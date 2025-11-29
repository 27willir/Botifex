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
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union
from http.cookiejar import LWPCookieJar
import requests
from bs4 import BeautifulSoup, FeatureNotFound
from error_handling import ScraperError
from utils import logger
from functools import lru_cache

try:
    from bs4.builder import ParserRejectedMarkup
except ImportError:  # pragma: no cover - fallback for older BeautifulSoup versions
    class ParserRejectedMarkup(Exception):
        """Fallback ParserRejectedMarkup when BeautifulSoup doesn't expose it."""
        pass

from scrapers import anti_blocking


def _sanitize_username(username: Optional[str]) -> str:
    """
    Convert a username into a filesystem and cache safe token.

    Args:
        username: Raw username or None

    Returns:
        Sanitized string suitable for filenames and cache keys
    """
    if not username:
        return "global"
    return re.sub(r"[^a-zA-Z0-9_-]", "_", str(username))


def _session_cache_key(site_name: str, username: Optional[str]) -> str:
    """Build a stable session cache key scoped by site and user."""
    return f"{site_name}:{_sanitize_username(username)}"


def _build_seen_filename(
    site_name: str, username: Optional[str] = None, filename: Optional[str] = None
) -> str:
    """
    Construct a per-user seen listings filename.

    Args:
        site_name: Scraper site identifier
        username: Optional username for multi-tenant separation
        filename: Optional explicit filename override
    """
    if filename:
        return filename

    user_token = _sanitize_username(username)
    if user_token == "global":
        return f"{site_name}_seen.json"
    return f"{site_name}_{user_token}_seen.json"


# Thread locks for seen listings (one per scraper)
_seen_listings_locks = {}

# Recursion guards for scrapers
_recursion_guards = threading.local()

# Session cache for persistent connections
_session_cache = {}
_session_lock = threading.Lock()
_SESSION_COOKIE_DIR = Path(".session_cookies")

# Compiled URL normalization patterns (cache for better performance)
_url_cache = {}
_url_cache_lock = threading.Lock()
_url_cache_max_size = 1000  # Limit cache size

