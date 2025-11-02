"""
Common utilities for all scrapers.
Consolidates duplicate code and provides shared functionality.
Optimized for performance without external dependencies.
"""
import random
import time
import json
import threading
import urllib.parse
from datetime import datetime
from pathlib import Path
import requests
from utils import logger
from functools import lru_cache

from scrapers import anti_blocking


# Thread locks for seen listings (one per scraper)
_seen_listings_locks = {}

# Recursion guards for scrapers
_recursion_guards = threading.local()

# Session cache for persistent connections
_session_cache = {}
_session_lock = threading.Lock()

# Compiled URL normalization patterns (cache for better performance)
_url_cache = {}
_url_cache_lock = threading.Lock()
_url_cache_max_size = 1000  # Limit cache size


# ======================
# USER AGENT MANAGEMENT
# ======================
# Legacy user agent list retained for reference (unused)

def get_random_user_agent(site_name=None):
    """Return a random realistic user agent.

    Wrapped around the anti-blocking header builder so callers benefit from the
    expanded fingerprint pool without code changes.
    """

    headers = anti_blocking.build_headers(site_name)
    return headers.get("User-Agent", "Mozilla/5.0")


def get_realistic_headers(referer=None, origin=None, site_name=None, extra_headers=None):
    """Generate realistic browser headers enriched with adaptive fingerprints."""

    base_headers = dict(extra_headers) if extra_headers else None
    return anti_blocking.build_headers(site_name, referer=referer, origin=origin, base_headers=base_headers)


# ======================
# SESSION MANAGEMENT
# ======================
def get_session(site_name, initialize_url=None):
    """
    Get or create a persistent session for a scraper site.
    
    Args:
        site_name: Name of the scraper site (e.g., 'craigslist', 'ebay')
        initialize_url: Optional URL to visit to initialize the session
        
    Returns:
        requests.Session object
    """
    with _session_lock:
        if site_name not in _session_cache:
            session = requests.Session()
            _session_cache[site_name] = session
            
            # Initialize session by visiting homepage if provided
            if initialize_url:
                try:
                    headers = get_realistic_headers(site_name=site_name)
                    logger.debug(f"Initializing {site_name} session by visiting homepage...")
                    response = session.get(initialize_url, headers=headers, timeout=15)
                    if response.status_code == 200:
                        logger.debug(f"{site_name} session initialized successfully")
                        # Small delay to mimic human behavior
                        time.sleep(random.uniform(0.5, 1.5))
                    else:
                        logger.warning(f"{site_name} session initialization returned status {response.status_code}")
                except Exception as e:
                    logger.warning(f"Failed to initialize {site_name} session: {e}")
        
        return _session_cache[site_name]


def clear_session(site_name):
    """Clear/reset the session for a scraper site."""
    with _session_lock:
        if site_name in _session_cache:
            try:
                _session_cache[site_name].close()
            except:
                pass
            del _session_cache[site_name]
            logger.debug(f"Cleared session for {site_name}")


def initialize_session(site_name, base_url):
    """
    Initialize a session by visiting the homepage to get cookies.
    
    Args:
        site_name: Name of the scraper site
        base_url: Base URL to visit for initialization
    """
    session = get_session(site_name)
    try:
        headers = get_realistic_headers(site_name=site_name)
        logger.debug(f"Initializing {site_name} session by visiting homepage...")
        response = session.get(base_url, headers=headers, timeout=15)
        if response.status_code == 200:
            logger.debug(f"{site_name} session initialized successfully")
            # Small delay to mimic human behavior
            time.sleep(random.uniform(0.5, 1.5))
        else:
            logger.warning(f"{site_name} session initialization returned status {response.status_code}")
    except Exception as e:
        logger.warning(f"Failed to initialize {site_name} session: {e}")


# ======================
# RATE LIMIT DETECTION
# ======================
def check_rate_limit(response, site_name):
    """
    Check if response indicates rate limiting and handle accordingly.
    
    Args:
        response: requests.Response object
        site_name: Name of the scraper site for logging
        
    Returns:
        tuple: (is_rate_limited: bool, retry_after: int)
    """
    if response.status_code == 429:
        # Check for Retry-After header
        retry_after = response.headers.get('Retry-After')
        
        if retry_after:
            try:
                # Retry-After can be seconds or HTTP date
                retry_seconds = int(retry_after)
            except ValueError:
                # If it's a date, default to 60 seconds
                retry_seconds = 60
        else:
            # Default to 60 seconds if no header
            retry_seconds = 60
        
        logger.warning(f"{site_name} rate limit detected (429). Waiting {retry_seconds}s before retry...")
        return True, retry_seconds
    
    # Check for 403 which might indicate bot detection
    if response.status_code == 403:
        logger.warning(f"{site_name} returned 403 (possible bot detection)")
        return True, 30  # Wait 30 seconds
    
    return False, 0


