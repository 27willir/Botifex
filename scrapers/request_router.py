"""Smart Request Router - Intelligent Strategy Selection for Web Scraping.

This module provides an intelligent request routing system that:
- Automatically selects the best strategy based on site difficulty
- Learns from failures and adapts strategy selection
- Cascades through fallback strategies on failure
- Integrates TLS fingerprint impersonation, browser automation, and proxies

Site Difficulty Levels:
- EASY: Simple sites with minimal bot detection (use curl_cffi)
- MEDIUM: Sites with basic protection (curl_cffi with stealth headers)
- HARD: Sites with sophisticated detection (headless browser required)
- EXTREME: Sites with advanced WAF/Cloudflare (browser + proxies + challenges)

Usage:
    from scrapers.request_router import smart_request, SmartRouter
    
    # Simple usage
    response = smart_request(url, "ebay", user_id="user123")
    
    # With custom options
    response = smart_request(
        url,
        "mercari",
        user_id="user123",
        force_browser=True,
        proxy=proxy_url,
    )
"""

from __future__ import annotations

import asyncio
import random
import time
import threading
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Tuple
from collections import defaultdict, deque

from utils import logger


class SiteDifficulty(Enum):
    """Difficulty levels for scraping sites."""
    EASY = auto()      # Simple HTTP with curl_cffi
    MEDIUM = auto()    # Stealth HTTP with fingerprinting
    HARD = auto()      # Browser required
    EXTREME = auto()   # Browser + proxies + challenges


class StrategyType(Enum):
    """Types of request strategies."""
    CURL_CFFI = "curl_cffi"           # TLS fingerprint impersonation
    CURL_CFFI_MOBILE = "curl_cffi_mobile"  # Mobile TLS fingerprint
    BROWSER = "browser"               # Headless browser
    BROWSER_MOBILE = "browser_mobile" # Mobile browser
    PROXY_CURL = "proxy_curl"         # Proxy + curl_cffi
    PROXY_BROWSER = "proxy_browser"   # Proxy + browser
    RSS_FEED = "rss_feed"             # RSS/API fallback


@dataclass
class SiteConfig:
    """Configuration for a specific site."""
    name: str
    difficulty: SiteDifficulty
    base_url: str
    
    # Strategy preferences (order matters)
    preferred_strategies: List[StrategyType] = field(default_factory=list)
    
    # Timing
    min_delay: float = 2.0
    max_delay: float = 6.0
    
    # Browser-specific
    wait_selector: Optional[str] = None
    wait_time: float = 2.0
    
    # Special features
    has_rss: bool = False
    rss_transform: Optional[Callable[[str], str]] = None
    requires_warmup: bool = False
    
    # Block detection patterns
    block_patterns: List[str] = field(default_factory=list)


# ======================
# SITE CONFIGURATIONS
# ======================

def _ebay_rss_transform(url: str) -> str:
    """Transform eBay URL to RSS."""
    if "_rss=" in url:
        return url
    joiner = "&" if "?" in url else "?"
    return f"{url}{joiner}_rss=1"


