import sys
import threading
import socket
import time
from functools import lru_cache
from datetime import datetime
import urllib.parse
import json
import re
from lxml import html
from utils import debug_scraper_output, logger
from db import save_listing
from error_handling import ErrorHandler, log_errors, ScraperError, NetworkError
from location_utils import get_location_coords
from scrapers.common import (
    human_delay, normalize_url, is_new_listing, save_seen_listings,
    load_seen_listings, validate_listing, load_settings, get_session,
    make_request_with_retry, make_request_with_cascade, validate_image_url, 
    check_recursion_guard, set_recursion_guard, log_selector_failure, 
    log_parse_attempt, get_seen_listings_lock, extract_json_ld_items, 
    reset_session, validate_response_structure, detect_block_type,
    is_zero_results_page, RequestStrategy, smart_scrape_request,
    is_smart_request_available,
)
from scrapers.metrics import ScraperMetrics
from scrapers import anti_blocking
from scrapers import health_monitor

# Import new stealth infrastructure
try:
    from scrapers.stealth_client import stealth_get, is_curl_cffi_available
    _STEALTH_AVAILABLE = True
except ImportError:
    _STEALTH_AVAILABLE = False

# ======================
# CONFIGURATION
# ======================
SITE_NAME = "craigslist"
BASE_URL = "https://boise.craigslist.org"

CRAIGSLIST_DEFAULT_LOCATION = "boise"

# Known aliases and common city names that need to map to Craigslist subdomains.
# Keys are normalized (lowercase, alphanumeric only) for faster lookups.
CRAIGSLIST_LOCATION_ALIASES = {
    "blackfoot": "eastidaho",
    "idahofalls": "eastidaho",
    "rexburg": "eastidaho",
    "pocatello": "eastidaho",
}

_location_resolution_log = set()

_BLOCK_KEYWORDS = {
    "blocked | craigslist",
    "we have detected unusual activity",
    "please verify that you are a human",
    "security check required",
    "craigslist requires verification",
    "why did this happen",
    "unusual traffic from your computer",
    "access denied | craigslist",
    "are you a robot",
    "captcha",
}

# Craigslist-specific fallback chain with mobile site
def _transform_to_mobile(url: str) -> str:
    """Transform Craigslist URL to mobile version."""
    return url.replace("/search/", "/mob/")

def _transform_to_rss(url: str) -> str:
    """Transform Craigslist URL to RSS feed."""
    if "format=rss" in url:
        return url
    if "?" in url:
        return url + "&format=rss"
    return url + "?format=rss"

# RSS FIRST - Craigslist RSS is very reliable and less likely to be blocked
CRAIGSLIST_FALLBACK_CHAIN = [
    RequestStrategy("rss", url_transform=_transform_to_rss),  # RSS first - most reliable
    RequestStrategy("normal"),
    RequestStrategy("fresh_session", fresh_session=True),
    RequestStrategy("mobile", use_mobile=True, url_transform=_transform_to_mobile),
    RequestStrategy("proxy", use_proxy=True),
    RequestStrategy("mobile_proxy", use_mobile=True, use_proxy=True, url_transform=_transform_to_mobile),
]


def _fetch_rss_fallback(full_url: str, session, base_domain: str, username=None):
    """Fetch listings from RSS feed as fallback."""
    from xml.etree import ElementTree as ET
    
    rss_url = _transform_to_rss(full_url)
    logger.debug(f"Craigslist: Attempting RSS fallback from {rss_url}")
    
    response = make_request_with_retry(
        rss_url,
        SITE_NAME,
        session=session,
        referer=base_domain,
        origin=base_domain,
        session_initialize_url=base_domain,
        extra_headers={"Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8"},
        username=username,
    )
    
    if not response:
        return []
    
    try:
        root = ET.fromstring(response.text)
    except ET.ParseError as exc:
        logger.warning(f"Craigslist RSS parse error: {exc}")
        return []
    
    results = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        
        if not title or not link:
            continue
        
        # Extract price from title or description
        price_val = None
        description = item.findtext("description") or ""
        price_match = re.search(r"\$[\d,]+", title + " " + description)
        if price_match:
            price_val = _parse_price_text(price_match.group())
        
        results.append({
            "title": title,
            "link": link,
            "price": price_val,
            "image": None,
        })
    
    logger.debug(f"Craigslist RSS fallback recovered {len(results)} items")
    return results


