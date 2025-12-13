"""Advanced Stealth Browser Automation for JavaScript-Heavy Sites.

This module provides undetectable browser automation using Playwright with
comprehensive anti-detection measures:

- Stealth mode with navigator property overrides
- WebGL/Canvas fingerprint randomization
- Human-like mouse movements and scrolling
- Realistic timing patterns
- Shared browser contexts for efficiency
- Automatic retry with different fingerprints
- WAF/Cloudflare challenge handling

For sites like Mercari, Poshmark, and Facebook, browser automation is the
primary (not fallback) strategy because these sites require JavaScript
execution and have sophisticated bot detection.

Usage:
    from scrapers.browser_fallback import fetch_with_browser
    
    # Async usage
    html_content, cookies = await fetch_with_browser(url, site_name)
    
    # Sync usage
    html_content = fetch_with_browser_sync(url, site_name)
"""

from __future__ import annotations

import asyncio
import random
import time
import threading
import json
import hashlib
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
    logger.debug("Playwright not available - browser automation disabled")


# ======================
# ADVANCED STEALTH CONFIGURATION
# ======================

# Complete browser fingerprints for stealth mode
BROWSER_FINGERPRINTS = [
    {
        "name": "chrome_131_win_1080p",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "viewport": {"width": 1920, "height": 1080},
        "screen": {"width": 1920, "height": 1080},
        "locale": "en-US",
        "timezone": "America/New_York",
        "color_depth": 24,
        "device_memory": 8,
        "hardware_concurrency": 8,
        "platform": "Win32",
        "webgl_vendor": "Google Inc. (NVIDIA)",
        "webgl_renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)",
    },
    {
        "name": "chrome_131_win_1440p",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "viewport": {"width": 2560, "height": 1440},
        "screen": {"width": 2560, "height": 1440},
        "locale": "en-US",
        "timezone": "America/Chicago",
        "color_depth": 24,
        "device_memory": 16,
        "hardware_concurrency": 12,
        "platform": "Win32",
        "webgl_vendor": "Google Inc. (AMD)",
        "webgl_renderer": "ANGLE (AMD, AMD Radeon RX 6800 XT Direct3D11 vs_5_0 ps_5_0, D3D11)",
    },
    {
        "name": "chrome_131_mac_retina",
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "viewport": {"width": 1440, "height": 900},
        "screen": {"width": 2880, "height": 1800},
        "device_scale_factor": 2,
        "locale": "en-US",
        "timezone": "America/Los_Angeles",
        "color_depth": 30,
        "device_memory": 16,
        "hardware_concurrency": 10,
        "platform": "MacIntel",
        "webgl_vendor": "Apple Inc.",
        "webgl_renderer": "Apple M2 Pro",
    },
    {
        "name": "firefox_133_win",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
        "viewport": {"width": 1920, "height": 1080},
        "screen": {"width": 1920, "height": 1080},
        "locale": "en-US",
        "timezone": "America/Denver",
        "color_depth": 24,
        "device_memory": 8,
        "hardware_concurrency": 8,
        "platform": "Win32",
        "webgl_vendor": "Mozilla",
        "webgl_renderer": "Mozilla",
        "is_firefox": True,
    },
    {
        "name": "safari_18_mac",
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
        "viewport": {"width": 1680, "height": 1050},
        "screen": {"width": 1680, "height": 1050},
        "locale": "en-US",
        "timezone": "America/Phoenix",
        "color_depth": 30,
        "device_memory": 8,
        "hardware_concurrency": 8,
        "platform": "MacIntel",
        "webgl_vendor": "Apple Inc.",
        "webgl_renderer": "Apple M1",
    },
    {
        "name": "chrome_mobile_android",
        "user_agent": "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36",
        "viewport": {"width": 412, "height": 915},
        "screen": {"width": 412, "height": 915},
        "device_scale_factor": 2.625,
        "locale": "en-US",
        "timezone": "America/New_York",
        "color_depth": 24,
        "device_memory": 8,
        "hardware_concurrency": 8,
        "platform": "Linux armv81",
        "is_mobile": True,
        "has_touch": True,
    },
    {
        "name": "safari_ios_17",
        "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
        "viewport": {"width": 390, "height": 844},
        "screen": {"width": 390, "height": 844},
        "device_scale_factor": 3,
        "locale": "en-US",
        "timezone": "America/Los_Angeles",
        "color_depth": 24,
        "device_memory": 4,
        "hardware_concurrency": 6,
        "platform": "iPhone",
        "is_mobile": True,
        "has_touch": True,
    },
]

