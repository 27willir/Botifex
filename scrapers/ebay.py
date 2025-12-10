import sys
import threading
import time
from datetime import datetime
import urllib.parse
import json
import re
from xml.etree import ElementTree as ET
from bs4 import BeautifulSoup
from utils import debug_scraper_output, logger
from db import save_listing
from error_handling import ErrorHandler, log_errors, ScraperError, NetworkError
from location_utils import get_location_coords, miles_to_km
from scrapers.common import (
    human_delay, normalize_url, is_new_listing, save_seen_listings,
    load_seen_listings, validate_listing, load_settings, get_session,
    make_request_with_retry, validate_image_url, check_recursion_guard,
    set_recursion_guard, log_selector_failure, log_parse_attempt,
    get_seen_listings_lock, extract_json_ld_items, reset_session
)
from scrapers.metrics import ScraperMetrics
from scrapers import anti_blocking

# ======================
# CONFIGURATION
# ======================
SITE_NAME = "ebay"
BASE_URL = "https://www.ebay.com"
_BLOCK_KEYWORDS = {
    "are you a robot",
    "unusual activity",
    "blocked",
    "access denied",
    "captcha",
    "verify you are human",
    "pardon our interruption",
    "why did this happen",
}


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


def get_ebay_flag_key(user_id=None, flag_name=SITE_NAME):
    """Public helper for orchestrators to compute running flag keys."""
    return _flag_key(flag_name, user_id)


seen_listings = {}

# ======================
# RUNNING FLAG
# ======================
running_flags = {SITE_NAME: True}

# ======================
# HELPER FUNCTIONS
# ======================
def _parse_price_value(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)

    value_str = str(value)
    if not value_str:
        return None

    normalized = value_str.strip().lower()
    if "to" in normalized:
        normalized = normalized.split("to", 1)[0]
    if "-" in normalized:
        parts = [p.strip() for p in normalized.split("-", 1)]
        # Preserve leading negative sign if the first segment is an actual negative number
        normalized = parts[0] if not normalized.startswith("-") else f"-{parts[1]}" if len(parts) > 1 else normalized

    if "," in normalized:
        if "." in normalized or normalized.count(",") > 1:
            normalized = normalized.replace(",", "")
        else:
            right_part_tokens = normalized.split(",", 1)[1].split()
            right_part = right_part_tokens[0] if right_part_tokens else ""
            if right_part.isdigit() and 1 <= len(right_part) <= 2:
                normalized = normalized.replace(",", ".", 1)
            else:
                normalized = normalized.replace(",", "")

    match = re.search(r"-?\d+(?:\.\d+)?", normalized)
    if not match:
        return None

    try:
        price = float(match.group())
    except ValueError:
        return None

    # eBay prices are in currency units; return rounded integer dollars
    return int(round(price))


def _parse_json_listings(soup):
    listings = []
    for script in soup.find_all('script', attrs={'type': 'application/ld+json'}):
        try:
            data = json.loads(script.string)
        except (TypeError, json.JSONDecodeError):
            continue

        blocks = data if isinstance(data, list) else [data]
        for block in blocks:
            if not isinstance(block, dict):
                continue
            entries = block.get('itemListElement')
            if not isinstance(entries, list):
                continue
            for entry in entries:
                item = entry.get('item') if isinstance(entry, dict) else entry
                if not isinstance(item, dict):
                    continue
                title = item.get('name')
                link = item.get('url')
                offers = item.get('offers')
                price_val = None
                if isinstance(offers, dict):
                    price_val = _parse_price_value(offers.get('price') or offers.get('lowPrice'))
                elif isinstance(offers, list):
                    for offer in offers:
                        price_val = _parse_price_value(offer.get('price') or offer.get('lowPrice'))
                        if price_val is not None:
                            break
                image_url = item.get('image')
                if isinstance(image_url, list):
                    image_url = image_url[0]

                listings.append({
                    'title': title,
                    'link': link,
                    'price': price_val,
                    'image': image_url,
                })

    return listings


def _parse_rss_item_description(description_html):
    """Extract price, image, and plain text description from RSS HTML fragments."""
    if not description_html:
        return None, None, None

    soup = BeautifulSoup(description_html, 'html.parser')

    image_url = None
    img_elem = soup.find('img')
    if img_elem:
        image_url = img_elem.get('src') or img_elem.get('data-src')
        if image_url and image_url.startswith('//'):
            image_url = f"https:{image_url}"

    text_content = soup.get_text(" ", strip=True)

    price_val = None
    price_match = re.search(r"\$[\d,]+(?:\.\d{2})?", text_content)
    if price_match:
        price_val = _parse_price_value(price_match.group())

    if price_val is None:
        price_val = _parse_price_value(text_content)

    return price_val, image_url, text_content or None