def _normalize_location_key(location):
    """Normalize a location string for consistent craigslist subdomain lookups."""
    if not location:
        return CRAIGSLIST_DEFAULT_LOCATION
    return "".join(ch for ch in location.lower() if ch.isalnum()) or CRAIGSLIST_DEFAULT_LOCATION


@lru_cache(maxsize=128)
def _resolve_subdomain(normalized_key):
    """Resolve a normalized location key to a valid Craigslist subdomain."""
    candidates = []

    alias = CRAIGSLIST_LOCATION_ALIASES.get(normalized_key)
    if alias:
        candidates.append(alias)

    # Always try the normalized key itself last to preserve user intent if valid.
    candidates.append(normalized_key)

    for candidate in candidates:
        host = f"{candidate}.craigslist.org"
        try:
            socket.gethostbyname(host)
            return candidate
        except socket.gaierror:
            continue

    # Fallback to default if none resolve
    return CRAIGSLIST_DEFAULT_LOCATION


def resolve_craigslist_location(location):
    """
    Resolve the configured location to a valid Craigslist subdomain.
    Returns the resolved subdomain and a flag indicating whether a fallback occurred.
    """
    normalized_key = _normalize_location_key(location)
    resolved = _resolve_subdomain(normalized_key)

    fallback_used = resolved != normalized_key
    return resolved, fallback_used

def _user_key(user_id):
    """Generate a filesystem-safe key for tracking per-user state."""
    if not user_id:
        return "global"
    return re.sub(r'[^a-zA-Z0-9_-]', '_', str(user_id))


def _flag_key(flag_name, user_id):
    """Build a unique running flag key per user."""
    user_key = _user_key(user_id)
    if user_key == "global":
        return flag_name
    return f"{flag_name}:{user_key}"


def get_craigslist_flag_key(user_id=None, flag_name=SITE_NAME):
    """Public helper used by orchestrators to compute flag keys."""
    return _flag_key(flag_name, user_id)


seen_listings = {}

# ======================
# RUNNING FLAG
# ======================
running_flags = {SITE_NAME: True}

# ======================
# HELPER FUNCTIONS
# ======================
def _parse_price_text(price_text):
    if not price_text:
        return None
    try:
        cleaned = str(price_text).replace("$", "").replace(",", "").strip()
        if not cleaned:
            return None
        cleaned = cleaned.split()[0]
        if "-" in cleaned:
            cleaned = cleaned.split("-")[0]
        return int(float(cleaned))
    except (ValueError, TypeError):
        return None


def _parse_json_listings(tree):
    listings = []
    scripts = tree.xpath('//script[@type="application/ld+json"]/text()')
    for script in scripts:
        script = script.strip()
        if not script:
            continue
        try:
            data = json.loads(script)
        except json.JSONDecodeError:
            continue

        blocks = data if isinstance(data, list) else [data]
        for block in blocks:
            if not isinstance(block, dict):
                continue
            elements = block.get("itemListElement")
            if not isinstance(elements, list):
                continue
            for element in elements:
                entry = element.get("item") if isinstance(element, dict) else element
                if not isinstance(entry, dict):
                    continue
                title = entry.get("name") or entry.get("title")
                link = entry.get("url") or entry.get("@id")
                offers = entry.get("offers")
                price_val = None
                if isinstance(offers, dict):
                    price_val = _parse_price_text(offers.get("price"))
                elif isinstance(offers, list):
                    for offer in offers:
                        price_val = _parse_price_text(offer.get("price"))
                        if price_val is not None:
                            break

                image_url = entry.get("image")
                if isinstance(image_url, list):
                    image_url = image_url[0]

                listings.append({
                    "title": title,
                    "link": link,
                    "price": price_val,
                    "image": image_url,
                })

    return listings


def send_discord_message(title, link, price=None, image_url=None, user_id=None):
    """Save listing to database and send notification."""
    try:
        # Validate data before saving
        is_valid, error = validate_listing(title, link, price)
        if not is_valid:
            logger.warning(f"⚠️ Skipping invalid listing: {error}")
            return
        
        # Validate image URL if provided
        if image_url and not validate_image_url(image_url):
            logger.debug(f"Invalid/placeholder image URL, setting to None: {image_url}")
            image_url = None
        
        # Save to database with user_id
        save_listing(title, price, link, image_url, SITE_NAME, user_id=user_id)
        logger.info(f"📢 New Craigslist for {user_id}: {title} | ${price} | {link}")
    except Exception as e:
        logger.error(f"⚠️ Failed to save listing for {link}: {e}")

