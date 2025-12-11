import sys
import threading
import time
import re
from datetime import datetime
import urllib.parse
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
    is_zero_results_page, RequestStrategy
)
from scrapers import anti_blocking
from scrapers import health_monitor
from scrapers.metrics import ScraperMetrics

# ======================
# CONFIGURATION
# ======================
SITE_NAME = "ksl"
BASE_URL = "https://classifieds.ksl.com"

# KSL-specific fallback chain
KSL_FALLBACK_CHAIN = [
    RequestStrategy("normal"),
    RequestStrategy("fresh_session", fresh_session=True),
    RequestStrategy("mobile", use_mobile=True),
    RequestStrategy("proxy", use_proxy=True),
    RequestStrategy("mobile_proxy", use_mobile=True, use_proxy=True),
]


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


def get_ksl_flag_key(user_id=None, flag_name=SITE_NAME):
    """Public helper to compute running flag keys for orchestrators."""
    return _flag_key(flag_name, user_id)


seen_listings = {}

# ======================
# RUNNING FLAG
# ======================
running_flags = {SITE_NAME: True}

# ======================
# HELPER FUNCTIONS
# ======================
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
        
        # Save to database
        save_listing(title, price, link, image_url, SITE_NAME, user_id=user_id)
        logger.info(f"📢 New KSL: {title} | ${price} | {link}")
    except Exception as e:
        logger.error(f"⚠️ Failed to save listing for {link}: {e}")

