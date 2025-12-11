"""Browser-based fallback for JavaScript-heavy sites.

This module provides a Playwright-based fallback when normal HTTP requests fail
due to JavaScript challenges or complex anti-bot systems. It implements:

- Headless browser automation with stealth techniques
- Shared browser contexts for efficiency
- Automatic retry with different browser fingerprints
- Cookie extraction for use in subsequent requests
- Page content extraction after JavaScript execution

Usage:
    from scrapers.browser_fallback import fetch_with_browser
    
    html_content = await fetch_with_browser(url, site_name)
    if html_content:
        # Process the rendered HTML
        pass
"""

from __future__ import annotations

import asyncio
import random
import time
import threading
from typing import Any, Dict, List, Optional, Tuple
from contextlib import asynccontextmanager

from utils import logger

# Browser availability flag
_PLAYWRIGHT_AVAILABLE = False
_playwright = None
_async_playwright = None

try:
    from playwright.async_api import async_playwright, Browser, BrowserContext, Page
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    logger.debug("Playwright not available - browser fallback disabled")


# Browser configurations for different fingerprints
BROWSER_CONFIGS = [
    {
        "name": "chrome_desktop",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
        "viewport": {"width": 1920, "height": 1080},
        "locale": "en-US",
        "timezone": "America/New_York",
    },
    {
        "name": "chrome_mac",
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
        "viewport": {"width": 1440, "height": 900},
        "locale": "en-US",
        "timezone": "America/Los_Angeles",
    },
    {
        "name": "firefox_desktop",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:135.0) Gecko/20100101 Firefox/135.0",
        "viewport": {"width": 1920, "height": 1080},
        "locale": "en-US",
        "timezone": "America/Chicago",
    },
    {
        "name": "safari_mac",
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
        "viewport": {"width": 1680, "height": 1050},
        "locale": "en-US",
        "timezone": "America/Denver",
    },
    {
        "name": "mobile_iphone",
        "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
        "viewport": {"width": 390, "height": 844},
        "locale": "en-US",
        "timezone": "America/New_York",
        "is_mobile": True,
    },
]

# Stealth JavaScript to inject
STEALTH_JS = """
// Remove webdriver property
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined
});

// Fix chrome property
if (!window.chrome) {
    window.chrome = {
        runtime: {},
    };
}

// Fix permissions
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications' ?
        Promise.resolve({ state: Notification.permission }) :
        originalQuery(parameters)
);

// Fix plugins
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5],
});

// Fix languages
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en'],
});

// Fix platform
Object.defineProperty(navigator, 'platform', {
    get: () => 'Win32',
});

// Fix hardware concurrency
Object.defineProperty(navigator, 'hardwareConcurrency', {
    get: () => 8,
});

// Fix device memory
Object.defineProperty(navigator, 'deviceMemory', {
    get: () => 8,
});
"""


class BrowserPool:
    """Manages a pool of browser contexts for efficient reuse."""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._browser: Optional[Any] = None
        self._contexts: Dict[str, Any] = {}
        self._context_last_used: Dict[str, float] = {}
        self._async_lock = None
        self._playwright = None
        self._max_contexts = 5
        self._context_ttl = 300  # 5 minutes
        self._initialized = True
    
    async def _ensure_browser(self) -> Optional[Any]:
        """Ensure browser is running."""
        if not _PLAYWRIGHT_AVAILABLE:
            return None
        
        if self._browser is not None and self._browser.is_connected():
            return self._browser
        
        try:
            if self._playwright is None:
                self._playwright = await async_playwright().start()
            
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-accelerated-2d-canvas",
                    "--disable-gpu",
                ],
            )
            return self._browser
        except Exception as e:
            logger.error(f"Failed to launch browser: {e}")
            return None
    
    async def get_context(
        self,
        site_name: str,
        config: Optional[Dict[str, Any]] = None,
    ) -> Optional[Any]:
        """Get or create a browser context for the site."""
        if not _PLAYWRIGHT_AVAILABLE:
            return None
        
        browser = await self._ensure_browser()
        if not browser:
            return None
        
        context_key = f"{site_name}:{config.get('name', 'default') if config else 'default'}"
        
        # Check for existing context
        if context_key in self._contexts:
            context = self._contexts[context_key]
            if context and not context.browser.is_connected():
                # Browser disconnected, remove stale context
                del self._contexts[context_key]
            else:
                self._context_last_used[context_key] = time.time()
                return context
        
        # Cleanup old contexts if at limit
        await self._cleanup_old_contexts()
        
        # Create new context
        try:
            config = config or random.choice(BROWSER_CONFIGS)
            
            context = await browser.new_context(
                user_agent=config.get("user_agent"),
                viewport=config.get("viewport"),
                locale=config.get("locale", "en-US"),
                timezone_id=config.get("timezone", "America/New_York"),
                is_mobile=config.get("is_mobile", False),
                has_touch=config.get("is_mobile", False),
            )
            
            # Add stealth scripts
            await context.add_init_script(STEALTH_JS)
            
            self._contexts[context_key] = context
            self._context_last_used[context_key] = time.time()
            
            return context
        except Exception as e:
            logger.error(f"Failed to create browser context: {e}")
            return None
    
    async def _cleanup_old_contexts(self) -> None:
        """Remove old unused contexts."""
        now = time.time()
        to_remove = []
        
        for key, last_used in self._context_last_used.items():
            if now - last_used > self._context_ttl:
                to_remove.append(key)
        
        # Also remove if over limit
        if len(self._contexts) >= self._max_contexts:
            sorted_contexts = sorted(
                self._context_last_used.items(),
                key=lambda x: x[1]
            )
            to_remove.extend([k for k, _ in sorted_contexts[:len(sorted_contexts) - self._max_contexts + 1]])
        
        for key in set(to_remove):
            if key in self._contexts:
                try:
                    await self._contexts[key].close()
                except Exception:
                    pass
                del self._contexts[key]
                self._context_last_used.pop(key, None)
    
    async def close(self) -> None:
        """Close all contexts and the browser."""
        for context in self._contexts.values():
            try:
                await context.close()
            except Exception:
                pass
        
        self._contexts.clear()
        self._context_last_used.clear()
        
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None


