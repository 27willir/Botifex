"""Mercari scraper with shared anti-blocking defenses."""

import sys
import threading
import random
import json
import time
from datetime import datetime
import urllib.parse
import re
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from utils import debug_scraper_output, logger
from db import save_listing
from location_utils import get_location_coords, miles_to_km
from scrapers.common import (
    human_delay,
    normalize_url,
    is_new_listing,
    save_seen_listings,
    load_seen_listings,
    validate_listing,
    load_settings,
    get_session,
    make_request_with_retry,
    make_request_with_cascade,
    validate_image_url,
    check_recursion_guard,
    set_recursion_guard,
    log_selector_failure,
    log_parse_attempt,
    get_seen_listings_lock,
    validate_response_structure,
    detect_block_type,
    is_zero_results_page,
    RequestStrategy,
    reset_session,
)
from scrapers.metrics import ScraperMetrics
from scrapers import anti_blocking
from scrapers import health_monitor


SITE_NAME = "mercari"
BASE_URL = "https://www.mercari.com"
SEARCH_PATH = "/search"

# Mercari-specific fallback chain with mobile and proxy rotation
MERCARI_FALLBACK_CHAIN = [
    RequestStrategy("normal"),
    RequestStrategy("fresh_session", fresh_session=True),
    RequestStrategy("mobile", use_mobile=True),
    RequestStrategy("proxy", use_proxy=True),
    RequestStrategy("mobile_proxy", use_mobile=True, use_proxy=True),
    RequestStrategy("fresh_mobile", use_mobile=True, fresh_session=True),
]

# Cookie warmup endpoints - visit these to establish valid session
WARMUP_URLS = [
    "https://www.mercari.com/",
    "https://www.mercari.com/sell/",
]


def _warmup_session(session, username=None) -> bool:
    """
    Warm up Mercari session by visiting homepage to establish cookies.
    This helps avoid bot detection on first search request.
    """
    try:
        for url in WARMUP_URLS[:1]:  # Just visit homepage
            headers = anti_blocking.build_headers(SITE_NAME, referer=None)
            response = session.get(url, headers=headers, timeout=15)
            if response.status_code == 200:
                logger.debug(f"Mercari: Session warmup successful")
                time.sleep(random.uniform(0.5, 1.5))  # Human-like delay
                return True
        return False
    except Exception as e:
        logger.debug(f"Mercari: Session warmup failed: {e}")
        return False


def _try_search_api(keywords: List[str], min_price: int, max_price: int, session, username=None) -> List[Dict]:
    """
    Try to fetch listings directly from Mercari's search API endpoints.
    This is more reliable than scraping HTML when available.
    """
    results = []
    
    # Try multiple API endpoints
    api_endpoints = [
        # Public search API
        {
            "url": "https://www.mercari.com/v1/api",
            "method": "POST",
            "payload": {
                "operationName": "searchProducts",
                "variables": {
                    "query": " ".join(keywords),
                    "minPrice": min_price,
                    "maxPrice": max_price,
                    "status": ["on_sale"],
                    "sort": "created_time",
                    "order": "desc",
                    "limit": 50,
                }
            },
        },
        # Alternative search endpoint
        {
            "url": f"https://www.mercari.com/search/",
            "method": "GET",
            "params": {
                "keyword": " ".join(keywords),
                "minPrice": min_price,
                "maxPrice": max_price,
                "itemConditions": "new,like_new,good",
                "sortBy": "created_time",
            },
        },
    ]
    
    for endpoint in api_endpoints:
        try:
            # Add delay between API attempts
            time.sleep(random.uniform(1.0, 2.0))
            
            headers = anti_blocking.build_headers(SITE_NAME, referer=BASE_URL)
            
            if endpoint["method"] == "POST":
                headers["Content-Type"] = "application/json"
                headers["Accept"] = "application/json"
                response = session.post(
                    endpoint["url"],
                    json=endpoint.get("payload"),
                    headers=headers,
                    timeout=20
                )
            else:
                response = session.get(
                    endpoint["url"],
                    params=endpoint.get("params"),
                    headers=headers,
                    timeout=20
                )
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    items = (
                        data.get("data", {}).get("search", {}).get("items", []) or
                        data.get("items", []) or
                        data.get("results", [])
                    )
                    
                    for item in items:
                        if isinstance(item, dict):
                            results.append({
                                "title": item.get("name") or item.get("title"),
                                "link": f"{BASE_URL}/item/{item.get('id')}/" if item.get('id') else item.get("url"),
                                "price": _parse_price_value(item.get("price")),
                                "image": item.get("thumbnails", [{}])[0].get("url") if item.get("thumbnails") else item.get("image"),
                            })
                    
                    if results:
                        logger.debug(f"Mercari: API endpoint returned {len(results)} items")
                        return results
                except (json.JSONDecodeError, KeyError):
                    continue
                    
        except Exception as e:
            logger.debug(f"Mercari: API endpoint {endpoint['url'][:50]} failed: {e}")
            continue
    
    return results


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