def make_request_with_retry(url, site_name, max_retries=3, session=None, **kwargs):
    """
    Make HTTP request with automatic retry, rate limit detection, and adaptive throttling.
    """

    requester = session if session else requests
    base_kwargs = dict(kwargs)

    if "timeout" not in base_kwargs:
        base_kwargs["timeout"] = 30

    for attempt in range(max_retries):
        pre_wait = anti_blocking.pre_request_wait(site_name)
        if pre_wait > 0:
            logger.debug(f"{site_name}: waiting {pre_wait:.2f}s before request to {url}")
            time.sleep(pre_wait)

        request_kwargs = dict(base_kwargs)
        incoming_headers = request_kwargs.get("headers")
        if incoming_headers:
            request_kwargs["headers"] = anti_blocking.enrich_headers(site_name, dict(incoming_headers))
        else:
            request_kwargs["headers"] = get_realistic_headers(site_name=site_name)

        try:
            anti_blocking.record_request_start(site_name)
            response = requester.get(url, **request_kwargs)

            # First handle explicit rate-limit responses
            is_rate_limited, retry_after = check_rate_limit(response, site_name)
            if is_rate_limited:
                anti_blocking.record_block(site_name, f"status:{response.status_code}", retry_after)
                if attempt < max_retries - 1:
                    if session:
                        session.cookies.clear()
                    delay = max(retry_after, anti_blocking.suggest_retry_delay(site_name, attempt + 1))
                    logger.info(f"{site_name}: rate limited ({response.status_code}). Retrying in {delay:.1f}s...")
                    time.sleep(delay)
                    continue
                logger.error(f"{site_name} rate limited after {max_retries} attempts")
                return None

            soft_block_signal = anti_blocking.detect_soft_block(site_name, response)
            if soft_block_signal:
                anti_blocking.record_block(site_name, soft_block_signal)
                logger.warning(f"{site_name}: potential block detected ({soft_block_signal}) on attempt {attempt + 1}/{max_retries}")
                if attempt < max_retries - 1:
                    if session:
                        session.cookies.clear()
                    delay = anti_blocking.suggest_retry_delay(site_name, attempt + 1)
                    time.sleep(delay)
                    continue
                logger.error(f"{site_name} blocked after {max_retries} attempts")
                return None

            response.raise_for_status()
            anti_blocking.record_success(site_name)
            return response

        except (requests.exceptions.RequestException, requests.exceptions.Timeout) as e:
            anti_blocking.record_failure(site_name)
            logger.warning(f"{site_name} request failed (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                if session:
                    session.cookies.clear()
                delay = anti_blocking.suggest_retry_delay(site_name, attempt + 1)
                logger.info(f"Retrying in {delay:.1f} seconds...")
                time.sleep(delay)
                continue
            logger.error(f"{site_name} request failed after {max_retries} attempts: {e}")
            return None
        except Exception as e:
            anti_blocking.record_failure(site_name)
            logger.error(f"Unexpected error in {site_name} request: {e}")
            return None

    return None


# ======================
# IMAGE URL VALIDATION
# ======================
# Pre-defined patterns for image validation (avoid recreating on every call)
_PLACEHOLDER_PATTERNS = frozenset([
    'placeholder', 'blank', 'default', 'no-image', 'noimage',
    'icon', 'logo', 'avatar', 'spinner', 'loading',
    '1x1', 'spacer', 'pixel.gif', 'transparent.gif'
])
_SMALL_IMAGE_PATTERNS = frozenset(['s-l50', 's-l64', 's-l32', 'thumb_50', 'size=50', '50x50'])
_VALID_EXTENSIONS = frozenset(['.jpg', '.jpeg', '.png', '.webp', '.gif'])
_KNOWN_CDNS = frozenset(['cloudfront', 'imgur', 'scontent', 'ebayimg', 'craigslist', 'ksl.com'])

def validate_image_url(image_url):
    """
    Validate that an image URL is likely a real product image.
    Optimized with pre-compiled patterns and fast path checks.
    
    Args:
        image_url: URL string to validate
        
    Returns:
        bool: True if URL appears valid, False otherwise
    """
    # Fast rejection checks
    if not image_url or not isinstance(image_url, str):
        return False
    
    # Must start with http:// or https://
    if not image_url.startswith('http'):
        return False
    
    # Filter out data URIs (fast check before lowercasing)
    if image_url.startswith('data:'):
        return False
    
    # Convert to lowercase once for all checks
    url_lower = image_url.lower()
    
    # Check placeholder patterns using any() with generator (stops at first match)
    if any(pattern in url_lower for pattern in _PLACEHOLDER_PATTERNS):
        return False
    
    # Check small image patterns
    if any(pattern in url_lower for pattern in _SMALL_IMAGE_PATTERNS):
        return False
    
    # Must have a valid extension OR be from known CDN (combined check)
    has_valid_extension = any(ext in url_lower for ext in _VALID_EXTENSIONS)
    is_cdn = any(cdn in url_lower for cdn in _KNOWN_CDNS)
    
    return has_valid_extension or is_cdn


# ======================
# DELAY & TIMING
# ======================
def human_delay(flag_dict, flag_name, min_sec=1.5, max_sec=4.5):
    """
    Pause between requests with human-like randomness, respecting stop flags.
    
    Args:
        flag_dict: Dictionary containing running flags
        flag_name: Name of the flag to check
        min_sec: Minimum delay in seconds
        max_sec: Maximum delay in seconds
    """
    total = random.uniform(min_sec, max_sec)
    step = 0.25  # smaller step for faster stop response
    while total > 0 and flag_dict.get(flag_name, True):
        sleep_time = min(step, total)
        time.sleep(sleep_time)
        total -= sleep_time


# ======================
# URL HANDLING
# ======================
def normalize_url(url):
    """
    Normalize URL by removing query parameters and fragments for comparison.
    Optimized with caching for frequently accessed URLs.
    
    Args:
        url: URL string to normalize
        
    Returns:
        Normalized URL string or None if invalid
    """
    if not url:
        return None
    
    # Check cache first (thread-safe)
    with _url_cache_lock:
        if url in _url_cache:
            return _url_cache[url]
        
        # Manage cache size
        if len(_url_cache) >= _url_cache_max_size:
            # Remove oldest 20% of entries
            items_to_remove = _url_cache_max_size // 5
            for _ in range(items_to_remove):
                _url_cache.popitem()
    
    try:
        # Fast path for already normalized URLs (no query string or fragment)
        if '?' not in url and '#' not in url:
            normalized = url.rstrip('/')
        else:
            # Remove query parameters and fragments
            parsed = urllib.parse.urlparse(url)
            normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip('/')
        
        # Cache the result
        with _url_cache_lock:
            _url_cache[url] = normalized
        
        return normalized
    except Exception as e:
        logger.debug(f"Error normalizing URL {url}: {e}")
        return url


# ======================
# SEEN LISTINGS MANAGEMENT
# ======================
def get_seen_listings_lock(site_name):
    """Get or create a lock for seen listings of a specific site."""
    if site_name not in _seen_listings_locks:
        _seen_listings_locks[site_name] = threading.Lock()
    return _seen_listings_locks[site_name]


def is_new_listing(link, seen_listings, site_name):
    """
    Check if a listing is new or was last seen more than 24 hours ago.
    Optimized with cached normalization and reduced lock duration.
    
    Args:
        link: URL of the listing
        seen_listings: Dictionary of seen listings
        site_name: Name of the scraper site
        
    Returns:
        bool: True if listing is new, False otherwise
    """
    normalized_link = normalize_url(link)
    if not normalized_link:
        # If URL normalization failed, treat as new to attempt processing
        logger.debug(f"URL normalization failed for {link}, treating as new")
        return True
    
    lock = get_seen_listings_lock(site_name)
    
    # Fast path: check if not in dict (common case for new listings)
    with lock:
        last_seen = seen_listings.get(normalized_link)
        if last_seen is None:
            return True
    
    # Only calculate time difference if listing exists
    # This avoids datetime operations in the critical path
    time_diff = (datetime.now() - last_seen).total_seconds()
    return time_diff > 86400  # 24 hours


def save_seen_listings(seen_listings, site_name, filename=None):
    """
    Save seen listings with timestamps to JSON.
    
    Args:
        seen_listings: Dictionary of seen listings
        site_name: Name of the scraper site
        filename: Optional custom filename (defaults to {site_name}_seen.json)
    """
    if filename is None:
        filename = f"{site_name}_seen.json"
    
    try:
        lock = get_seen_listings_lock(site_name)
        with lock:
            Path(filename).write_text(
                json.dumps({k: v.isoformat() for k, v in seen_listings.items()}, indent=2),
                encoding="utf-8"
            )
        logger.debug(f"Saved seen listings to {filename}")
    except (OSError, PermissionError) as e:
        logger.error(f"File system error saving seen listings for {site_name}: {e}")
    except Exception as e:
        logger.error(f"Error saving seen listings for {site_name}: {e}")


def load_seen_listings(site_name, filename=None):
    """
    Load seen listings from JSON file.
    
    Args:
        site_name: Name of the scraper site
        filename: Optional custom filename (defaults to {site_name}_seen.json)
        
    Returns:
        Dictionary of seen listings
    """
    if filename is None:
        filename = f"{site_name}_seen.json"
    
    try:
        text = Path(filename).read_text(encoding="utf-8")
        data = json.loads(text) if text else {}
        seen_listings = {k: datetime.fromisoformat(v) for k, v in data.items()}
        logger.debug(f"Loaded {len(seen_listings)} seen listings from {filename}")
        return seen_listings
    except FileNotFoundError:
        logger.info(f"Seen listings file not found: {filename}, starting fresh")
        return {}
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"Invalid JSON in seen listings file for {site_name}: {e}")
        return {}
    except Exception as e:
        logger.error(f"Error loading seen listings for {site_name}: {e}")
        return {}