SITE_CONFIGS: Dict[str, SiteConfig] = {
    "ebay": SiteConfig(
        name="ebay",
        difficulty=SiteDifficulty.MEDIUM,
        base_url="https://www.ebay.com",
        preferred_strategies=[
            StrategyType.RSS_FEED,      # RSS is most reliable for eBay
            StrategyType.CURL_CFFI,
            StrategyType.CURL_CFFI_MOBILE,
            StrategyType.PROXY_CURL,
            StrategyType.BROWSER,
        ],
        min_delay=3.0,
        max_delay=8.0,
        wait_selector=".s-item, .srp-results",
        wait_time=2.0,
        has_rss=True,
        rss_transform=_ebay_rss_transform,
        block_patterns=["pardon our interruption", "bot protection", "attention required"],
    ),
    
    "craigslist": SiteConfig(
        name="craigslist",
        difficulty=SiteDifficulty.EASY,
        base_url="https://www.craigslist.org",
        preferred_strategies=[
            StrategyType.CURL_CFFI,
            StrategyType.CURL_CFFI_MOBILE,
            StrategyType.PROXY_CURL,
            StrategyType.BROWSER,
        ],
        min_delay=2.0,
        max_delay=5.0,
        wait_selector=".result-row, .cl-static-search-result",
        wait_time=1.5,
        block_patterns=["unusual activity", "blocked", "this ip"],
    ),
    
    "mercari": SiteConfig(
        name="mercari",
        difficulty=SiteDifficulty.HARD,
        base_url="https://www.mercari.com",
        preferred_strategies=[
            StrategyType.CURL_CFFI,         # curl_cffi works well with TLS impersonation
            StrategyType.CURL_CFFI_MOBILE,
            StrategyType.BROWSER,           # Browser as fallback
            StrategyType.PROXY_CURL,
            StrategyType.BROWSER_MOBILE,
        ],
        min_delay=4.0,
        max_delay=10.0,
        wait_selector='[data-testid="ItemTile"], a[href*="/item/"]',
        wait_time=3.0,
        requires_warmup=True,
        block_patterns=["security reasons", "bot detection", "unusual traffic", "please verify"],
    ),
    
    "ksl": SiteConfig(
        name="ksl",
        difficulty=SiteDifficulty.MEDIUM,
        base_url="https://www.ksl.com",
        preferred_strategies=[
            StrategyType.CURL_CFFI,
            StrategyType.CURL_CFFI_MOBILE,
            StrategyType.BROWSER,
            StrategyType.PROXY_CURL,
        ],
        min_delay=3.0,
        max_delay=8.0,
        wait_selector=".listing, .listing-item",
        wait_time=2.0,
        block_patterns=["unusual activity", "slow down", "blocked"],
    ),
    
    "poshmark": SiteConfig(
        name="poshmark",
        difficulty=SiteDifficulty.HARD,
        base_url="https://poshmark.com",
        preferred_strategies=[
            StrategyType.BROWSER,
            StrategyType.BROWSER_MOBILE,
            StrategyType.PROXY_BROWSER,
            StrategyType.CURL_CFFI,
        ],
        min_delay=4.0,
        max_delay=10.0,
        wait_selector=".tile, [data-test='tile']",
        wait_time=2.5,
        requires_warmup=True,
        block_patterns=["access denied", "security check", "please verify"],
    ),
    
    "facebook": SiteConfig(
        name="facebook",
        difficulty=SiteDifficulty.EXTREME,
        base_url="https://www.facebook.com",
        preferred_strategies=[
            StrategyType.BROWSER,           # Only browser works for Facebook
            StrategyType.BROWSER_MOBILE,
            StrategyType.PROXY_BROWSER,
        ],
        min_delay=5.0,
        max_delay=12.0,
        wait_selector='a[href*="/marketplace/item/"]',
        wait_time=4.0,
        requires_warmup=True,
        block_patterns=["log in", "create an account", "security check", "confirm your identity"],
    ),
}


# ======================
# STRATEGY EXECUTION
# ======================

@dataclass
class StrategyResult:
    """Result of a strategy execution."""
    success: bool
    response: Any = None
    html_content: Optional[str] = None
    cookies: Optional[List[Dict]] = None
    strategy: StrategyType = None
    response_time: float = 0.0
    error: Optional[str] = None
    is_blocked: bool = False