# ======================
# MAIN SCRAPER FUNCTION
# ======================
def check_ksl(flag_name=SITE_NAME, user_id=None, user_seen=None, flag_key=None):
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
                logger.debug(f"KSL: Searching {location} within {radius} miles")
            else:
                logger.warning(f"Could not geocode location '{location}', using default")
            
            # Build URL
            base_url = "https://classifieds.ksl.com/search/"
            params = {
                "keyword": " ".join(keywords),
                "priceFrom": min_price,
                "priceTo": max_price,
            }
            
            # Add location filtering if coordinates available
            if location_coords:
                lat, lon = location_coords
                params["latitude"] = lat
                params["longitude"] = lon
                params["miles"] = radius
            
            # Use randomized param order to avoid fingerprinting
            full_url = base_url + "?" + anti_blocking.randomize_params_order(params)

            # Get persistent session with initialization
            session = get_session(SITE_NAME, initialize_url=BASE_URL, username=user_id)
            
            # Add extra delay before KSL requests to avoid detection
            import random
            time.sleep(random.uniform(1.0, 2.5))
            
            start_time = time.time()
            
            # Use cascade fallback system for maximum reliability
            response, strategy_used = make_request_with_cascade(
                full_url,
                SITE_NAME,
                session=session,
                referer=BASE_URL,
                origin=BASE_URL,
                session_initialize_url=BASE_URL,
                username=user_id,
                fallback_chain=KSL_FALLBACK_CHAIN,
            )
            
            response_time = time.time() - start_time
            
            if not response:
                metrics.error = "Failed to fetch page after all fallbacks"
                logger.warning("KSL request exhausted all fallback strategies")
                health_monitor.record_failure(SITE_NAME, "all_fallbacks_exhausted")
                reset_session(SITE_NAME, initialize_url=BASE_URL, username=user_id)
                return []
            
            # Record successful request
            health_monitor.record_success(SITE_NAME, response_time, strategy_used)
            
            if strategy_used:
                logger.debug(f"KSL: Request succeeded using strategy '{strategy_used}'")
            
            # Use robust HTML parsing with fallback
            tree = None
            try:
                tree = html.fromstring(response.text)
            except Exception as parse_error:
                logger.warning(f"KSL: lxml parsing failed, trying BeautifulSoup: {parse_error}")
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(response.text, 'html.parser')
                try:
                    from lxml import html as lxml_html
                    tree = lxml_html.fromstring(str(soup))
                except Exception:
                    tree = soup
            
            # Helper function for extracting posts from listing links
            def _extract_from_listing_links(tree):
                """Extract posts from listing links as fallback."""
                if not hasattr(tree, 'xpath'):
                    return []
                link_elements = tree.xpath('//a[contains(@href, "/item/") or contains(@href, "/listing/")]')
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
            
            # Try multiple XPath patterns for robustness - updated for December 2024 KSL layout
            posts = []
            parse_strategies = [
                # Current KSL React-based selectors
                (1, "listing class sections", lambda: tree.xpath('//section[contains(@class,"listing")]') if hasattr(tree, 'xpath') else []),
                (2, "listing-item divs", lambda: tree.xpath('//div[contains(@class,"listing-item") or contains(@class,"ListingItem")]') if hasattr(tree, 'xpath') else []),
                (3, "listing article elements", lambda: tree.xpath('//article[contains(@class,"listing") or contains(@class,"Listing")]') if hasattr(tree, 'xpath') else []),
                (4, "div.listing-card or card", lambda: tree.xpath('//div[contains(@class,"listing-card") or contains(@class,"ListingCard") or contains(@class,"Card")]') if hasattr(tree, 'xpath') else []),
                (5, "div.item-card", lambda: tree.xpath('//div[contains(@class,"item-card") or contains(@class,"ItemCard")]') if hasattr(tree, 'xpath') else []),
                (6, "article.item", lambda: tree.xpath('//article[contains(@class,"item") or contains(@class,"Item")]') if hasattr(tree, 'xpath') else []),
                # React data attributes
                (7, "elements with data-testid", lambda: tree.xpath('//*[@data-testid and (contains(@data-testid,"listing") or contains(@data-testid,"item"))]') if hasattr(tree, 'xpath') else []),
                (8, "div with listing link", lambda: tree.xpath('//div[.//a[contains(@href,"/listing/") or contains(@href,"/item/")]]') if hasattr(tree, 'xpath') else []),
                (9, "links with href containing /listing/", lambda: _extract_from_listing_links(tree)),
            ]
            
            for method_num, description, strategy in parse_strategies:
                log_parse_attempt(SITE_NAME, method_num, description)
                try:
                    posts = strategy()
                    if posts:
                        logger.debug(f"KSL: Found {len(posts)} posts using method {method_num} ({description})")
                        break
                except Exception as e:
                    logger.debug(f"KSL: Method {method_num} failed: {e}")
                    continue
            
            json_ld_items = []
            if not posts:
                log_parse_attempt(SITE_NAME, 8, "JSON-LD itemListElement fallback")
                json_ld_items = extract_json_ld_items(response.text)
                if not json_ld_items:
                    log_selector_failure(SITE_NAME, "json-ld", "itemListElement", "posts")
                    
                    # Check if it's a block or just no results
                    block_info = detect_block_type(response, SITE_NAME)
                    if block_info:
                        block_type = block_info.get("type", "unknown")
                        cooldown_hint = block_info.get("cooldown_hint", 120)
                        
                        logger.warning(f"KSL: Block detected - type: {block_type}")
                        anti_blocking.record_block(SITE_NAME, f"block:{block_type}", cooldown_hint=cooldown_hint)
                        health_monitor.record_block(SITE_NAME, block_type)
                        metrics.error = f"Block detected: {block_type}"
                        reset_session(SITE_NAME, initialize_url=BASE_URL, username=user_id)
                        return []
                    
                    # Check if it's a valid no-results page
                    if is_zero_results_page(response, SITE_NAME):
                        logger.info(f"KSL: No listings match criteria. Next check in {check_interval}s...")
                        metrics.success = True
                        metrics.listings_found = 0
                        return []

                    logger.warning("KSL: No posts found with HTML or JSON-LD selectors")
                    metrics.success = True  # Not an error, just no results
                    metrics.listings_found = 0
                    return []
                logger.debug(f"KSL JSON-LD fallback produced {len(json_ld_items)} entries")
            else:
                logger.debug(f"KSL HTML selectors returned {len(posts)} posts")
            
            # Pre-compile keywords for faster matching
            keywords_lower = [k.lower() for k in keywords]
            
            for post in posts:
                try:
                    # Enhanced link extraction with multiple fallbacks
                    link = None
                    if hasattr(post, 'xpath'):
                        link_selectors = [
                            ".//a[@class='listing-item-link']/@href",
                            ".//a[contains(@class,'listing')]/@href",
                            ".//a[contains(@href,'/item/')]/@href",
                            ".//a[contains(@href,'/listing/')]/@href",
                            ".//a/@href",
                            ".//h2/a/@href | .//h3/a/@href",
                        ]
                        for selector in link_selectors:
                            try:
                                link_elems = post.xpath(selector)
                                if link_elems:
                                    link = link_elems[0]
                                    break
                            except Exception:
                                continue
                    
                    if not link:
                        continue
                    
                    if not link.startswith("http"):
                        link = urllib.parse.urljoin(BASE_URL, link)

                    # Enhanced title extraction with multiple fallbacks
                    title = None
                    if hasattr(post, 'xpath'):
                        title_selectors = [
                            ".//h2/text()",
                            ".//h3/text()",
                            ".//div[contains(@class,'title')]//text()",
                            ".//a[@class='listing-item-link']/@title",
                            ".//a[contains(@class,'listing')]//text()",
                            ".//span[contains(@class,'title')]//text()",
                        ]
                        for selector in title_selectors:
                            try:
                                title_elems = post.xpath(selector)
                                if title_elems:
                                    title = title_elems[0].strip() if isinstance(title_elems[0], str) else None
                                    if title:
                                        break
                            except Exception:
                                continue

                    if not title:
                        continue

                    # Enhanced price extraction with multiple fallbacks
                    price_val = None
                    if hasattr(post, 'xpath'):
                        price_selectors = [
                            ".//span[contains(@class,'price')]//text()",
                            ".//div[contains(@class,'price')]//text()",
                            ".//h3[contains(text(),'$')]//text()",
                            ".//*[contains(@class,'price')]//text()",
                            ".//*[contains(text(),'$')]/text()",
                        ]
                        for selector in price_selectors:
                            try:
                                price_elems = post.xpath(selector)
                                if price_elems:
                                    price_text = price_elems[0] if isinstance(price_elems[0], str) else str(price_elems[0])
                                    try:
                                        price_val = int(price_text.replace("$", "").replace(",", "").strip())
                                        if price_val:
                                            break
                                    except (ValueError, AttributeError):
                                        continue
                            except Exception:
                                continue

                    if price_val and (price_val < min_price or price_val > max_price):
                        continue

                    title_lower = title.lower()
                    if not any(k in title_lower for k in keywords_lower):
                        continue

                    if not is_new_listing(link, user_seen, SITE_NAME):
                        continue

                    normalized_link = normalize_url(link)
                    lock = get_seen_listings_lock(SITE_NAME)
                    with lock:
                        user_seen[normalized_link] = datetime.now()

                    # Enhanced image extraction with multiple fallbacks
                    image_url = None
                    if hasattr(post, 'xpath'):
                        img_selectors = [
                            ".//img[@data-src]/@data-src",
                            ".//img[@src]/@src",
                            ".//img[@data-lazy]/@data-lazy",
                            ".//img/@src",
                        ]
                        for selector in img_selectors:
                            try:
                                img_elem = post.xpath(selector)
                                if img_elem:
                                    image_url = img_elem[0]
                                    if image_url.startswith("//"):
                                        image_url = f"https:{image_url}"
                                    elif image_url and not image_url.startswith("http"):
                                        image_url = urllib.parse.urljoin(BASE_URL, image_url)
                                    # Validate image URL
                                    if image_url and validate_image_url(image_url):
                                        break
                                    else:
                                        image_url = None
                            except Exception:
                                continue

                    send_discord_message(title, link, price_val, image_url, user_id=user_id)
                    results.append({"title": title, "link": link, "price": price_val, "image": image_url})
                except Exception as e:
                    logger.warning(f"Error parsing a KSL post: {e}")

            if not posts and json_ld_items:
                lock = get_seen_listings_lock(SITE_NAME)
                for entry in json_ld_items:
                    try:
                        title = entry.get("title")
                        link = entry.get("url")
                        if link:
                            link = urllib.parse.urljoin(BASE_URL, link)
                        if not title or not link:
                            continue

                        price_val = entry.get("price")
                        if price_val is not None:
                            try:
                                price_val = int(float(price_val))
                            except (TypeError, ValueError):
                                price_val = None

                        description = entry.get("description")
                        text_blob = title.lower()
                        if isinstance(description, str):
                            text_blob = f"{text_blob} {description.lower()}"

                        if price_val and (price_val < min_price or price_val > max_price):
                            continue

                        if not any(k in text_blob for k in keywords_lower):
                            continue

                        if not is_new_listing(link, user_seen, SITE_NAME):
                            continue

                        normalized_link = normalize_url(link)
                        with lock:
                            user_seen[normalized_link] = datetime.now()

                        image_url = entry.get("image")
                        if isinstance(image_url, str):
                            if image_url.startswith("//"):
                                image_url = f"https:{image_url}"
                            elif image_url.startswith("/"):
                                image_url = urllib.parse.urljoin(BASE_URL, image_url)

                        send_discord_message(title, link, price_val, image_url, user_id=user_id)
                        results.append({"title": title, "link": link, "price": price_val, "image": image_url})
                    except Exception as e:
                        logger.warning(f"Error parsing KSL JSON-LD listing: {e}")

            if results:
                save_seen_listings(user_seen, SITE_NAME, username=user_id)
                metrics.success = True
                metrics.listings_found = len(results)
            else:
                logger.info(f"No new KSL listings. Next check in {check_interval}s...")
                metrics.success = True
                metrics.listings_found = 0

            debug_scraper_output("KSL", results)
            return results

        except Exception as e:
            logger.error(f"Error processing KSL results: {e}")
            metrics.error = str(e)
            return []