# ======================
# LISTING VALIDATION
# ======================
def validate_listing(title, link, price=None):
    """
    Validate listing data before saving.
    
    Args:
        title: Listing title
        link: Listing URL
        price: Optional listing price
        
    Returns:
        tuple: (is_valid: bool, error_message: str or None)
    """
    if not title or not isinstance(title, str) or len(title.strip()) == 0:
        return False, "Invalid or empty title"
    
    if not link or not isinstance(link, str) or not link.startswith("http"):
        return False, "Invalid or missing link"
    
    if price is not None and (not isinstance(price, (int, float)) or price < 0):
        return False, "Invalid price"
    
    return True, None


# ======================
# SETTINGS MANAGEMENT
# ======================
def load_settings(username=None):
    """
    Load scraper settings from database for a specific user or global.
    
    Args:
        username: Username to load settings for. If None, loads global settings.
    
    Returns:
        Dictionary of settings with defaults
    """
    try:
        from db import get_settings
        settings = get_settings(username=username)  # Get user-specific or global settings
        return {
            "keywords": [k.strip() for k in settings.get("keywords", "Firebird,Camaro,Corvette").split(",") if k.strip()],
            "min_price": int(settings.get("min_price", 1000)),
            "max_price": int(settings.get("max_price", 30000)),
            "interval": int(settings.get("interval", 60)),
            "location": settings.get("location", "boise"),
            "radius": int(settings.get("radius", 50))
        }
    except Exception as e:
        logger.error(f"?? Failed to load settings for user {username}: {e}")
        return {
            "keywords": ["Firebird", "Camaro", "Corvette"],
            "min_price": 1000,
            "max_price": 30000,
            "interval": 60,
            "location": "boise",
            "radius": 50
        }