def get_mercari_flag_key(user_id=None, flag_name=SITE_NAME):
    """Expose running flag keys for orchestrators."""
    return _flag_key(flag_name, user_id)


seen_listings = {}


# ======================
# RUNNING FLAG
# ======================
running_flags = {SITE_NAME: True}
_seen_listings_lock = get_seen_listings_lock(SITE_NAME)


# ======================
# HELPER FUNCTIONS
# ======================
def _parse_price_value(value):
    """Convert price fragments into integer dollars."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, dict):
        # Common Mercari offer payloads
        for key in ("price", "amount", "value", "lowPrice"):
            nested = value.get(key)
            parsed = _parse_price_value(nested)
            if parsed is not None:
                return parsed
        return None
    if isinstance(value, list):
        for entry in value:
            parsed = _parse_price_value(entry)
            if parsed is not None:
                return parsed
        return None

    value_str = str(value)
    digits = "".join(ch for ch in value_str if ch.isdigit())
    return int(digits) if digits else None


def _coerce_json_listing(candidate):
    """Normalize a JSON candidate into listing dict."""
    if not isinstance(candidate, dict):
        return None

    title = candidate.get("title") or candidate.get("name") or candidate.get("headline")

    link = (
        candidate.get("url")
        or candidate.get("href")
        or candidate.get("link")
        or candidate.get("permalink")
    )
    if not link and candidate.get("slug"):
        slug = candidate["slug"].strip("/")
        link = f"{BASE_URL}/item/{slug}/"

    price_val = _parse_price_value(
        candidate.get("price")
        or candidate.get("priceAmount")
        or candidate.get("offers")
    )

    image = candidate.get("image") or candidate.get("images") or candidate.get("thumbnail")
    if isinstance(image, list):
        image = image[0]

    if isinstance(image, dict):
        image = image.get("url") or image.get("src")

    if title and link:
        return {
            "title": title,
            "link": link,
            "price": price_val,
            "image": image,
        }
    return None


def _extract_listings_from_json(payload):
    """Recursively scan JSON payloads for listing dictionaries."""
    listings = []
    seen_links = set()

    def _walk(node):
        if isinstance(node, dict):
            listing = _coerce_json_listing(node)
            if listing:
                normalized_link = listing["link"]
                if normalized_link not in seen_links:
                    listings.append(listing)
                    seen_links.add(normalized_link)
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for value in node:
                _walk(value)

    _walk(payload)
    return listings


def _parse_json_results(soup):
    """Gather listings from structured JSON embedded in the page."""
    listings = []

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(script.string)
        except (TypeError, json.JSONDecodeError):
            continue
        listings.extend(_extract_listings_from_json(data))

    next_data = soup.find("script", id="__NEXT_DATA__")
    if next_data and next_data.string:
        try:
            data = json.loads(next_data.string)
            listings.extend(_extract_listings_from_json(data))
        except (TypeError, json.JSONDecodeError):
            pass

    return listings


def _coerce_html_listing(node):
    """Normalize BeautifulSoup nodes into listing dictionaries."""
    if node is None:
        return None

    link_elem = node if node.name == "a" else node.find("a", href=True)
    if not link_elem:
        return None

    link = link_elem.get("href")
    if not link:
        return None
    link = urllib.parse.urljoin(BASE_URL, link)

    title = (
        link_elem.get("aria-label")
        or link_elem.get("title")
        or link_elem.get_text(" ", strip=True)
    )
    if not title:
        title_elem = node.find(["p", "span", "h2", "h3"], string=True)
        title = title_elem.get_text(" ", strip=True) if title_elem else None

    price_elem = None
    for candidate in node.find_all(["span", "div", "p"], string=True):
        text = candidate.get_text(" ", strip=True)
        if "$" in text:
            price_elem = candidate
            break

    price_val = _parse_price_value(price_elem.get_text()) if price_elem else None

    img_elem = node.find("img")
    image_url = None
    if img_elem:
        image_url = (
            img_elem.get("src")
            or img_elem.get("data-src")
            or img_elem.get("data-original")
        )
        if image_url:
            if image_url.startswith("//"):
                image_url = f"https:{image_url}"
            elif image_url.startswith("/"):
                image_url = urllib.parse.urljoin(BASE_URL, image_url)

    if title and link:
        return {
            "title": title,
            "link": link,
            "price": price_val,
            "image": image_url,
        }
    return None


def _parse_html_results(soup):
    """Gather listing dictionaries using multiple HTML selector strategies."""
    # Updated for December 2024 Mercari layout
    selectors = [
        # Current Mercari selectors (Next.js based)
        (1, "data-testid item tiles", lambda: soup.select('[data-testid="ItemTile"], [data-testid="item-tile"], [data-testid="SearchResults"] [data-testid]')),
        (2, "modern anchor cards", lambda: soup.select('a[href*="/item/m"]')),  # Mercari item IDs start with 'm'
        # Next.js hydration data containers
        (3, "next-data item containers", lambda: soup.find_all("div", attrs={"data-hydration-id": True})),
        (4, "div.merItemTile", lambda: soup.find_all("div", class_="merItemTile")),
        (5, "article elements", lambda: soup.find_all("article")),
        # Broader fallbacks
        (6, "div with item in class", lambda: soup.find_all("div", class_=lambda x: x and "item" in str(x).lower() if x else False)),
        (7, "section.item-tile", lambda: soup.find_all("section", class_=lambda x: x and "item" in str(x).lower() if x else False)),
        (8, "links with /item/ in href", lambda: soup.find_all("a", href=lambda x: x and "/item/" in str(x) if x else False)),
        # Card-based layouts
        (9, "div.card patterns", lambda: soup.find_all("div", class_=lambda x: x and "card" in str(x).lower() if x else False)),
        (10, "product grid items", lambda: soup.select('[class*="ProductGrid"] > div, [class*="product-grid"] > div')),
    ]

    listings = []
    seen_links = set()
    for index, label, strategy in selectors:
        try:
            nodes = strategy()
            if not nodes:
                continue
            log_parse_attempt(SITE_NAME, index, label)
            for node in nodes:
                listing = _coerce_html_listing(node)
                if listing and listing.get("link") and listing["link"] not in seen_links:
                    seen_links.add(listing["link"])
                    listings.append(listing)
            if listings:
                logger.debug(f"Mercari: Found {len(listings)} listings using method {index} ({label})")
                break
        except Exception as e:
            logger.debug(f"Mercari: Method {index} failed: {e}")
            continue

    return listings


def send_discord_message(title, link, price=None, image_url=None, user_id=None):
    """Save listing to database and emit notification logs."""
    try:
        is_valid, error = validate_listing(title, link, price)
        if not is_valid:
            logger.warning(f"⚠️ Skipping invalid Mercari listing: {error}")
            return

        if image_url and not validate_image_url(image_url):
            logger.debug(f"Mercari listing image filtered as placeholder: {image_url}")
            image_url = None

        save_listing(title, price, link, image_url, SITE_NAME, user_id=user_id)
        logger.info(f"📢 New Mercari for {user_id}: {title} | ${price} | {link}")
    except Exception as exc:
        logger.error(f"⚠️ Failed to save Mercari listing for {link}: {exc}")


def check_mercari(flag_name=SITE_NAME, user_id=None, user_seen=None, flag_key=None):
    settings = load_settings(username=user_id)
    keywords = settings["keywords"]
    min_price = settings["min_price"]
    max_price = settings["max_price"]
    check_interval = settings["interval"]
    location = settings.get("location", "boise")
    radius = settings.get("radius", 50)

    results = []
    flag_key = flag_key or _flag_key(flag_name, user_id)
    user_key = _user_key(user_id)
    if user_seen is None:
        user_seen = seen_listings.setdefault(user_key, {})

    with ScraperMetrics(SITE_NAME) as metrics:
        try:
            if not running_flags.get(flag_key, True):
                metrics.error = "stopped"
                return []

            location_coords = get_location_coords(location)
            if location_coords:
                logger.debug(f"Mercari: Searching {location} within {radius} miles")
            else:
                logger.warning(f"Mercari: Could not geocode location '{location}', defaulting to keyword search")

            base_url = f"{BASE_URL}{SEARCH_PATH}"
            query = " ".join(keywords)

            params = {
                "keyword": query,
                "price_min": min_price,
                "price_max": max_price,
                "sort": "created_time",
                "order": "desc",
                "status": "on_sale",
                "limit": 80,
                "page": 1,
                "_": random.randint(100000, 999999),
            }

            if location_coords:
                lat, lon = location_coords
                params["latitude"] = lat
                params["longitude"] = lon
                params["distance"] = int(miles_to_km(radius))

            # Use randomized param order to avoid fingerprinting
            full_url = base_url + "?" + anti_blocking.randomize_params_order(params)

            # Get persistent session with initialization
            session = get_session(SITE_NAME, initialize_url=BASE_URL, username=user_id)
            
            # Warm up session if it's new or has been idle
            _warmup_session(session, username=user_id)
            
            # Add extra delay before Mercari requests to avoid detection
            time.sleep(random.uniform(1.5, 3.0))
            
            start_time = time.time()
            
            # First try API endpoints (more reliable when available)
            api_results = _try_search_api(keywords, min_price, max_price, session, user_id)
            if api_results:
                logger.debug(f"Mercari: Using GraphQL API results ({len(api_results)} items)")
                # Process API results directly
                for item in api_results:
                    link = item.get("link")
                    if not link or not is_new_listing(link, user_seen, SITE_NAME):
                        continue
                    
                    title = item.get("title", "").strip()
                    price_val = item.get("price")
                    
                    if price_val and (price_val < min_price or price_val > max_price):
                        continue
                    
                    if not any(k in title.lower() for k in [k.lower() for k in keywords]):
                        continue
                    
                    normalized_link = normalize_url(link)
                    with lock:
                        user_seen[normalized_link] = datetime.now()
                    
                    send_discord_message(title, link, price_val, item.get("image"), user_id=user_id)
                    results.append(item)
                
                if results:
                    save_seen_listings(user_seen, SITE_NAME, username=user_id)
                    health_monitor.record_success(SITE_NAME, time.time() - start_time, "graphql_api")
                    metrics.success = True
                    metrics.listings_found = len(results)
                    return results
            
            # Fall back to HTML scraping with cascade
            response, strategy_used = make_request_with_cascade(
                full_url,
                SITE_NAME,
                session=session,
                referer=BASE_URL,
                origin=BASE_URL,
                session_initialize_url=BASE_URL,
                username=user_id,
                fallback_chain=MERCARI_FALLBACK_CHAIN,
            )
            
            response_time = time.time() - start_time

            if not response:
                metrics.error = "Failed to fetch page after all fallbacks"
                logger.warning("Mercari request exhausted all fallback strategies")
                health_monitor.record_failure(SITE_NAME, "all_fallbacks_exhausted")
                
                # Try browser fallback as last resort
                try:
                    from scrapers.browser_fallback import fetch_with_browser_sync, is_browser_available
                    if is_browser_available():
                        logger.info("Mercari: Attempting browser fallback")
                        html_content = fetch_with_browser_sync(full_url, SITE_NAME)
                        if html_content:
                            class MockResponse:
                                def __init__(self, text):
                                    self.text = text
                                    self.content = text.encode('utf-8')
                                    self.status_code = 200
                            response = MockResponse(html_content)
                            strategy_used = "browser"
                            logger.info("Mercari: Browser fallback succeeded")
                except ImportError:
                    pass
                except Exception as browser_error:
                    logger.debug(f"Mercari: Browser fallback failed: {browser_error}")
                
                if not response:
                    reset_session(SITE_NAME, initialize_url=BASE_URL, username=user_id)
                    return []
            
            # Record successful request
            health_monitor.record_success(SITE_NAME, response_time, strategy_used)
            
            if strategy_used:
                logger.debug(f"Mercari: Request succeeded using strategy '{strategy_used}'")
            
            # Use robust HTML parsing with fallback parsers
            from scrapers.common import parse_html_with_fallback
            try:
                soup = parse_html_with_fallback(
                    response.text,
                    parser_order=('html.parser', 'lxml'),
                    raw_bytes=response.content,
                    site_name=SITE_NAME,
                )
            except Exception as parse_error:
                logger.warning(f"Mercari: HTML parsing failed, trying BeautifulSoup fallback: {parse_error}")
                soup = BeautifulSoup(response.text, 'html.parser')

            listings_by_link = {}

            # Try JSON-LD extraction first (more reliable)
            json_candidates = _parse_json_results(soup)
            for candidate in json_candidates:
                if not candidate.get("link"):
                    continue
                listings_by_link.setdefault(candidate["link"], candidate)

            # Fallback to HTML parsing
            html_candidates = _parse_html_results(soup)
            for candidate in html_candidates:
                if not candidate.get("link"):
                    continue
                # Prefer JSON candidates over HTML if both exist
                if candidate["link"] not in listings_by_link:
                    listings_by_link[candidate["link"]] = candidate

            if not listings_by_link:
                log_selector_failure(SITE_NAME, "html/json", "search results", "posts")
                
                # Check if it's a block or just no results
                block_info = detect_block_type(response, SITE_NAME)
                if block_info:
                    block_type = block_info.get("type", "unknown")
                    cooldown_hint = block_info.get("cooldown_hint", 150)
                    
                    logger.warning(f"Mercari: Block detected - type: {block_type}")
                    anti_blocking.record_block(SITE_NAME, f"block:{block_type}", cooldown_hint=cooldown_hint)
                    health_monitor.record_block(SITE_NAME, block_type)
                    metrics.error = f"Block detected: {block_type}"
                    reset_session(SITE_NAME, initialize_url=BASE_URL, username=user_id)
                    return []
                
                # Check if it's a valid no-results page
                if is_zero_results_page(response, SITE_NAME):
                    logger.info(f"Mercari: No listings match criteria. Next check in {check_interval}s...")
                    metrics.success = True
                    metrics.listings_found = 0
                    return []
                
                logger.warning("Mercari: No items found with HTML or JSON selectors")
                metrics.success = True
                metrics.listings_found = 0
                return []

            keywords_lower = [k.lower() for k in keywords]
            processed_links = set()
            lock = get_seen_listings_lock(SITE_NAME)

            for candidate in listings_by_link.values():
                link = candidate.get("link")
                title = (candidate.get("title") or "").strip()
                price_val = _parse_price_value(candidate.get("price"))
                image_url = candidate.get("image")

                if not link or not title:
                    continue

                link = urllib.parse.urljoin(BASE_URL, link)
                normalized_link = normalize_url(link)
                if not normalized_link or normalized_link in processed_links:
                    continue

                processed_links.add(normalized_link)

                if price_val and (price_val < min_price or price_val > max_price):
                    continue

                title_lower = title.lower()
                if keywords_lower and not any(keyword in title_lower for keyword in keywords_lower):
                    continue

                if not is_new_listing(link, user_seen, SITE_NAME):
                    continue

                with lock:
                    user_seen[normalized_link] = datetime.now()

                if image_url:
                    if image_url.startswith("//"):
                        image_url = f"https:{image_url}"
                    elif image_url.startswith("/"):
                        image_url = urllib.parse.urljoin(BASE_URL, image_url)
                    if not validate_image_url(image_url):
                        logger.debug(f"Mercari image rejected as placeholder: {image_url}")
                        image_url = None

                send_discord_message(title, link, price_val, image_url, user_id=user_id)
                results.append({
                    "title": title,
                    "link": link,
                    "price": price_val,
                    "image": image_url,
                })

            if results:
                save_seen_listings(user_seen, SITE_NAME, username=user_id)
                metrics.success = True
                metrics.listings_found = len(results)
            else:
                logger.info(f"No new Mercari listings. Next check in {check_interval}s...")
                metrics.success = True
                metrics.listings_found = 0

            debug_scraper_output("Mercari", results)
            return results

        except Exception as exc:
            logger.error(f"Error processing Mercari results: {exc}")
            metrics.error = str(exc)
            return []


# ======================
# CONTINUOUS RUNNER
# ======================
def run_mercari_scraper(flag_name=SITE_NAME, user_id=None):
    """Run Mercari scraper continuously until stopped."""
    if check_recursion_guard(SITE_NAME):
        return

    set_recursion_guard(SITE_NAME, True)
    flag_key = _flag_key(flag_name, user_id)
    running_flags.setdefault(flag_key, True)

    try:
        logger.info(f"Starting Mercari scraper for user {user_id}")
        user_key = _user_key(user_id)
        user_seen = load_seen_listings(SITE_NAME, username=user_id)
        seen_listings[user_key] = user_seen

        try:
            while running_flags.get(flag_key, True):
                try:
                    logger.debug(f"Running Mercari scraper check for user {user_id}")
                    results = check_mercari(flag_name, user_id=user_id, user_seen=user_seen, flag_key=flag_key)
                    if results:
                        logger.info(f"Mercari scraper found {len(results)} new listings for user {user_id}")
                    else:
                        logger.debug(f"Mercari scraper found no new listings for user {user_id}")
                except RecursionError as exc:
                    print(f"ERROR: RecursionError in Mercari scraper: {exc}", file=sys.stderr, flush=True)
                    time.sleep(10)
                    continue
                except Exception as exc:
                    try:
                        logger.error(f"Error in Mercari scraper iteration: {exc}")
                    except Exception:
                        print(f"ERROR: Error in Mercari scraper iteration: {exc}", file=sys.stderr, flush=True)
                    continue

                settings = load_settings(username=user_id)
                interval = settings.get("interval", 60)
                human_delay(running_flags, flag_key, interval * 0.9, interval * 1.1)

        except KeyboardInterrupt:
            logger.info("Mercari scraper interrupted by user")
        except RecursionError as exc:
            print(f"FATAL: RecursionError in Mercari scraper main loop: {exc}", file=sys.stderr, flush=True)
        except Exception as exc:
            try:
                logger.error(f"Fatal error in Mercari scraper: {exc}")
            except Exception:
                print(f"ERROR: Fatal error in Mercari scraper: {exc}", file=sys.stderr, flush=True)
        finally:
            logger.info("Mercari scraper stopped")

    finally:
        set_recursion_guard(SITE_NAME, False)