# ======================
# CONTINUOUS RUNNER
# ======================
def run_ksl_scraper(flag_name=SITE_NAME, user_id=None):
    """Run KSL scraper with proper error handling."""
    # Check for recursion
    if check_recursion_guard(SITE_NAME):
        return
    
    set_recursion_guard(SITE_NAME, True)
    flag_key = _flag_key(flag_name, user_id)
    running_flags.setdefault(flag_key, True)
    
    try:
        logger.info(f"Starting KSL scraper for user {user_id}")
        user_key = _user_key(user_id)
        user_seen = load_seen_listings(SITE_NAME, username=user_id)
        seen_listings[user_key] = user_seen
        
        try:
            while running_flags.get(flag_key, True):
                try:
                    logger.debug(f"Running KSL scraper check for user {user_id}")
                    results = check_ksl(flag_name, user_id=user_id, user_seen=user_seen, flag_key=flag_key)
                    if results:
                        logger.info(f"KSL scraper found {len(results)} new listings for user {user_id}")
                    else:
                        logger.debug(f"KSL scraper found no new listings for user {user_id}")
                except RecursionError as e:
                    print(f"ERROR: RecursionError in KSL scraper: {e}", file=sys.stderr, flush=True)
                    # Wait before retrying to avoid tight loop
                    time.sleep(10)
                    continue
                except Exception as e:
                    # Use fallback logging to avoid recursion in error handling
                    try:
                        logger.error(f"Error in KSL scraper iteration: {e}")
                    except:
                        print(f"ERROR: Error in KSL scraper iteration: {e}", file=sys.stderr, flush=True)
                    # Continue running but log the error
                    continue
                
                settings = load_settings(username=user_id)
                human_delay(running_flags, flag_key, settings["interval"]*0.9, settings["interval"]*1.1)
                
        except KeyboardInterrupt:
            logger.info("KSL scraper interrupted by user")
        except RecursionError as e:
            print(f"FATAL: RecursionError in KSL scraper main loop: {e}", file=sys.stderr, flush=True)
        except Exception as e:
            try:
                logger.error(f"Fatal error in KSL scraper: {e}")
            except:
                print(f"ERROR: Fatal error in KSL scraper: {e}", file=sys.stderr, flush=True)
        finally:
            logger.info("KSL scraper stopped")
    finally:
        set_recursion_guard(SITE_NAME, False)

