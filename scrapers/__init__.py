"""Advanced Scraping Infrastructure with Anti-Detection.

This package provides enterprise-grade web scraping with comprehensive
anti-detection measures:

Core Components:
- stealth_client: TLS fingerprint impersonation using curl_cffi
- browser_fallback: Stealth Playwright browser automation
- request_router: Intelligent strategy selection and fallback
- proxy_manager: Residential proxy rotation with health tracking
- waf_bypass: Cloudflare/DataDome challenge handling
- anti_blocking: Request timing and fingerprint management

Quick Start:
    from scrapers import smart_request, is_smart_request_available
    
    if is_smart_request_available():
        result = smart_request("https://example.com", "example")
        if result.success:
            print(result.html_content)

Configuration:
    Set environment variables for proxies:
    - SCRAPER_PROXIES: Comma-separated proxy URLs
    - BRIGHTDATA_PROXY: BrightData residential proxy URL
    - SMARTPROXY_PROXY: SmartProxy residential proxy URL
    
    Install optional dependencies:
    - pip install curl_cffi  # TLS fingerprint impersonation
    - pip install playwright && playwright install chromium  # Browser automation
"""

from scrapers import anti_blocking

# Export core anti-blocking functions
from scrapers.anti_blocking import (
    build_headers,
    build_mobile_headers,
    detect_soft_block,
    pre_request_wait,
    record_block,
    record_failure,
    record_request_start,
    record_success,
    suggest_retry_delay,
    get_proxy,
    rotate_proxy,
    add_proxies,
    get_proxy_stats,
    get_site_stats,
    get_all_site_stats,
    randomize_params_order,
    add_request_jitter,
    simulate_reading_time,
    get_progressive_delay,
)

# Try to import advanced stealth components
_STEALTH_CLIENT_AVAILABLE = False
_BROWSER_AVAILABLE = False
_ROUTER_AVAILABLE = False
_PROXY_MANAGER_AVAILABLE = False
_WAF_BYPASS_AVAILABLE = False

try:
    from scrapers.stealth_client import (
        stealth_get,
        stealth_post,
        is_curl_cffi_available,
        get_session_stats,
        invalidate_session,
        get_available_impersonations,
    )
    _STEALTH_CLIENT_AVAILABLE = True
except ImportError:
    pass

try:
    from scrapers.browser_fallback import (
        fetch_with_browser,
        fetch_with_browser_sync,
        is_browser_available,
        requires_browser,
        close_browser_pool,
        SITE_WAIT_SELECTORS,
        BROWSER_REQUIRED_SITES,
    )
    _BROWSER_AVAILABLE = True
except ImportError:
    pass

try:
    from scrapers.request_router import (
        smart_request,
        get_router_stats,
        get_site_config,
        set_proxy_manager,
        StrategyResult,
        StrategyType,
        SiteDifficulty,
        SITE_CONFIGS,
    )
    _ROUTER_AVAILABLE = True
except ImportError:
    pass

try:
    from scrapers.proxy_manager import (
        get_proxy as get_smart_proxy,
        record_proxy_success,
        record_proxy_failure,
        rotate_proxy as rotate_smart_proxy,
        add_proxies as add_smart_proxies,
        add_free_proxies,
        get_proxy_stats as get_smart_proxy_stats,
        has_proxies,
        blacklist_proxy,
        get_proxy_manager,
        ProxyConfig,
        ProxyType,
        ProxyProvider,
    )
    _PROXY_MANAGER_AVAILABLE = True
except ImportError:
    pass

try:
    from scrapers.waf_bypass import (
        detect_waf_type,
        is_challenge_page,
        bypass_challenge,
        bypass_challenge_sync,
        validate_response,
        WAFType,
        WAFDetectionResult,
        BypassResult,
    )
    _WAF_BYPASS_AVAILABLE = True
except ImportError:
    pass


def is_smart_request_available() -> bool:
    """Check if the advanced smart request system is available."""
    return _ROUTER_AVAILABLE


def is_stealth_available() -> bool:
    """Check if TLS fingerprint impersonation is available."""
    return _STEALTH_CLIENT_AVAILABLE


def get_capabilities() -> dict:
    """Get available scraping capabilities."""
    curl_cffi = False
    if _STEALTH_CLIENT_AVAILABLE:
        try:
            curl_cffi = is_curl_cffi_available()
        except Exception:
            pass
    
    browser = False
    if _BROWSER_AVAILABLE:
        try:
            browser = is_browser_available()
        except Exception:
            pass
    
    proxies = False
    if _PROXY_MANAGER_AVAILABLE:
        try:
            proxies = has_proxies()
        except Exception:
            pass
    
    return {
        "stealth_client": _STEALTH_CLIENT_AVAILABLE,
        "curl_cffi_tls_impersonation": curl_cffi,
        "browser_automation": browser,
        "smart_router": _ROUTER_AVAILABLE,
        "proxy_manager": _PROXY_MANAGER_AVAILABLE,
        "proxies_configured": proxies,
        "waf_bypass": _WAF_BYPASS_AVAILABLE,
    }


def initialize():
    """Initialize the scraping infrastructure.
    
    This should be called at application startup to:
    - Connect the proxy manager to the router
    - Warm up browser pool if needed
    - Log available capabilities
    """
    from utils import logger
    
    capabilities = get_capabilities()
    
    logger.info("=== Scraping Infrastructure Status ===")
    logger.info(f"  TLS Fingerprint Impersonation: {'✓' if capabilities['curl_cffi_tls_impersonation'] else '✗'}")
    logger.info(f"  Browser Automation: {'✓' if capabilities['browser_automation'] else '✗'}")
    logger.info(f"  Smart Request Router: {'✓' if capabilities['smart_router'] else '✗'}")
    logger.info(f"  Proxy Manager: {'✓' if capabilities['proxy_manager'] else '✗'}")
    logger.info(f"  Proxies Configured: {'✓' if capabilities['proxies_configured'] else '✗'}")
    logger.info(f"  WAF Bypass: {'✓' if capabilities['waf_bypass'] else '✗'}")
    
    # Connect proxy manager to router
    if _ROUTER_AVAILABLE and _PROXY_MANAGER_AVAILABLE:
        try:
            proxy_manager = get_proxy_manager()
            set_proxy_manager(proxy_manager)
            logger.debug("Connected proxy manager to smart router")
        except Exception as e:
            logger.debug(f"Failed to connect proxy manager: {e}")
    
    return capabilities


# Auto-initialize on import (optional, can be called explicitly)
# initialize()

__all__ = [
    # Core anti-blocking
    "build_headers",
    "build_mobile_headers",
    "detect_soft_block",
    "pre_request_wait",
    "record_block",
    "record_failure",
    "record_request_start",
    "record_success",
    "suggest_retry_delay",
    "get_proxy",
    "rotate_proxy",
    "add_proxies",
    "get_proxy_stats",
    "get_site_stats",
    "get_all_site_stats",
    "randomize_params_order",
    "add_request_jitter",
    "simulate_reading_time",
    "get_progressive_delay",
    
    # Capability checks
    "is_smart_request_available",
    "is_stealth_available",
    "get_capabilities",
    "initialize",
    
    # Module availability flags
    "_STEALTH_CLIENT_AVAILABLE",
    "_BROWSER_AVAILABLE",
    "_ROUTER_AVAILABLE",
    "_PROXY_MANAGER_AVAILABLE",
    "_WAF_BYPASS_AVAILABLE",
]