def _fetch_rss_fallback(full_url, session, username=None):
    """
    Attempt to recover listings via the public RSS endpoint when the HTML view is blocked.
    """
    if not full_url:
        return []

    rss_url = full_url
    if "_rss=" not in rss_url:
        joiner = "&" if "?" in rss_url else "?"
        rss_url = f"{rss_url}{joiner}_rss=1"

    logger.debug("eBay: attempting RSS fallback scrape")
    rss_response = make_request_with_retry(
        rss_url,
        SITE_NAME,
        session=session,
        referer=BASE_URL,
        origin=BASE_URL,
        session_initialize_url=BASE_URL,
        extra_headers={
            "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8"
        },
        username=username,
    )

    if not rss_response:
        return []

    try:
        root = ET.fromstring(rss_response.text)
    except ET.ParseError as exc:
        logger.warning(f"eBay RSS fallback parse error: {exc}")
        return []

    results = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        description_html = item.findtext("description") or ""

        if not title or not link:
            continue

        price_val, image_url, text_content = _parse_rss_item_description(description_html)
        results.append({
            "title": title,
            "link": link,
            "price": price_val,
            "image": image_url,
            "description": text_content,
        })

    logger.debug(f"eBay RSS fallback recovered {len(results)} candidate items")
    return results


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
        logger.info(f"📢 New eBay for {user_id}: {title} | ${price} | {link}")
    except Exception as e:
        logger.error(f"⚠️ Failed to save listing for {link}: {e}")


# ======================
# URL NORMALIZATION
# ======================
def resolve_listing_link(raw_link):
    """Normalize eBay listing URLs by removing tracking redirects and query strings."""
    if not raw_link or not isinstance(raw_link, str):
        return None

    href = raw_link.strip()
    if not href:
        return None

    if href.startswith("//"):
        href = f"https:{href}"

    if href.startswith("/"):
        href = urllib.parse.urljoin(BASE_URL, href)
    elif not href.lower().startswith("http"):
        href = urllib.parse.urljoin(BASE_URL, href)

    try:
        parsed = urllib.parse.urlparse(href)
        netloc = parsed.netloc.lower()

        if netloc in {"rover.ebay.com", "www.rover.ebay.com"}:
            query = urllib.parse.parse_qs(parsed.query)
            redirect_targets = (
                query.get("mpre")
                or query.get("mpp")
                or query.get("ru")
                or query.get("rvrtid")
                or query.get("redirect")
                or query.get("url")
            )
            for candidate in redirect_targets or []:
                if candidate:
                    decoded = urllib.parse.unquote(candidate)
                    resolved = resolve_listing_link(decoded)
                    if resolved:
                        return resolved

        normalized = normalize_url(href)
        return normalized or href
    except Exception as exc:
        logger.debug(f"Failed to normalize eBay link '{href}': {exc}")
        return href
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
        logger.info(f"📢 New eBay for {user_id}: {title} | ${price} | {link}")
    except Exception as e:
        logger.error(f"⚠️ Failed to save listing for {link}: {e}")