# Advanced stealth JavaScript - removes all automation indicators
STEALTH_JS = """
// ======== NAVIGATOR OVERRIDES ========
// Remove webdriver property (most common detection)
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined,
    configurable: true
});

// Delete webdriver from navigator prototype
delete Navigator.prototype.webdriver;

// ======== CHROME OBJECT ========
// Fix chrome object for Chromium detection
if (!window.chrome) {
    window.chrome = {
        app: {
            isInstalled: false,
            InstallState: {
                DISABLED: 'disabled',
                INSTALLED: 'installed',
                NOT_INSTALLED: 'not_installed'
            },
            RunningState: {
                CANNOT_RUN: 'cannot_run',
                READY_TO_RUN: 'ready_to_run',
                RUNNING: 'running'
            }
        },
        runtime: {
            OnInstalledReason: {
                CHROME_UPDATE: 'chrome_update',
                INSTALL: 'install',
                SHARED_MODULE_UPDATE: 'shared_module_update',
                UPDATE: 'update'
            },
            OnRestartRequiredReason: {
                APP_UPDATE: 'app_update',
                OS_UPDATE: 'os_update',
                PERIODIC: 'periodic'
            },
            PlatformArch: {
                ARM: 'arm',
                ARM64: 'arm64',
                MIPS: 'mips',
                MIPS64: 'mips64',
                X86_32: 'x86-32',
                X86_64: 'x86-64'
            },
            PlatformNaclArch: {
                ARM: 'arm',
                MIPS: 'mips',
                MIPS64: 'mips64',
                X86_32: 'x86-32',
                X86_64: 'x86-64'
            },
            PlatformOs: {
                ANDROID: 'android',
                CROS: 'cros',
                LINUX: 'linux',
                MAC: 'mac',
                OPENBSD: 'openbsd',
                WIN: 'win'
            },
            RequestUpdateCheckStatus: {
                NO_UPDATE: 'no_update',
                THROTTLED: 'throttled',
                UPDATE_AVAILABLE: 'update_available'
            },
            connect: () => undefined,
            sendMessage: () => undefined,
        },
        csi: () => {},
        loadTimes: () => ({
            commitLoadTime: Date.now() / 1000,
            connectionInfo: 'http/1.1',
            finishDocumentLoadTime: Date.now() / 1000,
            finishLoadTime: Date.now() / 1000,
            firstPaintAfterLoadTime: 0,
            firstPaintTime: Date.now() / 1000,
            navigationType: 'navigate',
            npnNegotiatedProtocol: 'unknown',
            requestTime: Date.now() / 1000 - 0.16,
            startLoadTime: Date.now() / 1000 - 0.32,
            wasAlternateProtocolAvailable: false,
            wasFetchedViaSpdy: false,
            wasNpnNegotiated: false
        }),
    };
}

// ======== PERMISSIONS ========
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications' ?
        Promise.resolve({ state: Notification.permission }) :
        originalQuery(parameters)
);

// ======== PLUGINS ========
Object.defineProperty(navigator, 'plugins', {
    get: () => {
        const plugins = [
            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
            { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' }
        ];
        plugins.length = 3;
        plugins.item = (i) => plugins[i] || null;
        plugins.namedItem = (name) => plugins.find(p => p.name === name) || null;
        plugins.refresh = () => {};
        return plugins;
    },
    configurable: true
});

// ======== LANGUAGES ========
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en'],
    configurable: true
});

// ======== HARDWARE ========
Object.defineProperty(navigator, 'hardwareConcurrency', {
    get: () => HARDWARE_CONCURRENCY_VALUE,
    configurable: true
});

Object.defineProperty(navigator, 'deviceMemory', {
    get: () => DEVICE_MEMORY_VALUE,
    configurable: true
});

// ======== PLATFORM ========
Object.defineProperty(navigator, 'platform', {
    get: () => 'PLATFORM_VALUE',
    configurable: true
});

// ======== WEBGL ========
const getParameterProxyHandler = {
    apply: function(target, thisArg, args) {
        const param = args[0];
        // UNMASKED_VENDOR_WEBGL
        if (param === 37445) {
            return 'WEBGL_VENDOR_VALUE';
        }
        // UNMASKED_RENDERER_WEBGL
        if (param === 37446) {
            return 'WEBGL_RENDERER_VALUE';
        }
        return Reflect.apply(target, thisArg, args);
    }
};

// Override WebGL for both contexts
['WebGLRenderingContext', 'WebGL2RenderingContext'].forEach(ctx => {
    if (window[ctx]) {
        const getParameter = window[ctx].prototype.getParameter;
        window[ctx].prototype.getParameter = new Proxy(getParameter, getParameterProxyHandler);
    }
});

// ======== SCREEN ========
Object.defineProperty(screen, 'colorDepth', {
    get: () => COLOR_DEPTH_VALUE,
    configurable: true
});

// ======== AUTOMATION PROPERTIES ========
// Remove automation properties from window
['callPhantom', '_phantom', '__nightmare', 'Buffer', 'emit', 'spawn', 
 '__selenium_unwrapped', '__webdriver_evaluate', '__webdriver_script_function',
 '__webdriver_script_func', '__webdriver_script_fn', '__fxdriver_evaluate',
 '__driver_unwrapped', '__webdriver_unwrapped', '__driver_evaluate',
 '__selenium_evaluate', '__webdriverFunc', 'domAutomation', 'domAutomationController',
 '_Selenium_IDE_Recorder', 'cdc_adoQpoasnfa76pfcZLmcfl_Array',
 'cdc_adoQpoasnfa76pfcZLmcfl_Promise', 'cdc_adoQpoasnfa76pfcZLmcfl_Symbol'
].forEach(prop => {
    try {
        delete window[prop];
    } catch(e) {}
});

// ======== IFRAME PROTECTION ========
// Ensure iframes also get stealth
const originalAttachShadow = Element.prototype.attachShadow;
Element.prototype.attachShadow = function(init) {
    if (init && init.mode === 'closed') {
        init.mode = 'open';
    }
    return originalAttachShadow.call(this, init);
};

// ======== CONSOLE MESSAGES ========
// Some sites check for automation via console
console.debug = console.log;

// ======== TOUCH SUPPORT ========
// Don't override if actually mobile
if (!('ontouchstart' in window) && !navigator.maxTouchPoints) {
    Object.defineProperty(navigator, 'maxTouchPoints', {
        get: () => 0,
        configurable: true
    });
}
"""