# ======================
# URL NORMALIZATION
# ======================
def resolve_listing_link(raw_link, base_domain):
    """Normalize Craigslist listing URLs and remove tracker parameters."""
    if not raw_link:
        return None

    href = str(raw_link).strip()
    if not href:
        return None

    absolute = urllib.parse.urljoin(base_domain, href)
    normalized = normalize_url(absolute)
    return normalized or absolute


# ======================
# MAIN SCRAPER FUNCTION
# ======================
def check_craigslist(flag_name=SITE_NAME, user_id=None, user_seen=None, flag_key=None):
    settings = load_settings(username=user_id)
    keywords = settings["keywords"]
    min_price = settings["min_price"]
    max_price = settings["max_price"]
    check_interval = settings["interval"]
    location = settings.get("location", CRAIGSLIST_DEFAULT_LOCATION)
    radius = settings.get("radius", 50)

    results = []
    flag_key = flag_key or _flag_key(flag_name, user_id)
    user_key = _user_key(user_id)
    if user_seen is None:
        user_seen = seen_listings.setdefault(user_key, {})
    
    # Use metrics tracking
    with ScraperMetrics(SITE_NAME) as metrics:
        try:
            if not running_flags.get(flag_key, True):
                metrics.error = "stopped"
                return []

            resolved_location, fallback_used = resolve_craigslist_location(location)
            log_key = (location.lower(), resolved_location)
            if fallback_used and log_key not in _location_resolution_log:
                _location_resolution_log.add(log_key)
                if resolved_location == CRAIGSLIST_DEFAULT_LOCATION:
                    logger.warning(
                        f"Craigslist: Location '{location}' is not a recognized Craigslist region; "
                        f"falling back to '{resolved_location}'."
                    )
                else:
                    logger.info(
                        f"Craigslist: Mapping location '{location}' to Craigslist region '{resolved_location}'."
                    )

            # Get location coordinates for distance filtering
            try:
                location_coords = get_location_coords(location)
                if location_coords:
                    logger.debug(
                        f"Craigslist: Searching {location} (subdomain '{resolved_location}') within {radius} miles"
                    )
                else:
                    logger.warning(f"Could not geocode location '{location}', using default coordinates")
                    # Use default coordinates for Boise, ID as fallback
                    location_coords = (43.6150, -116.2023)
            except Exception as e:
                logger.error(f"Error getting location coordinates for '{location}': {e}")
                # Use default coordinates for Boise, ID as fallback
                location_coords = (43.6150, -116.2023)
            
            # Build URL
            base_domain = f"https://{resolved_location}.craigslist.org"
            url = f"{base_domain}/search/sss"
            params = {"query": " ".join(keywords), "min_price": min_price, "max_price": max_price}
            # Use randomized param order to avoid fingerprinting
            full_url = url + "?" + anti_blocking.randomize_params_order(params)

            # Get persistent session
            session = get_session(SITE_NAME, base_domain, username=user_id)
            
            start_time = time.time()
            
            # Use cascade fallback system for maximum reliability
            response, strategy_used = make_request_with_cascade(
                full_url,
                SITE_NAME,
                session=session,
                referer=base_domain,
                origin=base_domain,
                session_initialize_url=base_domain,
                username=user_id,
                fallback_chain=CRAIGSLIST_FALLBACK_CHAIN,
            )
            
            response_time = time.time() - start_time
            
            if not response:
                metrics.error = "Failed to fetch page after all fallbacks"
                logger.warning("Craigslist request exhausted all fallback strategies")
                health_monitor.record_failure(SITE_NAME, "all_fallbacks_exhausted")
                
                # Try RSS as absolute last resort
                rss_results = _fetch_rss_fallback(full_url, session, base_domain, username=user_id)
                if rss_results:
                    logger.info(f"Craigslist: Final RSS fallback recovered {len(rss_results)} items")
                    # Process RSS results (simplified)
                    for entry in rss_results:
                        link = entry.get("link")
                        if link and not is_new_listing(link, user_seen, SITE_NAME):
                            continue
                        results.append(entry)
                    if results:
                        save_seen_listings(user_seen, SITE_NAME, username=user_id)
                        metrics.success = True
                        metrics.listings_found = len(results)
                        return results
                
                return []
            
            # Record successful request
            health_monitor.record_success(SITE_NAME, response_time, strategy_used)
            
            if strategy_used:
                logger.debug(f"Craigslist: Request succeeded using strategy '{strategy_used}'")
            
            # Check if response is RSS/XML (when RSS strategy succeeded)
            response_text = response.text if hasattr(response, 'text') else ""
            is_rss_response = response_text.strip().startswith('<?xml') or '<rss' in response_text[:500]
            
            if is_rss_response:
                logger.info("Craigslist: Detected RSS response, parsing as XML")
                from xml.etree import ElementTree as ET
                try:
                    root = ET.fromstring(response_text)
                    rss_items = []
                    for item in root.findall(".//item"):
                        title = (item.findtext("title") or "").strip()
                        link = (item.findtext("link") or "").strip()
                        description = item.findtext("description") or ""
                        
                        if not title or not link:
                            continue
                        
                        # Extract price from title or description
                        price_val = None
                        price_match = re.search(r"\$[\d,]+", title + " " + description)
                        if price_match:
                            price_val = _parse_price_text(price_match.group())
                        
                        rss_items.append({
                            "title": title,
                            "link": link,
                            "price": price_val,
                            "image": None,  # RSS doesn't typically include images
                        })
                    
                    logger.info(f"Craigslist: RSS parsing found {len(rss_items)} items")
                    
                    # Process RSS items with filtering
                    keywords_lower = [k.lower() for k in keywords]
                    seen_lock = get_seen_listings_lock(SITE_NAME)
                    
                    for entry in rss_items:
                        title = entry.get("title", "")
                        link = entry.get("link")
                        price_val = entry.get("price")
                        
                        if not link or not title:
                            continue
                        
                        # Apply filters
                        if price_val is not None:
                            if price_val < min_price or price_val > max_price:
                                continue
                        
                        if not any(k in title.lower() for k in keywords_lower):
                            continue
                        
                        if not is_new_listing(link, user_seen, SITE_NAME):
                            continue
                        
                        normalized_link = normalize_url(link) or link
                        with seen_lock:
                            user_seen[normalized_link] = datetime.now()
                        
                        send_discord_message(title, link, price_val, None, user_id=user_id)
                        results.append({
                            "title": title,
                            "link": link,
                            "price": price_val,
                            "image": None
                        })
                    
                    if results:
                        save_seen_listings(user_seen, SITE_NAME, username=user_id)
                        metrics.success = True
                        metrics.listings_found = len(results)
                    else:
                        logger.info(f"No new Craigslist listings from RSS. Next check in {check_interval}s...")
                        metrics.success = True
                        metrics.listings_found = 0
                    
                    debug_scraper_output("Craigslist", results)
                    return results
                except ET.ParseError as e:
                    logger.warning(f"Craigslist: RSS parse error, falling back to HTML: {e}")
            
            # Enhanced block detection using new system
            block_info = detect_block_type(response, SITE_NAME)
            if block_info:
                block_type = block_info.get("type", "unknown")
                cooldown_hint = block_info.get("cooldown_hint", 180)
                
                logger.warning(f"Craigslist: Block detected - type: {block_type}")
                anti_blocking.record_block(SITE_NAME, f"block:{block_type}", cooldown_hint=cooldown_hint)
                health_monitor.record_block(SITE_NAME, block_type)
                metrics.error = f"Block detected: {block_type}"
                reset_session(SITE_NAME, initialize_url=base_domain, username=user_id)
                
                # Try RSS fallback after block
                rss_results = _fetch_rss_fallback(full_url, session, base_domain, username=user_id)
                if rss_results:
                    logger.info(f"Craigslist: RSS fallback recovered {len(rss_results)} items after block")
                    return rss_results
                
                return []
            
            # Check if it's a valid zero-results page
            if is_zero_results_page(response, SITE_NAME):
                logger.info(f"Craigslist: No listings match criteria. Next check in {check_interval}s...")
                metrics.success = True
                metrics.listings_found = 0
                return []
            
            # Use robust HTML parsing - try lxml first, fallback to BeautifulSoup
            tree = None
            try:
                tree = html.fromstring(response.text)
            except Exception as parse_error:
                logger.warning(f"Craigslist: lxml parsing failed, trying BeautifulSoup: {parse_error}")
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(response.text, 'html.parser')
                # Convert BeautifulSoup to lxml tree for consistency
                try:
                    from lxml import html as lxml_html
                    tree = lxml_html.fromstring(str(soup))
                except Exception:
                    # Fallback: use soup directly for parsing
                    tree = soup
            
            # Try multiple XPath patterns for robustness - expanded with better fallbacks
            posts = []
            parse_strategies = [
                (1, "cl-static-search-result class", lambda: tree.xpath('//li[@class="cl-static-search-result"]') if hasattr(tree, 'xpath') else []),
                (2, "result-row class pattern", lambda: tree.xpath('//li[contains(@class, "result-row")]') if hasattr(tree, 'xpath') else []),
                (3, "generic search-result class", lambda: tree.xpath('//li[contains(@class, "search-result")]') if hasattr(tree, 'xpath') else []),
                (4, "ol.results li elements", lambda: tree.xpath('//ol[contains(@class, "results")]//li') if hasattr(tree, 'xpath') else []),
                (5, "div.cl-search-result", lambda: tree.xpath('//div[contains(@class, "cl-search-result")]') if hasattr(tree, 'xpath') else []),
                (6, "any li with data-pid", lambda: tree.xpath('//li[@data-pid]') if hasattr(tree, 'xpath') else []),
                (7, "article elements", lambda: tree.xpath('//article[contains(@class, "result")]') if hasattr(tree, 'xpath') else []),
                (8, "div.result-info containers", lambda: tree.xpath('//div[contains(@class, "result-info")]') if hasattr(tree, 'xpath') else []),
                (9, "links with href containing /post/", lambda: _extract_from_listing_links(tree)),
            ]
            
            for method_num, description, strategy in parse_strategies:
                log_parse_attempt(SITE_NAME, method_num, description)
                try:
                    posts = strategy()
                    if posts:
                        logger.debug(f"Craigslist: Found {len(posts)} posts using method {method_num} ({description})")
                        break
                except Exception as e:
                    logger.debug(f"Craigslist: Method {method_num} failed: {e}")
                    continue
            
            def _extract_from_listing_links(tree):
                """Extract posts from listing links as fallback."""
                if not hasattr(tree, 'xpath'):
                    return []
                link_elements = tree.xpath('//a[contains(@href, "/post/") or contains(@href, "/d/")]')
                if not link_elements:
                    return []
                posts_found = []
                seen_links = set()
                for link_elem in link_elements:
                    href = link_elem.get('href', '')
                    if href and href not in seen_links:
                        seen_links.add(href)
                        parent = link_elem.getparent()
                        if parent is not None and parent not in posts_found:
                            posts_found.append(parent)
                return posts_found

            json_ld_items = []
            if not posts:
                log_parse_attempt(SITE_NAME, 8, "JSON-LD itemListElement fallback")
                json_ld_items = extract_json_ld_items(response.text)
                if not json_ld_items:
                    # Log HTML snippet for debugging (first 2000 chars)
                    html_snippet = response.text[:2000].replace('\n', ' ').replace('\r', ' ')
                    logger.debug(f"Craigslist HTML snippet (first 2000 chars): {html_snippet}")
                    # Check for common class names in HTML
                    found_classes = set()
                    for match in re.findall(r'class=["\']([^"\']+)["\']', response.text[:5000]):
                        found_classes.update(match.split())
                    logger.debug(f"Craigslist found class names: {sorted(found_classes)[:20]}")
                    log_selector_failure(SITE_NAME, "json-ld", "itemListElement", "posts")
                    logger.warning("Craigslist: No posts found with HTML or JSON-LD selectors")
                    metrics.success = True
                    metrics.listings_found = 0
                    return []
                logger.debug(f"Craigslist JSON-LD fallback produced {len(json_ld_items)} entries")
            else:
                logger.debug(f"Craigslist HTML selectors returned {len(posts)} posts")

            keywords_lower = [k.lower() for k in keywords]
            seen_lock = get_seen_listings_lock(SITE_NAME)
            processed_links = set()

            def handle_candidate(title, raw_link, price_val, image_url=None, description=None):
                if not title or not raw_link:
                    return

                link = resolve_listing_link(raw_link, base_domain)
                if not link:
                    return

                normalized_price = None
                if price_val is not None:
                    try:
                        normalized_price = int(float(price_val))
                    except (TypeError, ValueError):
                        normalized_price = None

                if normalized_price is not None:
                    if normalized_price < min_price or normalized_price > max_price:
                        return

                text_blob = title.lower()
                if description:
                    text_blob = f"{text_blob} {description.lower()}"

                if not any(k in text_blob for k in keywords_lower):
                    return

                if not is_new_listing(link, user_seen, SITE_NAME):
                    return

                normalized_link = normalize_url(link) or link
                if normalized_link in processed_links:
                    return
                processed_links.add(normalized_link)

                with seen_lock:
                    user_seen[normalized_link] = datetime.now()

                send_discord_message(title, link, normalized_price, image_url, user_id=user_id)
                results.append({
                    "title": title,
                    "link": link,
                    "price": normalized_price,
                    "image": image_url
                })

            if posts:
                for post in posts:
                    try:
                        link = None
                        title = None

                        # Enhanced anchor and title extraction with multiple fallbacks
                        link = None
                        title = None
                        
                        # Try multiple anchor patterns
                        anchor_selectors = [
                            ".//a[@class='titlestring']",
                            ".//a[contains(@class, 'result-title')]",
                            ".//a[contains(@class, 'title')]",
                            ".//a[contains(@href, '/post/') or contains(@href, '/d/')]",
                            ".//a[@href]",
                            ".//h2/a | .//h3/a",
                            ".//a[contains(@href, 'craigslist.org')]",
                        ]
                        
                        anchor = None
                        for selector in anchor_selectors:
                            try:
                                anchor = post.xpath(selector) if hasattr(post, 'xpath') else []
                                if anchor:
                                    break
                            except Exception:
                                continue
                        
                        if anchor:
                            link = anchor[0].get('href')
                            # Try multiple title extraction methods
                            title_sources = [
                                anchor[0].get('title'),
                                anchor[0].get('aria-label'),
                                (anchor[0].text_content() or "").strip() if hasattr(anchor[0], 'text_content') else None,
                                post.get("title") if hasattr(post, 'get') else None,
                                post.get("aria-label") if hasattr(post, 'get') else None,
                            ]
                            for title_source in title_sources:
                                if title_source and isinstance(title_source, str) and title_source.strip():
                                    title = title_source.strip()
                                    break
                            
                            # Try finding title in nearby elements if still missing
                            if not title and hasattr(post, 'xpath'):
                                title_selectors = [
                                    ".//span[contains(@class, 'title')]",
                                    ".//h2",
                                    ".//h3",
                                    ".//div[contains(@class, 'title')]",
                                    ".//p[contains(@class, 'title')]",
                                ]
                                for selector in title_selectors:
                                    try:
                                        title_elem = post.xpath(selector)
                                        if title_elem and hasattr(title_elem[0], 'text_content'):
                                            title_candidate = title_elem[0].text_content().strip()
                                            if title_candidate:
                                                title = title_candidate
                                                break
                                    except Exception:
                                        continue

                        if not link or not title:
                            continue

                        # Enhanced price extraction with multiple fallbacks
                        price_val = None
                        if hasattr(post, 'xpath'):
                            price_selectors = [
                                ".//span[contains(@class, 'price')]/text()",
                                ".//div[contains(@class, 'price')]/text()",
                                ".//span[contains(text(), '$')]",
                                ".//div[contains(text(), '$')]",
                                ".//*[contains(@class, 'price')]//text()",
                            ]
                            for selector in price_selectors:
                                try:
                                    price_elem = post.xpath(selector)
                                    if price_elem:
                                        price_val = _parse_price_text(price_elem[0])
                                        if price_val is not None:
                                            break
                                except Exception:
                                    continue

                        # Enhanced image extraction with multiple fallbacks
                        image_url = None
                        if hasattr(post, 'xpath'):
                            img_selectors = [
                                ".//img[@src]/@src",
                                ".//img[@data-src]/@data-src",
                                ".//img[@data-lazy]/@data-lazy",
                                ".//img/@src",
                            ]
                            for selector in img_selectors:
                                try:
                                    img_elem = post.xpath(selector)
                                    if img_elem:
                                        image_url = img_elem[0]
                                        if image_url.startswith('//'):
                                            image_url = f"https:{image_url}"
                                        elif image_url and not image_url.startswith('http'):
                                            image_url = "https://images.craigslist.org" + image_url
                                        # Validate image URL
                                        if image_url and validate_image_url(image_url):
                                            break
                                        else:
                                            image_url = None
                                except Exception:
                                    continue

                        handle_candidate(title, link, price_val, image_url)
                    except Exception as e:
                        logger.warning(f"Error parsing a Craigslist post: {e}")
            else:
                for entry in json_ld_items:
                    try:
                        title = entry.get("title")
                        link = entry.get("url")
                        image_url = entry.get("image")
                        if isinstance(image_url, str):
                            if image_url.startswith('//'):
                                image_url = f"https:{image_url}"
                            elif image_url.startswith('/'):
                                image_url = "https://images.craigslist.org" + image_url

                        description = entry.get("description")
                        price_val = _parse_price_text(entry.get("price"))

                        handle_candidate(title, link, price_val, image_url, description)
                    except Exception as e:
                        logger.warning(f"Error parsing Craigslist JSON-LD listing: {e}")

            if results:
                save_seen_listings(user_seen, SITE_NAME, username=user_id)
                metrics.success = True
                metrics.listings_found = len(results)
            else:
                logger.info(f"No new Craigslist listings. Next check in {check_interval}s...")
                metrics.success = True
                metrics.listings_found = 0

            debug_scraper_output("Craigslist", results)
            return results

        except Exception as e:
            logger.error(f"Error processing Craigslist results: {e}")
            metrics.error = str(e)
            return []