class StrategyExecutor:
    """Executes individual request strategies."""
    
    def __init__(self):
        self._curl_cffi_available = False
        self._browser_available = False
        self._proxy_manager = None
        
        # Try to import modules
        try:
            from scrapers.stealth_client import stealth_get, is_curl_cffi_available
            self._stealth_get = stealth_get
            self._curl_cffi_available = is_curl_cffi_available()
        except ImportError:
            self._stealth_get = None
        
        try:
            from scrapers.browser_fallback import fetch_with_browser_sync, is_browser_available
            self._browser_fetch = fetch_with_browser_sync
            self._browser_available = is_browser_available()
        except ImportError:
            self._browser_fetch = None
    
    def _check_blocked(self, response, site_config: SiteConfig) -> bool:
        """Check if response indicates blocking."""
        if response is None:
            return True
        
        # Check status codes
        status = getattr(response, 'status_code', 200)
        if status in (403, 429, 503):
            return True
        
        # Check content for block patterns
        text = ""
        if hasattr(response, 'text'):
            text = response.text[:5000].lower() if response.text else ""
        elif isinstance(response, str):
            text = response[:5000].lower()
        
        # Check site-specific patterns
        for pattern in site_config.block_patterns:
            if pattern.lower() in text:
                return True
        
        # Check common patterns
        common_patterns = [
            "captcha", "access denied", "blocked", "unusual traffic",
            "verify you are human", "security check", "checking your browser",
        ]
        for pattern in common_patterns:
            if pattern in text:
                return True
        
        return False
    
    def execute_curl_cffi(
        self,
        url: str,
        site_config: SiteConfig,
        user_id: Optional[str] = None,
        mobile: bool = False,
        proxy: Optional[str] = None,
    ) -> StrategyResult:
        """Execute curl_cffi strategy with TLS fingerprint impersonation."""
        if not self._curl_cffi_available or not self._stealth_get:
            return StrategyResult(
                success=False,
                error="curl_cffi not available",
                strategy=StrategyType.CURL_CFFI_MOBILE if mobile else StrategyType.CURL_CFFI,
            )
        
        start_time = time.time()
        try:
            response = self._stealth_get(
                url,
                site_config.name,
                user_id=user_id,
                proxy=proxy,
                mobile=mobile,
                timeout=45,
            )
            
            response_time = time.time() - start_time
            
            if response is None:
                return StrategyResult(
                    success=False,
                    error="No response",
                    response_time=response_time,
                    strategy=StrategyType.CURL_CFFI_MOBILE if mobile else StrategyType.CURL_CFFI,
                )
            
            is_blocked = self._check_blocked(response, site_config)
            
            return StrategyResult(
                success=not is_blocked,
                response=response,
                html_content=response.text if hasattr(response, 'text') else None,
                response_time=response_time,
                is_blocked=is_blocked,
                strategy=StrategyType.CURL_CFFI_MOBILE if mobile else StrategyType.CURL_CFFI,
            )
            
        except Exception as e:
            return StrategyResult(
                success=False,
                error=str(e),
                response_time=time.time() - start_time,
                strategy=StrategyType.CURL_CFFI_MOBILE if mobile else StrategyType.CURL_CFFI,
            )
    
    def execute_browser(
        self,
        url: str,
        site_config: SiteConfig,
        user_id: Optional[str] = None,
        mobile: bool = False,
        proxy: Optional[str] = None,
    ) -> StrategyResult:
        """Execute browser strategy with stealth automation."""
        if not self._browser_available or not self._browser_fetch:
            return StrategyResult(
                success=False,
                error="Browser not available",
                strategy=StrategyType.BROWSER_MOBILE if mobile else StrategyType.BROWSER,
            )
        
        start_time = time.time()
        try:
            html_content = self._browser_fetch(
                url,
                site_config.name,
                wait_for_selector=site_config.wait_selector,
                wait_time=site_config.wait_time,
                mobile=mobile,
                proxy=proxy,
                max_retries=2,
            )
            
            response_time = time.time() - start_time
            
            if html_content is None:
                return StrategyResult(
                    success=False,
                    error="Browser fetch returned None",
                    response_time=response_time,
                    strategy=StrategyType.BROWSER_MOBILE if mobile else StrategyType.BROWSER,
                )
            
            is_blocked = self._check_blocked(html_content, site_config)
            
            return StrategyResult(
                success=not is_blocked,
                html_content=html_content,
                response_time=response_time,
                is_blocked=is_blocked,
                strategy=StrategyType.BROWSER_MOBILE if mobile else StrategyType.BROWSER,
            )
            
        except Exception as e:
            return StrategyResult(
                success=False,
                error=str(e),
                response_time=time.time() - start_time,
                strategy=StrategyType.BROWSER_MOBILE if mobile else StrategyType.BROWSER,
            )
    
    def execute_rss(
        self,
        url: str,
        site_config: SiteConfig,
        user_id: Optional[str] = None,
    ) -> StrategyResult:
        """Execute RSS/API fallback strategy."""
        if not site_config.has_rss or not site_config.rss_transform:
            return StrategyResult(
                success=False,
                error="RSS not available for this site",
                strategy=StrategyType.RSS_FEED,
            )
        
        rss_url = site_config.rss_transform(url)
        
        start_time = time.time()
        try:
            if self._curl_cffi_available and self._stealth_get:
                response = self._stealth_get(
                    rss_url,
                    site_config.name,
                    user_id=user_id,
                    headers={"Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8"},
                    timeout=30,
                )
            else:
                import requests
                response = requests.get(
                    rss_url,
                    headers={"Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8"},
                    timeout=30,
                )
            
            response_time = time.time() - start_time
            
            if response is None:
                return StrategyResult(
                    success=False,
                    error="No RSS response",
                    response_time=response_time,
                    strategy=StrategyType.RSS_FEED,
                )
            
            # RSS responses are usually valid if they contain XML
            content = response.text if hasattr(response, 'text') else str(response)
            is_valid_rss = '<?xml' in content[:100] or '<rss' in content[:500]
            
            return StrategyResult(
                success=is_valid_rss,
                response=response,
                html_content=content,
                response_time=response_time,
                is_blocked=not is_valid_rss,
                strategy=StrategyType.RSS_FEED,
            )
            
        except Exception as e:
            return StrategyResult(
                success=False,
                error=str(e),
                response_time=time.time() - start_time,
                strategy=StrategyType.RSS_FEED,
            )
    
    def execute(
        self,
        strategy: StrategyType,
        url: str,
        site_config: SiteConfig,
        user_id: Optional[str] = None,
        proxy: Optional[str] = None,
    ) -> StrategyResult:
        """Execute a specific strategy."""
        if strategy == StrategyType.CURL_CFFI:
            return self.execute_curl_cffi(url, site_config, user_id, mobile=False, proxy=None)
        elif strategy == StrategyType.CURL_CFFI_MOBILE:
            return self.execute_curl_cffi(url, site_config, user_id, mobile=True, proxy=None)
        elif strategy == StrategyType.BROWSER:
            return self.execute_browser(url, site_config, user_id, mobile=False, proxy=None)
        elif strategy == StrategyType.BROWSER_MOBILE:
            return self.execute_browser(url, site_config, user_id, mobile=True, proxy=None)
        elif strategy == StrategyType.PROXY_CURL:
            return self.execute_curl_cffi(url, site_config, user_id, mobile=False, proxy=proxy)
        elif strategy == StrategyType.PROXY_BROWSER:
            return self.execute_browser(url, site_config, user_id, mobile=False, proxy=proxy)
        elif strategy == StrategyType.RSS_FEED:
            return self.execute_rss(url, site_config, user_id)
        else:
            return StrategyResult(success=False, error=f"Unknown strategy: {strategy}")