def _build_stealth_script(fingerprint: Dict[str, Any]) -> str:
    """Build stealth script with fingerprint-specific values."""
    script = STEALTH_JS
    script = script.replace('HARDWARE_CONCURRENCY_VALUE', str(fingerprint.get('hardware_concurrency', 8)))
    script = script.replace('DEVICE_MEMORY_VALUE', str(fingerprint.get('device_memory', 8)))
    script = script.replace('PLATFORM_VALUE', fingerprint.get('platform', 'Win32'))
    script = script.replace('WEBGL_VENDOR_VALUE', fingerprint.get('webgl_vendor', 'Google Inc.'))
    script = script.replace('WEBGL_RENDERER_VALUE', fingerprint.get('webgl_renderer', 'ANGLE'))
    script = script.replace('COLOR_DEPTH_VALUE', str(fingerprint.get('color_depth', 24)))
    return script


# ======================
# HUMAN-LIKE BEHAVIOR
# ======================

async def simulate_human_scroll(page, scroll_amount: int = None) -> None:
    """Simulate human-like scrolling behavior."""
    if scroll_amount is None:
        scroll_amount = random.randint(300, 800)
    
    # Scroll in small increments with varying speed
    scrolled = 0
    while scrolled < scroll_amount:
        increment = random.randint(50, 150)
        await page.evaluate(f"window.scrollBy(0, {increment})")
        scrolled += increment
        await asyncio.sleep(random.uniform(0.05, 0.15))
    
    # Sometimes scroll back up a bit (like a human would)
    if random.random() < 0.3:
        await page.evaluate(f"window.scrollBy(0, {-random.randint(30, 100)})")