# Global browser pool instance
_browser_pool = BrowserPool()


async def fetch_with_browser(
    url: str,
    site_name: str,
    wait_for_selector: Optional[str] = None,
    wait_time: float = 2.0,
    max_retries: int = 2,
    extract_cookies: bool = True,
) -> Tuple[Optional[str], Optional[List[Dict[str, Any]]]]:
    """
    Fetch a page using a headless browser.
    
    Args:
        url: URL to fetch
        site_name: Name of the site for context reuse
        wait_for_selector: CSS selector to wait for before extracting content
        wait_time: Additional wait time after page load (seconds)
        max_retries: Number of retry attempts
        extract_cookies: Whether to extract cookies for later use
        
    Returns:
        tuple: (html_content, cookies) or (None, None) on failure
    """
    if not _PLAYWRIGHT_AVAILABLE:
        logger.warning("Playwright not available - cannot use browser fallback")
        return None, None
    
    for attempt in range(max_retries):
        try:
            # Get random config for this attempt
            config = BROWSER_CONFIGS[attempt % len(BROWSER_CONFIGS)]
            
            context = await _browser_pool.get_context(site_name, config)
            if not context:
                continue
            
            page = await context.new_page()
            
            try:
                # Navigate with timeout
                response = await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=30000,
                )
                
                if not response:
                    logger.debug(f"Browser fallback: No response for {url}")
                    continue
                
                # Wait for specific selector if provided
                if wait_for_selector:
                    try:
                        await page.wait_for_selector(
                            wait_for_selector,
                            timeout=10000,
                        )
                    except Exception:
                        logger.debug(f"Browser fallback: Selector '{wait_for_selector}' not found")
                
                # Additional wait for JavaScript execution
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                
                # Scroll to trigger lazy loading
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
                await asyncio.sleep(0.5)
                
                # Extract content
                html_content = await page.content()
                
                # Extract cookies if requested
                cookies = None
                if extract_cookies:
                    cookies = await context.cookies()
                
                logger.debug(f"Browser fallback: Successfully fetched {url} (config: {config['name']})")
                return html_content, cookies
                
            finally:
                await page.close()
                
        except Exception as e:
            logger.debug(f"Browser fallback attempt {attempt + 1} failed: {e}")
            continue
    
    logger.warning(f"Browser fallback: All {max_retries} attempts failed for {url}")
    return None, None


def fetch_with_browser_sync(
    url: str,
    site_name: str,
    wait_for_selector: Optional[str] = None,
    wait_time: float = 2.0,
    max_retries: int = 2,
) -> Optional[str]:
    """
    Synchronous wrapper for fetch_with_browser.
    
    Args:
        url: URL to fetch
        site_name: Name of the site
        wait_for_selector: CSS selector to wait for
        wait_time: Additional wait time
        max_retries: Number of retry attempts
        
    Returns:
        HTML content or None on failure
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    html_content, _ = loop.run_until_complete(
        fetch_with_browser(
            url, site_name, wait_for_selector, wait_time, max_retries
        )
    )
    return html_content


async def close_browser_pool() -> None:
    """Close the browser pool and release resources."""
    await _browser_pool.close()


def is_browser_available() -> bool:
    """Check if browser fallback is available."""
    return _PLAYWRIGHT_AVAILABLE


# Site-specific selectors to wait for
SITE_WAIT_SELECTORS = {
    "ebay": ".s-item, .srp-results",
    "mercari": '[data-testid="ItemTile"], a[href*="/item/"]',
    "poshmark": ".tile, [data-test='tile']",
    "facebook": '[data-testid="marketplace-search-result"], a[href*="/marketplace/item/"]',
    "craigslist": ".result-row, .cl-static-search-result",
    "ksl": ".listing, .listing-item",
}


async def fetch_site_with_browser(
    url: str,
    site_name: str,
    max_retries: int = 2,
) -> Optional[str]:
    """
    Fetch a site using browser with site-specific optimizations.
    
    Args:
        url: URL to fetch
        site_name: Name of the site
        max_retries: Number of retry attempts
        
    Returns:
        HTML content or None on failure
    """
    wait_selector = SITE_WAIT_SELECTORS.get(site_name)
    
    # Adjust wait time based on site
    wait_times = {
        "facebook": 3.0,  # Facebook is slow
        "mercari": 2.5,
        "poshmark": 2.0,
        "ebay": 2.0,
        "craigslist": 1.5,
        "ksl": 1.5,
    }
    wait_time = wait_times.get(site_name, 2.0)
    
    html_content, cookies = await fetch_with_browser(
        url,
        site_name,
        wait_for_selector=wait_selector,
        wait_time=wait_time,
        max_retries=max_retries,
        extract_cookies=True,
    )
    
    return html_content


__all__ = [
    "fetch_with_browser",
    "fetch_with_browser_sync",
    "fetch_site_with_browser",
    "close_browser_pool",
    "is_browser_available",
    "SITE_WAIT_SELECTORS",
]