# ======================
# RECURSION GUARDS
# ======================
def check_recursion_guard(site_name):
    """
    Check if scraper is already running (recursion guard).
    
    Args:
        site_name: Name of the scraper site
        
    Returns:
        bool: True if recursion detected, False otherwise
    """
    guard_attr = f'in_{site_name}_scraper'
    if getattr(_recursion_guards, guard_attr, False):
        import sys
        print(f"ERROR: Recursion detected in {site_name} scraper", file=sys.stderr, flush=True)
        return True
    return False


def set_recursion_guard(site_name, value):
    """
    Set recursion guard for a scraper.
    
    Args:
        site_name: Name of the scraper site
        value: True to set guard, False to clear
    """
    guard_attr = f'in_{site_name}_scraper'
    setattr(_recursion_guards, guard_attr, value)


def clear_recursion_guard(site_name):
    """
    Clear recursion guard for a scraper.
    
    Args:
        site_name: Name of the scraper site
    """
    set_recursion_guard(site_name, False)


# ======================
# ERROR CONTEXT LOGGING
# ======================
def log_selector_failure(site_name, selector_type, selector, element_type="element"):
    """
    Log detailed information about selector failures.
    
    Args:
        site_name: Name of the scraper site
        selector_type: Type of selector (e.g., 'xpath', 'css', 'class')
        selector: The actual selector that failed
        element_type: What was being selected (e.g., 'title', 'price', 'link')
    """
    logger.debug(f"{site_name}: Failed to find {element_type} using {selector_type}: {selector}")


def log_parse_attempt(site_name, method_num, description):
    """
    Log parsing attempt for debugging website structure changes.
    
    Args:
        site_name: Name of the scraper site
        method_num: Method number (1, 2, 3, etc.)
        description: Description of what's being attempted
    """
    logger.debug(f"{site_name}: Trying method {method_num} - {description}")