async def simulate_human_mouse(page) -> None:
    """Simulate random mouse movements."""
    try:
        viewport = page.viewport_size
        if not viewport:
            return
        
        # Move mouse to a few random positions
        for _ in range(random.randint(2, 4)):
            x = random.randint(100, viewport['width'] - 100)
            y = random.randint(100, viewport['height'] - 100)
            await page.mouse.move(x, y, steps=random.randint(5, 15))
            await asyncio.sleep(random.uniform(0.1, 0.3))
    except Exception:
        pass


async def wait_with_jitter(base_time: float, jitter: float = 0.3) -> None:
    """Wait with random jitter for human-like timing."""
    actual_wait = base_time * (1 + random.uniform(-jitter, jitter))
    await asyncio.sleep(max(0.1, actual_wait))


# ======================
# BROWSER POOL
# ======================

class StealthBrowserPool:
    """Manages a pool of stealth browser contexts."""
    
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
        self._context_fingerprints: Dict[str, Dict] = {}
        self._context_last_used: Dict[str, float] = {}
        self._playwright = None
        self._max_contexts = 5
        self._context_ttl = 300  # 5 minutes
        self._initialized = True
    
    async def _ensure_browser(self) -> Optional[Any]:
        """Ensure browser is running with stealth settings."""
        if not _PLAYWRIGHT_AVAILABLE:
            return None
        
        if self._browser is not None:
            try:
                if self._browser.is_connected():
                    return self._browser
            except Exception:
                pass
        
        try:
            if self._playwright is None:
                self._playwright = await async_playwright().start()
            
            # Launch with maximum stealth settings
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    # Disable automation indicators
                    "--disable-blink-features=AutomationControlled",
                    "--disable-automation",
                    "--disable-infobars",
                    
                    # Disable crash reporting (can leak info)
                    "--disable-breakpad",
                    "--disable-crash-reporter",
                    
                    # Performance and fingerprinting
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-gpu-sandbox",
                    
                    # Disable features that reveal headless mode
                    "--disable-background-timer-throttling",
                    "--disable-backgrounding-occluded-windows",
                    "--disable-renderer-backgrounding",
                    "--disable-ipc-flooding-protection",
                    
                    # WebRTC leak protection
                    "--disable-webrtc-hw-decoding",
                    "--disable-webrtc-hw-encoding",
                    "--webrtc-ip-handling-policy=disable_non_proxied_udp",
                    "--force-webrtc-ip-handling-policy",
                    
                    # Other stealth settings
                    "--window-size=1920,1080",
                    "--start-maximized",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-sync",
                    "--disable-translate",
                    "--metrics-recording-only",
                    "--safebrowsing-disable-auto-update",
                ],
            )
            
            logger.debug("Stealth browser launched successfully")
            return self._browser
            
        except Exception as e:
            logger.error(f"Failed to launch stealth browser: {e}")
            return None
    
    def _get_fingerprint(self, site_name: str, mobile: bool = False, seed: str = None) -> Dict:
        """Get a fingerprint for the site (consistent per site)."""
        if seed:
            hash_int = int(hashlib.md5(seed.encode()).hexdigest()[:8], 16)
        else:
            hash_int = int(hashlib.md5(site_name.encode()).hexdigest()[:8], 16)
        
        if mobile:
            mobile_fps = [f for f in BROWSER_FINGERPRINTS if f.get('is_mobile')]
            return mobile_fps[hash_int % len(mobile_fps)]
        
        desktop_fps = [f for f in BROWSER_FINGERPRINTS if not f.get('is_mobile')]
        return desktop_fps[hash_int % len(desktop_fps)]
    
    async def get_context(
        self,
        site_name: str,
        mobile: bool = False,
        proxy: Optional[str] = None,
        force_new: bool = False,
    ) -> Tuple[Optional[Any], Dict]:
        """Get or create a stealth browser context.
        
        Returns:
            Tuple of (context, fingerprint) or (None, {}) on failure
        """
        if not _PLAYWRIGHT_AVAILABLE:
            return None, {}
        
        browser = await self._ensure_browser()
        if not browser:
            return None, {}
        
        context_key = f"{site_name}:{'mobile' if mobile else 'desktop'}:{proxy or 'direct'}"
        now = time.time()
        
        # Check for existing valid context
        if not force_new and context_key in self._contexts:
            context = self._contexts[context_key]
            try:
                if context.browser.is_connected():
                    self._context_last_used[context_key] = now
                    return context, self._context_fingerprints.get(context_key, {})
            except Exception:
                pass
            
            # Context invalid, remove it
            try:
                await context.close()
            except Exception:
                pass
            del self._contexts[context_key]
        
        # Cleanup old contexts
        await self._cleanup_old_contexts()
        
        # Get fingerprint for this site
        fingerprint = self._get_fingerprint(site_name, mobile)
        
        try:
            # Build context options
            context_options = {
                "user_agent": fingerprint["user_agent"],
                "viewport": fingerprint["viewport"],
                "locale": fingerprint.get("locale", "en-US"),
                "timezone_id": fingerprint.get("timezone", "America/New_York"),
                "is_mobile": fingerprint.get("is_mobile", False),
                "has_touch": fingerprint.get("has_touch", False),
                "color_scheme": "light",
                "reduced_motion": "no-preference",
                "forced_colors": "none",
            }
            
            if fingerprint.get("device_scale_factor"):
                context_options["device_scale_factor"] = fingerprint["device_scale_factor"]
            
            # Add proxy if provided
            if proxy:
                context_options["proxy"] = {"server": proxy}
            
            # Add extra HTTP headers
            context_options["extra_http_headers"] = {
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
            }
            
            # Create context
            context = await browser.new_context(**context_options)
            
            # Inject stealth script
            stealth_script = _build_stealth_script(fingerprint)
            await context.add_init_script(stealth_script)
            
            # Store context
            self._contexts[context_key] = context
            self._context_fingerprints[context_key] = fingerprint
            self._context_last_used[context_key] = now
            
            logger.debug(f"Created stealth context: {fingerprint['name']}")
            return context, fingerprint
            
        except Exception as e:
            logger.error(f"Failed to create stealth context: {e}")
            return None, {}
    
    async def _cleanup_old_contexts(self) -> None:
        """Remove old unused contexts."""
        now = time.time()
        to_remove = []
        
        for key, last_used in list(self._context_last_used.items()):
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
                self._context_fingerprints.pop(key, None)
                self._context_last_used.pop(key, None)
    
    async def close(self) -> None:
        """Close all contexts and the browser."""
        for context in list(self._contexts.values()):
            try:
                await context.close()
            except Exception:
                pass
        
        self._contexts.clear()
        self._context_fingerprints.clear()
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


