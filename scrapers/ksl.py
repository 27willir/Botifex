import sys
import threading
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
    make_request_with_retry, validate_image_url, check_recursion_guard,
    set_recursion_guard, log_selector_failure, log_parse_attempt,
    get_seen_listings_lock, extract_json_ld_items
)
from scrapers import anti_blocking
from scrapers.metrics import ScraperMetrics

# ======================
# CONFIGURATION
# ======================
SITE_NAME = "ksl"
BASE_URL = "https://classifieds.ksl.com"

seen_listings = {}

# ======================
# RUNNING FLAG
# ======================
running_flags = {SITE_NAME: True}

# ======================
# HELPER FUNCTIONS
# ======================
def send_discord_message(title, link, price=None, image_url=None):
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
        save_listing(title, price, link, image_url, SITE_NAME)
        logger.info(f"📢 New KSL: {title} | ${price} | {link}")
    except Exception as e:
        logger.error(f"⚠️ Failed to save listing for {link}: {e}")

# ======================
# MAIN SCRAPER FUNCTION
# ======================
def check_ksl(flag_name=SITE_NAME):
    settings = load_settings()
    keywords = settings["keywords"]
    min_price = settings["min_price"]
    max_price = settings["max_price"]
    check_interval = settings["interval"]
    location = settings.get("location", "boise")
    radius = settings.get("radius", 50)

    results = []
    
    # Use metrics tracking
    with ScraperMetrics(SITE_NAME) as metrics:
        try:
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
            
            full_url = base_url + "?" + urllib.parse.urlencode(params)

            # Get persistent session
            session = get_session(SITE_NAME, BASE_URL)
            
            # Make request with automatic retry and rate limit detection
            response = make_request_with_retry(full_url, SITE_NAME, session=session)
            
            if not response:
                metrics.error = "Failed to fetch page after retries"
                return []
            
            tree = html.fromstring(response.text)
            
            # Try multiple XPath patterns for robustness
            log_parse_attempt(SITE_NAME, 1, "listing class sections")
            posts = tree.xpath('//section[contains(@class,"listing")]')
            if not posts:
                log_parse_attempt(SITE_NAME, 2, "listing-item divs")
                posts = tree.xpath('//div[contains(@class,"listing-item")]')
            if not posts:
                log_parse_attempt(SITE_NAME, 3, "listing article elements")
                posts = tree.xpath('//article[contains(@class,"listing")]')
            
            json_ld_items = []
            if not posts:
                log_parse_attempt(SITE_NAME, 4, "JSON-LD itemListElement fallback")
                json_ld_items = extract_json_ld_items(response.text)
                if not json_ld_items:
                    log_selector_failure(SITE_NAME, "json-ld", "itemListElement", "posts")
                    snippet = (response.text[:2000] if getattr(response, "text", None) else "").lower()
                    block_keywords = (
                        "are you a robot",
                        "unusual activity",
                        "blocked",
                        "slow down",
                    )
                    if any(keyword in snippet for keyword in block_keywords):
                        anti_blocking.record_block(SITE_NAME, "keyword:ksl-block", cooldown_hint=120)

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
                    link_elems = (
                        post.xpath(".//a[@class='listing-item-link']/@href") or
                        post.xpath(".//a[contains(@class,'listing')]/@href") or
                        post.xpath(".//a/@href")
                    )

                    if not link_elems:
                        continue

                    link = link_elems[0]
                    if not link.startswith("http"):
                        link = urllib.parse.urljoin(BASE_URL, link)

                    title_elems = (
                        post.xpath(".//h2/text()") or
                        post.xpath(".//h3/text()") or
                        post.xpath(".//div[contains(@class,'title')]/text()")
                    )

                    if not title_elems:
                        continue

                    title = title_elems[0].strip()

                    price_val = None
                    price_elems = (
                        post.xpath(".//h3/text()") or
                        post.xpath(".//span[contains(@class,'price')]/text()") or
                        post.xpath(".//*[contains(text(),'$')]/text()")
                    )
                    if price_elems:
                        try:
                            price_val = int(price_elems[0].replace("$", "").replace(",", "").strip())
                        except (ValueError, AttributeError):
                            price_val = None

                    if price_val and (price_val < min_price or price_val > max_price):
                        continue

                    title_lower = title.lower()
                    if not any(k in title_lower for k in keywords_lower):
                        continue

                    if not is_new_listing(link, seen_listings, SITE_NAME):
                        continue

                    normalized_link = normalize_url(link)
                    lock = get_seen_listings_lock(SITE_NAME)
                    with lock:
                        seen_listings[normalized_link] = datetime.now()

                    img_elem = post.xpath(".//img/@src") or post.xpath(".//img/@data-src")
                    image_url = None
                    if img_elem:
                        image_url = img_elem[0]
                        if image_url.startswith("//"):
                            image_url = f"https:{image_url}"
                        elif image_url and not image_url.startswith("http"):
                            image_url = urllib.parse.urljoin(BASE_URL, image_url)

                    send_discord_message(title, link, price_val, image_url)
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

                        if not is_new_listing(link, seen_listings, SITE_NAME):
                            continue

                        normalized_link = normalize_url(link)
                        with lock:
                            seen_listings[normalized_link] = datetime.now()

                        image_url = entry.get("image")
                        if isinstance(image_url, str):
                            if image_url.startswith("//"):
                                image_url = f"https:{image_url}"
                            elif image_url.startswith("/"):
                                image_url = urllib.parse.urljoin(BASE_URL, image_url)

                        send_discord_message(title, link, price_val, image_url)
                        results.append({"title": title, "link": link, "price": price_val, "image": image_url})
                    except Exception as e:
                        logger.warning(f"Error parsing KSL JSON-LD listing: {e}")

            if results:
                save_seen_listings(seen_listings, SITE_NAME)
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
    global seen_listings
    
    # Check for recursion
    if check_recursion_guard(SITE_NAME):
        return
    
    set_recursion_guard(SITE_NAME, True)
    
    try:
        logger.info("Starting KSL scraper")
        seen_listings = load_seen_listings(SITE_NAME)
        
        try:
            while running_flags.get(flag_name, True):
                try:
                    logger.debug("Running KSL scraper check")
                    results = check_ksl(flag_name)
                    if results:
                        logger.info(f"KSL scraper found {len(results)} new listings")
                    else:
                        logger.debug("KSL scraper found no new listings")
                except RecursionError as e:
                    print(f"ERROR: RecursionError in KSL scraper: {e}", file=sys.stderr, flush=True)
                    # Wait before retrying to avoid tight loop
                    import time
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
                
                settings = load_settings()
                human_delay(running_flags, flag_name, settings["interval"]*0.9, settings["interval"]*1.1)
                
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