# ======================
# SMART ROUTER
# ======================

@dataclass
class StrategyStats:
    """Statistics for a strategy's performance."""
    total_attempts: int = 0
    successes: int = 0
    failures: int = 0
    blocks: int = 0
    total_response_time: float = 0.0
    recent_results: deque = field(default_factory=lambda: deque(maxlen=20))
    
    @property
    def success_rate(self) -> float:
        if self.total_attempts == 0:
            return 0.5  # Unknown, assume 50%
        return self.successes / self.total_attempts
    
    @property
    def avg_response_time(self) -> float:
        if self.successes == 0:
            return 30.0  # Default high value
        return self.total_response_time / self.successes
    
    @property
    def recent_success_rate(self) -> float:
        if not self.recent_results:
            return 0.5
        return sum(1 for r in self.recent_results if r) / len(self.recent_results)
    
    def record(self, success: bool, response_time: float = 0.0, is_block: bool = False):
        self.total_attempts += 1
        if success:
            self.successes += 1
            self.total_response_time += response_time
        else:
            self.failures += 1
            if is_block:
                self.blocks += 1
        self.recent_results.append(success)


class SmartRouter:
    """Intelligent request router that learns and adapts strategy selection."""
    
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
        
        self._executor = StrategyExecutor()
        self._stats: Dict[str, Dict[StrategyType, StrategyStats]] = defaultdict(
            lambda: defaultdict(StrategyStats)
        )
        self._lock = threading.Lock()
        self._initialized = True
        
        # Proxy manager reference (set externally)
        self._proxy_manager = None
    
    def set_proxy_manager(self, proxy_manager) -> None:
        """Set the proxy manager for proxy strategies."""
        self._proxy_manager = proxy_manager
    
    def _get_config(self, site_name: str) -> SiteConfig:
        """Get configuration for a site."""
        if site_name in SITE_CONFIGS:
            return SITE_CONFIGS[site_name]
        
        # Default config for unknown sites
        return SiteConfig(
            name=site_name,
            difficulty=SiteDifficulty.MEDIUM,
            base_url=f"https://{site_name}.com",
            preferred_strategies=[
                StrategyType.CURL_CFFI,
                StrategyType.BROWSER,
                StrategyType.CURL_CFFI_MOBILE,
                StrategyType.BROWSER_MOBILE,
            ],
        )
    
    def _select_strategies(self, site_config: SiteConfig) -> List[StrategyType]:
        """Select and order strategies based on performance stats."""
        available = list(site_config.preferred_strategies)
        
        with self._lock:
            site_stats = self._stats.get(site_config.name, {})
            
            # If we have enough data, reorder by recent success rate
            if site_stats:
                def score(strategy: StrategyType) -> float:
                    stats = site_stats.get(strategy)
                    if not stats or stats.total_attempts < 3:
                        return 0.5  # Unknown
                    # Weight recent performance heavily
                    return stats.recent_success_rate * 0.7 + stats.success_rate * 0.3
                
                # Sort by success rate (descending)
                available.sort(key=score, reverse=True)
        
        return available
    
    def _get_proxy(self, site_name: str) -> Optional[str]:
        """Get a proxy for the request."""
        if self._proxy_manager:
            return self._proxy_manager.get_proxy(site_name)
        return None
    
    def request(
        self,
        url: str,
        site_name: str,
        user_id: Optional[str] = None,
        force_browser: bool = False,
        force_curl: bool = False,
        max_strategies: int = 4,
    ) -> StrategyResult:
        """
        Make a smart request with automatic strategy selection and fallback.
        
        Args:
            url: URL to fetch
            site_name: Name of the target site
            user_id: Optional user ID for session isolation
            force_browser: Force browser strategy first
            force_curl: Force curl_cffi strategy first
            max_strategies: Maximum number of strategies to try
            
        Returns:
            StrategyResult with response data
        """
        site_config = self._get_config(site_name)
        
        # Get ordered list of strategies
        strategies = self._select_strategies(site_config)
        
        # Apply force flags
        if force_browser:
            strategies = [s for s in strategies if 'browser' in s.value.lower()]
            strategies.extend([s for s in site_config.preferred_strategies if 'browser' not in s.value.lower()])
        elif force_curl:
            strategies = [s for s in strategies if 'curl' in s.value.lower()]
            strategies.extend([s for s in site_config.preferred_strategies if 'curl' not in s.value.lower()])
        
        # Limit strategies
        strategies = strategies[:max_strategies]
        
        # Get proxy for proxy strategies
        proxy = self._get_proxy(site_name)
        
        # Try each strategy in order
        for idx, strategy in enumerate(strategies):
            # Add delay between attempts
            if idx > 0:
                delay = random.uniform(site_config.min_delay, site_config.max_delay)
                logger.debug(f"{site_name}: Waiting {delay:.1f}s before strategy {strategy.value}")
                time.sleep(delay)
            
            logger.info(f"{site_name}: Trying strategy {strategy.value} ({idx + 1}/{len(strategies)})")
            
            result = self._executor.execute(
                strategy,
                url,
                site_config,
                user_id=user_id,
                proxy=proxy if 'proxy' in strategy.value.lower() else None,
            )
            
            # Record stats
            with self._lock:
                self._stats[site_name][strategy].record(
                    result.success,
                    result.response_time,
                    result.is_blocked,
                )
            
            if result.success:
                logger.info(f"{site_name}: Strategy {strategy.value} succeeded in {result.response_time:.2f}s")
                return result
            
            if result.is_blocked:
                logger.warning(f"{site_name}: Strategy {strategy.value} was blocked")
            else:
                logger.debug(f"{site_name}: Strategy {strategy.value} failed: {result.error}")
        
        # All strategies failed
        logger.error(f"{site_name}: All {len(strategies)} strategies exhausted for {url[:60]}")
        return StrategyResult(
            success=False,
            error="All strategies exhausted",
        )
    
    def get_stats(self, site_name: Optional[str] = None) -> Dict[str, Any]:
        """Get performance statistics."""
        with self._lock:
            if site_name:
                site_stats = self._stats.get(site_name, {})
                return {
                    "site": site_name,
                    "strategies": {
                        strategy.value: {
                            "attempts": stats.total_attempts,
                            "success_rate": round(stats.success_rate * 100, 1),
                            "recent_success_rate": round(stats.recent_success_rate * 100, 1),
                            "avg_response_time": round(stats.avg_response_time, 2),
                            "blocks": stats.blocks,
                        }
                        for strategy, stats in site_stats.items()
                    }
                }
            
            return {
                site: self.get_stats(site)
                for site in self._stats
            }