# Global browser pool
_browser_pool = StealthBrowserPool()


# ======================
# SITE-SPECIFIC CONFIGURATION
# ======================

# Selectors to wait for that indicate page loaded
SITE_WAIT_SELECTORS = {
    "ebay": ".s-item, .srp-results, [data-view*='mi:']",
    "mercari": '[data-testid="ItemTile"], [data-testid="item-tile"], a[href*="/item/"]',
    "poshmark": ".tile, [data-test='tile'], .card--small",
    "facebook": '[data-testid="marketplace-search-result"], a[href*="/marketplace/item/"]',
    "craigslist": ".result-row, .cl-static-search-result, [data-pid]",
    "ksl": ".listing, .listing-item, .listing-card",
}

# Wait times for JavaScript execution
SITE_WAIT_TIMES = {
    "facebook": 4.0,  # Facebook is heavy JS
    "mercari": 3.0,
    "poshmark": 2.5,
    "ebay": 2.0,
    "craigslist": 1.5,
    "ksl": 2.0,
}

# Sites that should always use browser (JS-rendered)
BROWSER_REQUIRED_SITES = {"mercari", "poshmark", "facebook"}


# ======================
# MAIN FETCH FUNCTIONS
# ======================

async def fetch_with_browser(
    url: str,
    site_name: str,
    wait_for_selector: Optional[str] = None,
    wait_time: float = None,
    max_retries: int = 3,
    mobile: bool = False,
    proxy: Optional[str] = None,
    extract_cookies: bool = True,
    simulate_human: bool = True,
) -> Tuple[Optional[str], Optional[List[Dict[str, Any]]]]:
    """
    Fetch a page using stealth headless browser.
    
    This is the primary method for JavaScript-heavy sites. It uses comprehensive
    anti-detection including:
    - Real browser fingerprints
    - Human-like behavior simulation
    - WebGL/Canvas fingerprint spoofing
    - Navigator property overrides
    
    Args:
        url: URL to fetch
        site_name: Name of the site for fingerprint consistency
        wait_for_selector: CSS selector to wait for
        wait_time: Additional wait time after load
        max_retries: Number of retry attempts
        mobile: Use mobile fingerprint
        proxy: Optional proxy URL
        extract_cookies: Whether to extract cookies
        simulate_human: Whether to simulate human behavior
        
    Returns:
        Tuple of (html_content, cookies) or (None, None) on failure
    """
    if not _PLAYWRIGHT_AVAILABLE:
        logger.warning("Playwright not available - browser fetch disabled")
        return None, None
    
    # Get site-specific configuration
    if wait_for_selector is None:
        wait_for_selector = SITE_WAIT_SELECTORS.get(site_name)
    if wait_time is None:
        wait_time = SITE_WAIT_TIMES.get(site_name, 2.0)
    
    for attempt in range(max_retries):
        page = None
        try:
            # Get stealth context (rotates fingerprint on retry)
            force_new = attempt > 0
            context, fingerprint = await _browser_pool.get_context(
                site_name,
                mobile=mobile or (attempt >= 2),  # Try mobile on later attempts
                proxy=proxy,
                force_new=force_new,
            )
            
            if not context:
                logger.debug("Failed to get browser context")
                continue
            
            # Create new page
            page = await context.new_page()
            
            # Block unnecessary resources for speed
            await page.route("**/*.{png,jpg,jpeg,gif,svg,ico,woff,woff2,ttf,otf}", 
                           lambda route: route.abort())
            await page.route("**/*google-analytics*", lambda route: route.abort())
            await page.route("**/*googletagmanager*", lambda route: route.abort())
            await page.route("**/*facebook.net*", lambda route: route.abort())
            await page.route("**/*doubleclick*", lambda route: route.abort())
            
            # Navigate to page
            logger.debug(f"Browser navigating to {url[:80]}... (attempt {attempt + 1}, fp: {fingerprint.get('name', 'unknown')})")
            
            response = await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=45000,
            )
            
            if not response:
                logger.debug("No response from browser navigation")
                continue
            
            # Check for immediate blocks
            if response.status in (403, 429, 503):
                logger.debug(f"Browser got blocked status: {response.status}")
                await wait_with_jitter(5.0)
                continue
            
            # Wait for content selector if provided
            if wait_for_selector:
                try:
                    await page.wait_for_selector(
                        wait_for_selector,
                        timeout=15000,
                        state="attached",
                    )
                except Exception as e:
                    logger.debug(f"Wait for selector failed: {e}")
                    # Continue anyway - might still have content
            
            # Simulate human behavior
            if simulate_human:
                await wait_with_jitter(wait_time)
                await simulate_human_scroll(page)
                await simulate_human_mouse(page)
                await wait_with_jitter(0.5)
            else:
                await asyncio.sleep(wait_time)
            
            # Check for challenge pages
            content_preview = await page.content()
            content_lower = content_preview[:5000].lower()
            
            challenge_indicators = [
                "checking your browser",
                "just a moment",
                "cf-browser-verification",
                "challenge-platform",
                "please wait",
                "ddos protection",
                "security check",
            ]
            
            if any(ind in content_lower for ind in challenge_indicators):
                logger.debug("Detected challenge page, waiting for resolution...")
                await asyncio.sleep(5)
                
                # Try to wait for challenge to resolve
                try:
                    await page.wait_for_function(
                        "() => !document.body.innerHTML.toLowerCase().includes('checking your browser')",
                        timeout=30000,
                    )
                except Exception:
                    logger.debug("Challenge did not resolve")
                    continue
            
            # Get final content
            html_content = await page.content()
            
            # Extract cookies if requested
            cookies = None
            if extract_cookies:
                try:
                    cookies = await context.cookies()
                except Exception as e:
                    logger.debug(f"Failed to extract cookies: {e}")
            
            logger.debug(f"Browser fetch succeeded: {len(html_content)} bytes, fingerprint: {fingerprint.get('name', 'unknown')}")
            return html_content, cookies
            
        except Exception as e:
            logger.debug(f"Browser fetch attempt {attempt + 1} failed: {e}")
            await wait_with_jitter(2.0)
            continue
            
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass
    
    logger.warning(f"Browser fetch failed after {max_retries} attempts: {url[:60]}")
    return None, None