# ======================
# MAIN SCRAPER FUNCTION
# ======================
def check_ebay(flag_name=SITE_NAME, user_id=None, user_seen=None, flag_key=None):
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
    
    # Use metrics tracking
    with ScraperMetrics(SITE_NAME) as metrics:
        try:
            if not running_flags.get(flag_key, True):
                metrics.error = "stopped"
                return []

            # Get location coordinates for distance filtering
            location_coords = get_location_coords(location)
            if location_coords:
                logger.debug(f"eBay: Searching {location} within {radius} miles")
            else:
                logger.warning(f"Could not geocode location '{location}', using default")
            
            # Build eBay search URL
            # eBay uses _nkw for keyword, _udlo for min price, _udhi for max price
            base_url = "https://www.ebay.com/sch/i.html"
            params = {
                "_nkw": " ".join(keywords),  # Search keywords
                "_udlo": min_price,  # Min price
                "_udhi": max_price,  # Max price
                "_sop": 10,  # Sort by: newly listed
                "LH_ItemCondition": 3000,  # Used condition (can be adjusted)
                "_ipg": 50  # Items per page
            }
            
            # Add location filtering if coordinates available
            if location_coords:
                lat, lon = location_coords
                radius_km = int(miles_to_km(radius))
                params["_sadis"] = radius_km  # Search distance in km
                params["_stpos"] = f"{lat},{lon}"  # Search position (lat,lon)
            
            full_url = base_url + "?" + urllib.parse.urlencode(params)

            # Get persistent session
            session = get_session(SITE_NAME, BASE_URL, username=user_id)
            
            # Make request with automatic retry and rate limit detection
            response = make_request_with_retry(
                full_url,
                SITE_NAME,
                session=session,
                referer=BASE_URL,
                origin=BASE_URL,
                session_initialize_url=BASE_URL,
                username=user_id,
            )
            
            if not response:
                metrics.error = "Failed to fetch page after retries"
                logger.warning("eBay request exhausted retries without success")
                return []
            
            # Check for bot detection or blocking in response
            response_text_lower = response.text.lower()
            if any(keyword in response_text_lower for keyword in _BLOCK_KEYWORDS):
                logger.warning("eBay: Block page detected (bot protection triggered)")
                anti_blocking.record_block(SITE_NAME, "keyword:ebay-block", cooldown_hint=300)
                metrics.error = "Bot protection page detected"
                session = reset_session(SITE_NAME, initialize_url=BASE_URL, username=user_id)

                rss_candidates = _fetch_rss_fallback(full_url, session, username=user_id)
                if rss_candidates:
                    logger.info(f"eBay: RSS fallback recovered {len(rss_candidates)} items after block page")
                    for entry in rss_candidates:
                        handle_candidate(
                            entry.get("title"),
                            entry.get("link"),
                            entry.get("price"),
                            entry.get("image"),
                            entry.get("description"),
                        )

                    if results:
                        save_seen_listings(user_seen, SITE_NAME, username=user_id)
                        metrics.success = True
                        metrics.listings_found = len(results)
                        metrics.error = None
                    else:
                        logger.info(f"No new eBay listings from RSS fallback. Next check in {check_interval}s...")
                        metrics.success = True
                        metrics.listings_found = 0

                    debug_scraper_output("eBay", results)
                    return results

                logger.warning("eBay RSS fallback did not return any items after block page")
                return []
            
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
                logger.warning(f"eBay: HTML parsing failed, trying BeautifulSoup fallback: {parse_error}")
                soup = BeautifulSoup(response.text, 'html.parser')
            
            # Helper function for extracting items from listing links
            def _extract_from_listing_links(soup):
                """Extract items from listing links as fallback."""
                link_elements = soup.find_all('a', href=lambda x: x and '/itm/' in str(x) if x else False)
                if not link_elements:
                    return []
                items_found = []
                seen_links = set()
                for link_elem in link_elements:
                    href = link_elem.get('href', '')
                    if href and href not in seen_links:
                        seen_links.add(href)
                        parent = link_elem.find_parent(['li', 'div', 'article', 'section'])
                        if parent and parent not in items_found:
                            items_found.append(parent)
                return items_found
            
            # eBay uses different HTML structures, try multiple patterns - expanded with better fallbacks
            items = []
            parse_strategies = [
                (1, "s-item__wrapper divs", lambda: soup.find_all('div', class_='s-item__wrapper')),
                (2, "s-item list items", lambda: soup.find_all('li', class_='s-item')),
                (3, "generic s-item pattern", lambda: soup.find_all('div', attrs={'class': lambda x: x and 's-item' in str(x).lower() if x else False})),
                (4, "srp-results items", lambda: soup.find_all('div', class_='srp-results') or soup.find_all('ul', class_='srp-results')),
                (5, "items with data-view", lambda: soup.find_all('div', attrs={'data-view': lambda x: x and 'mi:1686' in str(x) if x else False})),
                (6, "ul.srp-results direct children", lambda: [ul for ul in soup.find_all('ul', class_='srp-results') if ul][0].find_all('li', recursive=False) if soup.find_all('ul', class_='srp-results') else []),
                (7, "div with data-view='mi:1686'", lambda: soup.find_all('div', attrs={'data-view': 'mi:1686'})),
                (8, "links with href containing /itm/", lambda: _extract_from_listing_links(soup)),
            ]
            
            for method_num, description, strategy in parse_strategies:
                log_parse_attempt(SITE_NAME, method_num, description)
                try:
                    items = strategy()
                    if items:
                        logger.debug(f"eBay: Found {len(items)} items using method {method_num} ({description})")
                        break
                except Exception as e:
                    logger.debug(f"eBay: Method {method_num} failed: {e}")
                    continue

            # Try JSON-LD extraction if HTML parsing failed
            json_items = []
            json_ld_items = []
            if not items:
                log_parse_attempt(SITE_NAME, 9, "JSON-LD itemListElement")
                json_items = [entry for entry in _parse_json_listings(soup) if entry.get('title') and entry.get('link')]
                if not json_items:
                    log_parse_attempt(SITE_NAME, 10, "Common JSON-LD extractor")
                    json_ld_items = extract_json_ld_items(response.text)
                    if not json_ld_items:
                        # Try extracting from script tags with inline JSON
                        log_parse_attempt(SITE_NAME, 11, "Inline JSON in script tags")
                        for script in soup.find_all('script', type='application/json'):
                            try:
                                data = json.loads(script.string)
                                if isinstance(data, dict):
                                    items_data = data.get('items') or data.get('results') or data.get('listings', [])
                                    if items_data:
                                        json_items.extend([item for item in items_data if isinstance(item, dict) and item.get('title')])
                                        break
                            except (json.JSONDecodeError, TypeError, AttributeError):
                                continue
                        
                        if not json_items and not json_ld_items:
                            # Log HTML snippet for debugging
                            html_snippet = response.text[:2000].replace('\n', ' ').replace('\r', ' ')
                            logger.debug(f"eBay HTML snippet (first 2000 chars): {html_snippet}")
                            # Check for common class names
                            import re
                            found_classes = set()
                            for match in re.findall(r'class=["\']([^"\']+)["\']', response.text[:5000]):
                                found_classes.update(match.split())
                            logger.debug(f"eBay found class names: {sorted(found_classes)[:20]}")
                            log_selector_failure(SITE_NAME, "combined selectors", "s-item patterns + JSON-LD", "listing items")
                            logger.warning("eBay: No items found with HTML or JSON-LD selectors")
                            metrics.success = True
                            metrics.listings_found = 0
                            return []
            
            logger.debug(f"Found {len(items) if items else len(json_items) if json_items else len(json_ld_items)} eBay items to process")
            
            # Pre-compile keywords for faster matching and prep seen listings lock
            keywords_lower = [k.lower() for k in keywords]
            seen_lock = get_seen_listings_lock(SITE_NAME)
            candidates_processed = set()

            def handle_candidate(title, raw_link, price_val, image_url=None, description=None):
                """Apply shared filtering/notification logic for a listing candidate."""

                if not title or not raw_link:
                    return

                link = resolve_listing_link(raw_link)
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

                normalized_link = normalize_url(link)
                if not normalized_link:
                    return
                if normalized_link in candidates_processed:
                    return
                candidates_processed.add(normalized_link)

                with seen_lock:
                    user_seen[normalized_link] = datetime.now()

                send_discord_message(title, link, normalized_price, image_url, user_id=user_id)
                results.append({
                    "title": title,
                    "link": link,
                    "price": normalized_price,
                    "image": image_url
                })

            # Use json_ld_items if we have them from fallback
            if not items and json_ld_items:
                logger.debug(f"eBay JSON-LD fallback produced {len(json_ld_items)} entries")

            if items:
                for item in items:
                    try:
                        title_elem = (
                            item.find('div', class_='s-item__title') or
                            item.find('h3', class_='s-item__title') or
                            item.find('a', class_='s-item__link')
                        )

                        if not title_elem:
                            continue

                        title = title_elem.get_text(strip=True)

                        if not title or "Shop on eBay" in title:
                            continue

                        link_elem = item.find('a', class_='s-item__link') or item.find('a', href=True)
                        if not link_elem or not link_elem.get('href'):
                            continue

                        link = resolve_listing_link(link_elem.get('href'))
                        if not link:
                            continue

                        # Enhanced price extraction with multiple fallbacks
                        price_val = None
                        price_selectors = [
                            item.find('span', class_='s-item__price'),
                            item.find('span', class_='s-item__price--last'),
                            item.find('span', attrs={'class': lambda x: x and 'price' in str(x).lower() if x else False}),
                            item.find('div', attrs={'class': lambda x: x and 'price' in str(x).lower() if x else False}),
                        ]
                        for price_elem in price_selectors:
                            if price_elem:
                                price_text = price_elem.get_text(strip=True)
                                price_val = _parse_price_value(price_text)
                                if price_val is not None:
                                    break
                        
                        # Enhanced image extraction with multiple fallbacks
                        image_url = None
                        img_selectors = [
                            item.find('img', class_='s-item__image-img'),
                            item.find('img', attrs={'data-src': True}),
                            item.find('img', src=lambda x: x and 'ebayimg' in str(x) if x else False),
                            item.find('img'),
                        ]
                        for img_elem in img_selectors:
                            if img_elem:
                                image_url = (img_elem.get('data-src') or 
                                            img_elem.get('data-lazy') or
                                            img_elem.get('src') or
                                            img_elem.get('data-original'))
                                if image_url:
                                    if image_url.startswith('//'):
                                        image_url = f"https:{image_url}"
                                    elif not image_url.startswith('http'):
                                        continue
                                    # Skip placeholder images
                                    if any(token in image_url.lower() for token in ('s-l64', 's-l50', 'data:', 'placeholder', '1x1')):
                                        continue
                                    # Found valid image
                                    break

                        handle_candidate(title, link, price_val, image_url)
                    except Exception as e:
                        logger.warning(f"Error parsing an eBay listing: {e}")
                        continue
            elif json_items:
                # Use parsed JSON items
                for entry in json_items:
                    try:
                        title = entry.get("title")
                        link = resolve_listing_link(entry.get("link"))
                        if not link:
                            continue

                        image_url = entry.get("image")
                        if isinstance(image_url, str) and image_url.startswith('//'):
                            image_url = f"https:{image_url}"
                        price_val = entry.get("price")

                        handle_candidate(title, link, price_val, image_url)
                    except Exception as e:
                        logger.warning(f"Error parsing eBay JSON listing: {e}")
                        continue
            elif json_ld_items:
                for entry in json_ld_items:
                    try:
                        title = entry.get("title")
                        link = resolve_listing_link(entry.get("url"))
                        if not link:
                            continue

                        image_url = entry.get("image")
                        if isinstance(image_url, str) and image_url.startswith('//'):
                            image_url = f"https:{image_url}"
                        description = entry.get("description")
                        price_val = entry.get("price")

                        handle_candidate(title, link, price_val, image_url, description)
                    except Exception as e:
                        logger.warning(f"Error parsing eBay JSON-LD listing: {e}")
                        continue
            
            if results:
                save_seen_listings(user_seen, SITE_NAME, username=user_id)
                metrics.success = True
                metrics.listings_found = len(results)
            else:
                logger.info(f"No new eBay listings. Next check in {check_interval}s...")
                metrics.success = True
                metrics.listings_found = 0

            debug_scraper_output("eBay", results)
            return results

        except Exception as e:
            logger.error(f"Error processing eBay results: {e}")
            metrics.error = str(e)
            return []