# Pre-compiled pattern for extracting JSON-LD scripts
_JSON_LD_SCRIPT_RE = re.compile(
    r"<script[^>]+type=[\"']application/(?:ld\+json|json)[\"'][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)

# Price cleanup regex
_PRICE_CLEAN_RE = re.compile(r"[^0-9.]")


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
# HTML PARSING
# ======================
def parse_html_with_fallback(
    markup: Union[str, bytes, bytearray],
    *,
    parser_order: Optional[Sequence[str]] = None,
    encodings: Optional[Sequence[Optional[str]]] = None,
    raw_bytes: Optional[bytes] = None,
    soup_builder: Callable[[str, str], Any] = BeautifulSoup,
    site_name: Optional[str] = None,
) -> Any:
    """
    Parse HTML content with graceful fallbacks for parser and encoding errors.

    Args:
        markup: The HTML markup to parse, as str or bytes.
        parser_order: Parsers to try in order. Defaults to ('html.parser', 'lxml').
        encodings: Optional list of encodings to try when decoding bytes.
        raw_bytes: Optional raw bytes for re-decoding attempts.
        soup_builder: Callable used to create the soup object (defaults to BeautifulSoup).
        site_name: Optional site name for logging context.

    Returns:
        Parsed soup-like object returned by soup_builder.

    Raises:
        ScraperError: If all parsing attempts fail.
    """
    if markup is None:
        raise ScraperError("No markup supplied for parsing")

    parser_sequence: Tuple[str, ...] = tuple(parser_order or ("html.parser", "lxml"))
    if not parser_sequence:
        raise ScraperError("No HTML parsers configured for fallback parsing")

    attempts: List[str] = []

    def _try_parse(text: str, parser_name: str, source: str):
        try:
            return soup_builder(text, parser_name)
        except (ParserRejectedMarkup, FeatureNotFound, ValueError) as exc:
            attempts.append(f"{parser_name} [{source}]: {exc}")
        except Exception as exc:  # pragma: no cover - unexpected parser errors
            attempts.append(f"{parser_name} [{source}]: {exc}")
        return None

    text_variants: List[Tuple[str, str]] = []

    if isinstance(markup, (bytes, bytearray)):
        markup_bytes = bytes(markup)
        if raw_bytes is None:
            raw_bytes = markup_bytes
        try:
            decoded_text = markup_bytes.decode("utf-8")
            text_variants.append((decoded_text, "bytes:utf-8"))
        except UnicodeDecodeError:
            text_variants.append((markup_bytes.decode("utf-8", errors="replace"), "bytes:utf-8-replace"))
    else:
        text_variants.append((str(markup), "initial"))
        if raw_bytes is None:
            try:
                raw_bytes = str(markup).encode("utf-8")
            except Exception:
                raw_bytes = None

    for text, source in text_variants:
        for parser_name in parser_sequence:
            soup = _try_parse(text, parser_name, source)
            if soup is not None:
                if attempts:
                    preview = ", ".join(attempts[:3])
                    context = site_name or "scraper"
                    logger.debug(f"{context}: HTML parsed using {parser_name} ({source}) after fallbacks: {preview}")
                return soup

    if raw_bytes:
        encoding_candidates: List[str] = []
        if encodings:
            encoding_candidates.extend(encodings)
        # Default encodings to try as fallbacks
        encoding_candidates.extend(["utf-8", "latin-1"])

        seen_encodings = set()
        for encoding in encoding_candidates:
            if not encoding:
                continue
            normalized = encoding.lower()
            if normalized in seen_encodings:
                continue
            seen_encodings.add(normalized)

            try:
                decoded_text = raw_bytes.decode(encoding, errors="replace")
            except Exception as exc:
                attempts.append(f"decode[{encoding}]: {exc}")
                continue

            source = f"decoded:{encoding}"
            for parser_name in parser_sequence:
                soup = _try_parse(decoded_text, parser_name, source)
                if soup is not None:
                    if attempts:
                        preview = ", ".join(attempts[:3])
                        context = site_name or "scraper"
                        logger.debug(f"{context}: HTML parsed using {parser_name} ({source}) after fallbacks: {preview}")
                    return soup

    error_detail = "; ".join(attempts) if attempts else "no parser attempts recorded"
    context = site_name or "scraper"
    logger.debug(f"{context}: HTML parsing failed after fallbacks: {error_detail}")
    raise ScraperError(f"Failed to parse HTML with available parsers: {error_detail}")


# ======================
# SESSION MANAGEMENT
# ======================
def _sanitize_site_name(site_name: str) -> str:
    if not site_name:
        return "site"
    return re.sub(r"[^a-zA-Z0-9_-]", "_", site_name)


def _session_cookie_path(site_name: str, username: Optional[str]) -> Path:
    user_token = _sanitize_username(username)
    site_token = _sanitize_site_name(site_name)
    filename = f"{site_token}_{user_token}.lwp" if user_token != "global" else f"{site_token}.lwp"
    return _SESSION_COOKIE_DIR / filename


def _load_session_cookies(session: requests.Session, site_name: str, username: Optional[str]) -> int:
    """Restore cookies from disk into the provided session."""
    try:
        cookie_path = _session_cookie_path(site_name, username)
        if not cookie_path.exists():
            return 0
        jar = LWPCookieJar(str(cookie_path))
        jar.load(ignore_discard=True, ignore_expires=False)
        restored = 0
        for cookie in jar:
            session.cookies.set_cookie(cookie)
            restored += 1
        if restored:
            logger.debug(f"{site_name}: restored {restored} cookies (user={username})")
        return restored
    except Exception as exc:
        logger.debug(f"{site_name}: failed to restore cookies for user {username}: {exc}")
        return 0


def _save_session_cookies(session: Optional[requests.Session], site_name: str, username: Optional[str]) -> None:
    """Persist session cookies to disk for reuse across runs."""
    if session is None:
        return
    try:
        cookies = list(session.cookies)
        cookie_path = _session_cookie_path(site_name, username)
        if not cookies:
            if cookie_path.exists():
                cookie_path.unlink(missing_ok=True)
                logger.debug(f"{site_name}: cleared persisted cookies (user={username})")
            return
        _SESSION_COOKIE_DIR.mkdir(parents=True, exist_ok=True)
        jar = LWPCookieJar(str(cookie_path))
        for cookie in cookies:
            jar.set_cookie(cookie)
        jar.save(ignore_discard=True, ignore_expires=True)
        logger.debug(f"{site_name}: persisted {len(cookies)} cookies (user={username})")
    except Exception as exc:
        logger.debug(f"{site_name}: failed to persist cookies for user {username}: {exc}")


def _delete_session_cookies(site_name: str, username: Optional[str]) -> None:
    """Remove any persisted cookies for the given site/user combination."""
    try:
        cookie_path = _session_cookie_path(site_name, username)
        if cookie_path.exists():
            cookie_path.unlink(missing_ok=True)
            logger.debug(f"{site_name}: deleted cookie cache (user={username})")
    except Exception as exc:
        logger.debug(f"{site_name}: failed to delete cookie cache for user {username}: {exc}")


def get_session(site_name, initialize_url=None, force_new=False, username=None):
    """
    Get or create a persistent session for a scraper site.
    
    Args:
        site_name: Name of the scraper site (e.g., 'craigslist', 'ebay')
        initialize_url: Optional URL to visit to initialize the session
        force_new: Force creation of a fresh session even if one is cached
        username: Optional username for per-user session separation
        
    Returns:
        requests.Session object
    """
    cache_key = _session_cache_key(site_name, username)
    with _session_lock:
        if force_new and cache_key in _session_cache:
            try:
                _session_cache[cache_key].close()
            except Exception:
                pass
            _session_cache.pop(cache_key, None)

        if cache_key not in _session_cache:
            session = requests.Session()
            session.headers.update({
                "Connection": "keep-alive",
                "Pragma": "no-cache",
                "Cache-Control": "no-cache"
            })
            _load_session_cookies(session, site_name, username)
            _session_cache[cache_key] = session
            
            # Initialize session by visiting homepage if provided
            if initialize_url:
                try:
                    headers = get_realistic_headers(site_name=site_name)
                    logger.debug(f"Initializing {site_name} session by visiting homepage ({initialize_url})...")
                    response = session.get(initialize_url, headers=headers, timeout=15)
                    if response.status_code == 200:
                        logger.debug(f"{site_name} session initialized successfully")
                        # Small delay to mimic human behavior
                        time.sleep(random.uniform(0.5, 1.5))
                    else:
                        logger.warning(f"{site_name} session initialization returned status {response.status_code}")
                except Exception as e:
                    logger.warning(f"Failed to initialize {site_name} session: {e}")
                finally:
                    _save_session_cookies(session, site_name, username)
        
        return _session_cache[cache_key]


def clear_session(site_name, username=None):
    """Clear/reset the session for a scraper site."""
    with _session_lock:
        cache_key = _session_cache_key(site_name, username)
        if cache_key in _session_cache:
            try:
                _session_cache[cache_key].close()
            except:
                pass
            del _session_cache[cache_key]
            if username:
                logger.debug(f"Cleared session for {site_name} (user={username})")
            else:
                logger.debug(f"Cleared session for {site_name}")
        _delete_session_cookies(site_name, username)


def reset_session(site_name, initialize_url=None, username=None):
    """Force creation of a new session and return it."""
    clear_session(site_name, username=username)
    return get_session(
        site_name,
        initialize_url=initialize_url,
        force_new=True,
        username=username,
    )


def initialize_session(site_name, base_url, username=None):
    """
    Initialize a session by visiting the homepage to get cookies.
    
    Args:
        site_name: Name of the scraper site
        base_url: Base URL to visit for initialization
        username: Optional username for per-user session separation
    """
    session = get_session(site_name, username=username)
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


def make_request_with_retry(
    url,
    site_name,
    max_retries=3,
    session=None,
    referer=None,
    origin=None,
    session_initialize_url=None,
    rotate_headers=True,
    extra_headers=None,
    username=None,
    **kwargs,
):
    """
    Make HTTP request with automatic retry, rate limit detection, and adaptive throttling.
    
    Args:
        url: URL to request
        site_name: Name of scraper site for logging
        max_retries: Maximum number of retry attempts
        session: Optional requests.Session object
        referer: Optional Referer header value
        origin: Optional Origin header value
        session_initialize_url: URL to use when recreating sessions after a block
        rotate_headers: Whether to regenerate browser headers on each attempt
        extra_headers: Additional headers to merge into the generated set
        username: Optional username for per-user session isolation
        **kwargs: Additional arguments to pass to requests.get()
        
    Returns:
        requests.Response object or None if all retries failed
    """
    requester = session if session else requests
    base_kwargs = dict(kwargs)
    session_to_use = session

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
            # Merge extra_headers if provided
            base_headers = dict(extra_headers) if extra_headers else {}
            if referer:
                base_headers["Referer"] = referer
            if origin:
                base_headers["Origin"] = origin
            request_kwargs["headers"] = get_realistic_headers(site_name=site_name, referer=referer, origin=origin, extra_headers=extra_headers)

        try:
            anti_blocking.record_request_start(site_name)
            response = requester.get(url, **request_kwargs)

            # First handle explicit rate-limit responses
            is_rate_limited, retry_after = check_rate_limit(response, site_name)
            if is_rate_limited:
                anti_blocking.record_block(site_name, f"status:{response.status_code}", retry_after)
                if attempt < max_retries - 1:
                    if session_to_use:
                        try:
                            session_to_use.cookies.clear()
                        except Exception:
                            pass
                    
                    status_code = getattr(response, "status_code", None)
                    if status_code == 403:
                        logger.info(f"{site_name}: refreshing session after 403 response")
                        session_to_use = reset_session(
                            site_name,
                            initialize_url=session_initialize_url,
                            username=username,
                        )
                        requester = session_to_use if session_to_use else requests
                    elif session_to_use is None and session is not None:
                        session_to_use = get_session(
                            site_name,
                            initialize_url=session_initialize_url,
                            username=username,
                        )
                        requester = session_to_use
                    
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
                    if session_to_use:
                        try:
                            session_to_use.cookies.clear()
                        except Exception:
                            pass
                    delay = anti_blocking.suggest_retry_delay(site_name, attempt + 1)
                    time.sleep(delay)
                    continue
                logger.error(f"{site_name} blocked after {max_retries} attempts")
                return None

            response.raise_for_status()
            anti_blocking.record_success(site_name)
            if session_to_use:
                _save_session_cookies(session_to_use, site_name, username)
            return response

        except (requests.exceptions.RequestException, requests.exceptions.Timeout) as e:
            anti_blocking.record_failure(site_name)
            logger.warning(f"{site_name} request failed (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                if session_to_use:
                    try:
                        session_to_use.cookies.clear()
                    except Exception:
                        pass
                    # Optionally rotate the session after repeated failures
                    if attempt >= 1:
                        try:
                            session_to_use = reset_session(
                                site_name,
                                initialize_url=session_initialize_url,
                                username=username,
                            )
                            requester = session_to_use if session_to_use else requests
                        except Exception as reset_error:
                            logger.debug(f"{site_name}: session reset failed during retry: {reset_error}")
                elif session is not None:
                    session_to_use = get_session(
                        site_name,
                        initialize_url=session_initialize_url,
                        username=username,
                    )
                    requester = session_to_use
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


def save_seen_listings(seen_listings, site_name, filename=None, username=None):
    """
    Save seen listings with timestamps to JSON.
    
    Args:
        seen_listings: Dictionary of seen listings
        site_name: Name of the scraper site
        filename: Optional explicit filename override
        username: Optional username for per-user isolation
    """
    filename = _build_seen_filename(site_name, username=username, filename=filename)
    
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


def load_seen_listings(site_name, filename=None, username=None):
    """
    Load seen listings from JSON file.
    
    Args:
        site_name: Name of the scraper site
        filename: Optional custom filename (defaults to {site_name}_seen.json)
        username: Optional username for per-user isolation
        
    Returns:
        Dictionary of seen listings
    """
    filename = _build_seen_filename(site_name, username=username, filename=filename)
    
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
# JSON-LD EXTRACTION
# ======================
def _coerce_price_value(value: Any) -> Optional[int]:
    """Convert a JSON-LD price value into an integer number of currency units."""

    if value is None:
        return None

    if isinstance(value, (int, float)):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    if isinstance(value, str):
        cleaned = _PRICE_CLEAN_RE.sub("", value)
        if not cleaned:
            return None
        try:
            return int(float(cleaned))
        except ValueError:
            return None

    return None


def _extract_offer_metadata(offers: Any) -> Dict[str, Any]:
    """Extract price information from a JSON-LD offers structure."""

    if not offers:
        return {"price": None, "currency": None, "raw": None}

    offer_candidates: List[Dict[str, Any]] = []

    if isinstance(offers, dict):
        offer_candidates.append(offers)
    elif isinstance(offers, list):
        offer_candidates.extend([o for o in offers if isinstance(o, dict)])

    for offer in offer_candidates:
        price_value = (
            offer.get("price")
            or offer.get("lowPrice")
            or offer.get("highPrice")
        )
        price = _coerce_price_value(price_value)
        if price is not None:
            return {
                "price": price,
                "currency": offer.get("priceCurrency"),
                "raw": price_value,
            }

    # If none of the offers had a parseable price, fall back to the first raw value
    if offer_candidates:
        raw_value = (
            offer_candidates[0].get("price")
            or offer_candidates[0].get("lowPrice")
            or offer_candidates[0].get("highPrice")
        )
        return {
            "price": _coerce_price_value(raw_value),
            "currency": offer_candidates[0].get("priceCurrency"),
            "raw": raw_value,
        }

    return {"price": None, "currency": None, "raw": None}


def _normalize_json_ld_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a JSON-LD item into a standard listing dict."""

    title = (
        item.get("name")
        or item.get("title")
        or item.get("headline")
        or item.get("alternateName")
    )

    url = item.get("url") or item.get("@id") or item.get("id")

    image_field = item.get("image")
    image_url: Optional[str] = None
    if isinstance(image_field, str):
        image_url = image_field.strip()
    elif isinstance(image_field, list):
        for element in image_field:
            if isinstance(element, str) and element.strip():
                image_url = element.strip()
                if image_url.startswith("http"):
                    break

    description = item.get("description") or item.get("abstract")

    offer_meta = _extract_offer_metadata(item.get("offers"))
    price = offer_meta["price"]
    currency = offer_meta["currency"]
    raw_price = offer_meta["raw"]

    # Some schemas put price directly on the item
    if price is None:
        price = _coerce_price_value(item.get("price"))
        if price is None:
            price = _coerce_price_value(item.get("priceSpecification"))

    return {
        "title": title.strip() if isinstance(title, str) else None,
        "url": url.strip() if isinstance(url, str) else None,
        "price": price,
        "price_raw": raw_price or item.get("price"),
        "currency": currency,
        "image": image_url,
        "description": description.strip() if isinstance(description, str) else None,
        "raw": item,
    }


def _collect_json_ld_items(payload: Any, results: List[Dict[str, Any]], seen_urls: set):
    """Recursively collect JSON-LD listings from arbitrary payloads."""

    if payload is None:
        return

    if isinstance(payload, list):
        for element in payload:
            _collect_json_ld_items(element, results, seen_urls)
        return

    if not isinstance(payload, dict):
        return

    if "@graph" in payload and isinstance(payload["@graph"], list):
        _collect_json_ld_items(payload["@graph"], results, seen_urls)

    if "itemListElement" in payload and isinstance(payload["itemListElement"], list):
        for element in payload["itemListElement"]:
            item = element.get("item") if isinstance(element, dict) else element
            if isinstance(item, dict):
                normalized = _normalize_json_ld_item(item)
                url = normalized.get("url")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    results.append(normalized)

    # Some schemas use "item" directly without itemListElement
    if payload.get("@type") in {"Product", "Offer", "ListItem", "Article"} and (
        payload.get("url") or payload.get("@id")
    ):
        normalized = _normalize_json_ld_item(payload)
        url = normalized.get("url")
        if url and url not in seen_urls:
            seen_urls.add(url)
            results.append(normalized)

    # Recurse into values to catch nested declarations
    for value in payload.values():
        if isinstance(value, (dict, list)):
            _collect_json_ld_items(value, results, seen_urls)


def extract_json_ld_items(html_text: str) -> List[Dict[str, Any]]:
    """Extract listing-like items from any JSON-LD scripts embedded in HTML."""

    if not html_text:
        return []

    results: List[Dict[str, Any]] = []
    seen_urls: set = set()

    for match in _JSON_LD_SCRIPT_RE.finditer(html_text):
        script_content = match.group(1).strip()
        if not script_content:
            continue

        # Remove HTML comment wrappers if present
        if script_content.startswith("<!--"):
            script_content = script_content[4:]
        if script_content.endswith("-->"):
            script_content = script_content[:-3]

        try:
            data = json.loads(script_content)
        except json.JSONDecodeError:
            # Some scripts may contain multiple JSON objects separated by newlines
            # Attempt to load line-by-line as a fallback
            fragments = []
            for line in script_content.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    fragments.append(json.loads(line))
                except json.JSONDecodeError:
                    fragments = []
                    break
            if not fragments:
                logger.debug("Failed to decode JSON-LD fragment")
                continue
            data = fragments

        _collect_json_ld_items(data, results, seen_urls)

    return results


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