def fetch_with_browser_sync(
    url: str,
    site_name: str,
    wait_for_selector: Optional[str] = None,
    wait_time: float = None,
    max_retries: int = 3,
    mobile: bool = False,
    proxy: Optional[str] = None,
) -> Optional[str]:
    """
    Synchronous wrapper for fetch_with_browser.
    
    Args:
        url: URL to fetch
        site_name: Name of the site
        wait_for_selector: CSS selector to wait for
        wait_time: Additional wait time
        max_retries: Number of retry attempts
        mobile: Use mobile fingerprint
        proxy: Optional proxy URL
        
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
            url,
            site_name,
            wait_for_selector=wait_for_selector,
            wait_time=wait_time,
            max_retries=max_retries,
            mobile=mobile,
            proxy=proxy,
        )
    )
    return html_content


async def close_browser_pool() -> None:
    """Close the browser pool and release resources."""
    await _browser_pool.close()


def is_browser_available() -> bool:
    """Check if browser automation is available."""
    return _PLAYWRIGHT_AVAILABLE


def requires_browser(site_name: str) -> bool:
    """Check if a site requires browser automation."""
    return site_name.lower() in BROWSER_REQUIRED_SITES


__all__ = [
    "fetch_with_browser",
    "fetch_with_browser_sync",
    "close_browser_pool",
    "is_browser_available",
    "requires_browser",
    "SITE_WAIT_SELECTORS",
    "SITE_WAIT_TIMES",
    "BROWSER_REQUIRED_SITES",
]