# ======================
# CONTINUOUS RUNNER
# ======================
def run_ebay_scraper(flag_name=SITE_NAME, user_id=None):
    """Run scraper continuously until stopped via running_flags."""
    # Check for recursion
    if check_recursion_guard(SITE_NAME):
        return
    
    set_recursion_guard(SITE_NAME, True)
    flag_key = _flag_key(flag_name, user_id)
    running_flags.setdefault(flag_key, True)
    
    try:
        logger.info(f"Starting eBay scraper for user {user_id}")
        user_key = _user_key(user_id)
        user_seen = load_seen_listings(SITE_NAME, username=user_id)
        seen_listings[user_key] = user_seen
        
        try:
            while running_flags.get(flag_key, True):
                try:
                    logger.debug(f"Running eBay scraper check for user {user_id}")
                    results = check_ebay(flag_name, user_id=user_id, user_seen=user_seen, flag_key=flag_key)
                    if results:
                        logger.info(f"eBay scraper found {len(results)} new listings for user {user_id}")
                    else:
                        logger.debug(f"eBay scraper found no new listings for user {user_id}")
                except RecursionError as e:
                    import sys
                    print(f"ERROR: RecursionError in eBay scraper: {e}", file=sys.stderr, flush=True)
                    # Wait before retrying to avoid tight loop
                    time.sleep(10)
                    continue
                except Exception as e:
                    # Use fallback logging to avoid recursion in error handling
                    try:
                        logger.error(f"Error in eBay scraper iteration: {e}")
                    except:
                        import sys
                        print(f"ERROR: Error in eBay scraper iteration: {e}", file=sys.stderr, flush=True)
                    # Continue running but log the error
                    continue
                
                settings = load_settings(username=user_id)
                # Delay dynamically based on interval
                human_delay(running_flags, flag_key, settings["interval"]*0.9, settings["interval"]*1.1)
                
        except KeyboardInterrupt:
            logger.info("eBay scraper interrupted by user")
        except RecursionError as e:
            import sys
            print(f"FATAL: RecursionError in eBay scraper main loop: {e}", file=sys.stderr, flush=True)
        except Exception as e:
            try:
                logger.error(f"Fatal error in eBay scraper: {e}")
            except:
                import sys
                print(f"ERROR: Fatal error in eBay scraper: {e}", file=sys.stderr, flush=True)
        finally:
            logger.info("eBay scraper stopped")
    finally:
        set_recursion_guard(SITE_NAME, False)