# ======================
# CONTINUOUS RUNNER
# ======================
def run_craigslist_scraper(flag_name=SITE_NAME, user_id=None):
    """Run scraper continuously until stopped via running_flags."""
    # Check for recursion
    if check_recursion_guard(SITE_NAME):
        return
    
    set_recursion_guard(SITE_NAME, True)
    flag_key = _flag_key(flag_name, user_id)
    running_flags.setdefault(flag_key, True)
    
    try:
        logger.info(f"Starting Craigslist scraper for user {user_id}")
        user_key = _user_key(user_id)
        user_seen = load_seen_listings(SITE_NAME, username=user_id)
        seen_listings[user_key] = user_seen
        
        try:
            while running_flags.get(flag_key, True):
                try:
                    logger.debug(f"Running Craigslist scraper check for user {user_id}")
                    results = check_craigslist(flag_name, user_id=user_id, user_seen=user_seen, flag_key=flag_key)
                    if results:
                        logger.info(f"Craigslist scraper found {len(results)} new listings for user {user_id}")
                    else:
                        logger.debug(f"Craigslist scraper found no new listings for user {user_id}")
                except RecursionError as e:
                    print(f"ERROR: RecursionError in Craigslist scraper: {e}", file=sys.stderr)
                    # Wait before retrying to avoid tight loop
                    time.sleep(10)
                    continue
                except Exception as e:
                    # Use fallback logging to avoid recursion in error handling
                    try:
                        logger.error(f"Error in Craigslist scraper iteration: {e}")
                    except:
                        print(f"ERROR: Error in Craigslist scraper iteration: {e}", file=sys.stderr)
                    # Continue running but log the error
                    continue
                
                settings = load_settings(username=user_id)
                # Delay dynamically based on interval
                human_delay(running_flags, flag_key, settings["interval"]*0.9, settings["interval"]*1.1)
                
        except KeyboardInterrupt:
            logger.info("Craigslist scraper interrupted by user")
        except RecursionError as e:
            print(f"FATAL: RecursionError in Craigslist scraper main loop: {e}", file=sys.stderr)
        except Exception as e:
            try:
                logger.error(f"Fatal error in Craigslist scraper: {e}")
            except:
                print(f"ERROR: Fatal error in Craigslist scraper: {e}", file=sys.stderr)
        finally:
            logger.info("Craigslist scraper stopped")
    finally:
        set_recursion_guard(SITE_NAME, False)
