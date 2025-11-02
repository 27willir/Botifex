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
    get_seen_listings_lock
)
from scrapers.metrics import ScraperMetrics

# ======================
# CONFIGURATION
# ======================
SITE_NAME = "craigslist"
BASE_URL = "https://boise.craigslist.org"

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
        
        # Save to database with user_id
        save_listing(title, price, link, image_url, SITE_NAME, user_id=user_id)
        logger.info(f"📢 New Craigslist for {user_id}: {title} | ${price} | {link}")
    except Exception as e:
        logger.error(f"⚠️ Failed to save listing for {link}: {e}")

# ======================
# MAIN SCRAPER FUNCTION
# ======================
def check_craigslist(flag_name=SITE_NAME, user_id=None):
    settings = load_settings(username=user_id)
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
            try:
                location_coords = get_location_coords(location)
                if location_coords:
                    logger.debug(f"Craigslist: Searching {location} within {radius} miles")
                else:
                    logger.warning(f"Could not geocode location '{location}', using default coordinates")
                    # Use default coordinates for Boise, ID as fallback
                    location_coords = (43.6150, -116.2023)
            except Exception as e:
                logger.error(f"Error getting location coordinates for '{location}': {e}")
                # Use default coordinates for Boise, ID as fallback
                location_coords = (43.6150, -116.2023)
            
            # Build URL
            url = f"https://{location}.craigslist.org/search/sss"
            params = {"query": " ".join(keywords), "min_price": min_price, "max_price": max_price}
            full_url = url + "?" + urllib.parse.urlencode(params)

            # Get persistent session
            session = get_session(SITE_NAME, f"https://{location}.craigslist.org")
            
            # Make request with automatic retry and rate limit detection
            response = make_request_with_retry(full_url, SITE_NAME, session=session)
            
            if not response:
                metrics.error = "Failed to fetch page after retries"
                return []
            
            tree = html.fromstring(response.text)
            
            # Try multiple XPath patterns for robustness
            log_parse_attempt(SITE_NAME, 1, "cl-static-search-result class")
            posts = tree.xpath('//li[@class="cl-static-search-result"]')
            if not posts:
                log_parse_attempt(SITE_NAME, 2, "result-row class pattern")
                posts = tree.xpath('//li[contains(@class, "result-row")]')
            if not posts:
                log_parse_attempt(SITE_NAME, 3, "generic search-result class")
                posts = tree.xpath('//li[contains(@class, "search-result")]')
            
            if not posts:
                log_selector_failure(SITE_NAME, "xpath", "listing items", "posts")
                logger.warning(f"Craigslist: No posts found with any selector pattern")
                metrics.success = True  # Not an error, just no results
                metrics.listings_found = 0
                return []
            
            # Pre-compile title lower for keyword matching (outside loop)
            keywords_lower = [k.lower() for k in keywords]
            
            for post in posts:
                try:
                    # Combined XPath query for link and title (single pass)
                    # Try titlestring class first, then result-title, then any anchor
                    link = None
                    title = None
                    
                    # Method 1: titlestring class
                    anchor = post.xpath(".//a[@class='titlestring']")
                    if anchor:
                        link = anchor[0].get('href')
                        title = anchor[0].text_content().strip() if anchor[0].text_content() else None
                    
                    # Method 2: result-title class (fallback)
                    if not link:
                        anchor = post.xpath(".//a[contains(@class, 'result-title')]")
                        if anchor:
                            link = anchor[0].get('href')
                            title = anchor[0].text_content().strip() if anchor[0].text_content() else None
                    
                    # Method 3: Any anchor with href (last resort)
                    if not link:
                        anchor = post.xpath(".//a[@href]")
                        if anchor:
                            link = anchor[0].get('href')
                            title = anchor[0].text_content().strip() if anchor[0].text_content() else None
                    
                    if not link or not title:
                        continue
                    
                    # Extract and parse price (consolidated)
                    price_elem = post.xpath(".//span[contains(@class, 'price')]/text()")
                    price_val = None
                    if price_elem:
                        try:
                            price_val = int(price_elem[0].replace("$", "").replace(",", ""))
                        except (ValueError, IndexError):
                            pass
                    
                    # Early exit if price out of range
                    if price_val and (price_val < min_price or price_val > max_price):
                        continue
                    
                    # Check keywords (use pre-lowercased title)
                    title_lower = title.lower()
                    if not any(k in title_lower for k in keywords_lower):
                        continue
                    
                    # Check if new listing
                    if not is_new_listing(link, seen_listings, SITE_NAME):
                        continue
                    
                    # Update seen listings
                    normalized_link = normalize_url(link)
                    lock = get_seen_listings_lock(SITE_NAME)
                    with lock:
                        seen_listings[normalized_link] = datetime.now()
                    
                    # Extract image URL
                    image_url = None
                    img_elem = post.xpath(".//img/@src")
                    if img_elem:
                        image_url = img_elem[0]
                        # Make sure it's a full URL
                        if image_url and not image_url.startswith("http"):
                            image_url = "https://images.craigslist.org" + image_url
                    
                        send_discord_message(title, link, price_val, image_url, user_id=user_id)
                        results.append({"title": title, "link": link, "price": price_val, "image": image_url})
                except Exception as e:
                    logger.warning(f"Error parsing a Craigslist post: {e}")

            if results:
                save_seen_listings(seen_listings, SITE_NAME)
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
    global seen_listings
    
    # Check for recursion
    if check_recursion_guard(SITE_NAME):
        return
    
    set_recursion_guard(SITE_NAME, True)
    
    try:
        logger.info(f"Starting Craigslist scraper for user {user_id}")
        seen_listings = load_seen_listings(SITE_NAME)
        
        try:
            while running_flags.get(flag_name, True):
                try:
                    logger.debug(f"Running Craigslist scraper check for user {user_id}")
                    results = check_craigslist(flag_name, user_id=user_id)
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
                
                settings = load_settings()
                # Delay dynamically based on interval
                human_delay(running_flags, flag_name, settings["interval"]*0.9, settings["interval"]*1.1)
                
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