# Global router instance
_router = SmartRouter()


# ======================
# PUBLIC API
# ======================

def smart_request(
    url: str,
    site_name: str,
    user_id: Optional[str] = None,
    force_browser: bool = False,
    force_curl: bool = False,
    max_strategies: int = 4,
) -> StrategyResult:
    """
    Make a smart request with automatic strategy selection.
    
    This is the main entry point for making scraping requests. It automatically:
    - Selects the best strategy based on site difficulty and history
    - Falls back through multiple strategies on failure
    - Uses TLS fingerprint impersonation when possible
    - Falls back to browser automation for difficult sites
    
    Args:
        url: URL to fetch
        site_name: Name of the target site (e.g., "ebay", "mercari")
        user_id: Optional user ID for session isolation
        force_browser: Force browser strategy first
        force_curl: Force curl_cffi strategy first
        max_strategies: Maximum strategies to try
        
    Returns:
        StrategyResult with success status and response data
    """
    return _router.request(
        url,
        site_name,
        user_id=user_id,
        force_browser=force_browser,
        force_curl=force_curl,
        max_strategies=max_strategies,
    )


def get_router_stats(site_name: Optional[str] = None) -> Dict[str, Any]:
    """Get router performance statistics."""
    return _router.get_stats(site_name)


def get_site_config(site_name: str) -> SiteConfig:
    """Get configuration for a site."""
    return SITE_CONFIGS.get(site_name) or SiteConfig(
        name=site_name,
        difficulty=SiteDifficulty.MEDIUM,
        base_url=f"https://{site_name}.com",
    )


def set_proxy_manager(proxy_manager) -> None:
    """Set the proxy manager for the router."""
    _router.set_proxy_manager(proxy_manager)


__all__ = [
    "smart_request",
    "get_router_stats",
    "get_site_config",
    "set_proxy_manager",
    "SmartRouter",
    "StrategyResult",
    "StrategyType",
    "SiteDifficulty",
    "SiteConfig",
    "SITE_CONFIGS",
]

