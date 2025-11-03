import sys
import threading
from datetime import datetime
import urllib.parse
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
    get_seen_listings_lock, extract_json_ld_items
)
from scrapers.metrics import ScraperMetrics

# ======================
# CONFIGURATION
# ======================
SITE_NAME = "ebay"
BASE_URL = "https://www.ebay.com"

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
        logger.info(f"📢 New eBay for {user_id}: {title} | ${price} | {link}")
    except Exception as e:
        logger.error(f"⚠️ Failed to save listing for {link}: {e}")

# ======================
# MAIN SCRAPER FUNCTION
# ======================
def check_ebay(flag_name=SITE_NAME, user_id=None):
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
            session = get_session(SITE_NAME, BASE_URL)
            
            # Make request with automatic retry and rate limit detection
            response = make_request_with_retry(full_url, SITE_NAME, session=session)
            
            if not response:
                metrics.error = "Failed to fetch page after retries"
                return []
            
            # Parse with BeautifulSoup for better HTML handling
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # eBay uses different HTML structures, try multiple patterns
            log_parse_attempt(SITE_NAME, 1, "s-item__wrapper divs")
            items = soup.find_all('div', class_='s-item__wrapper')
            if not items:
                log_parse_attempt(SITE_NAME, 2, "s-item list items")
                items = soup.find_all('li', class_='s-item')
            
            if not items:
                log_parse_attempt(SITE_NAME, 3, "generic s-item pattern")
                items = soup.find_all('div', attrs={'class': lambda x: x and 's-item' in x if x else False})
            
            if not items:
                log_selector_failure(SITE_NAME, "class", "s-item patterns", "listing items")
                logger.warning(f"eBay: No items found with any selector pattern")
                metrics.success = True  # Not an error, just no results
                metrics.listings_found = 0
                return []
            
            logger.debug(f"Found {len(items)} eBay items via HTML selectors")
            
            # Pre-compile keywords for faster matching and prep seen listings lock
            keywords_lower = [k.lower() for k in keywords]
            seen_lock = get_seen_listings_lock(SITE_NAME)

            def handle_candidate(title, link, price_val, image_url=None, description=None):
                """Apply shared filtering/notification logic for a listing candidate."""

                if not title or not link:
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

                if not is_new_listing(link, seen_listings, SITE_NAME):
                    return

                normalized_link = normalize_url(link)
                with seen_lock:
                    seen_listings[normalized_link] = datetime.now()

                send_discord_message(title, link, normalized_price, image_url, user_id=user_id)
                results.append({
                    "title": title,
                    "link": link,
                    "price": normalized_price,
                    "image": image_url
                })

            json_ld_items = []
            if not items:
                log_parse_attempt(SITE_NAME, 4, "JSON-LD itemListElement fallback")
                json_ld_items = extract_json_ld_items(response.text)
                if not json_ld_items:
                    log_selector_failure(SITE_NAME, "json-ld", "itemListElement", "listing items")
                    logger.warning(f"eBay: No items found with HTML or JSON-LD selectors")
                    metrics.success = True
                    metrics.listings_found = 0
                    return []
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

                        link = urllib.parse.urljoin(BASE_URL, link_elem['href'])
                        if '?' in link:
                            link = link.split('?', 1)[0]

                        price_val = None
                        price_elem = (
                            item.find('span', class_='s-item__price') or
                            item.find('span', attrs={'class': lambda x: x and 'price' in x.lower() if x else False})
                        )
                        if price_elem:
                            price_text = price_elem.get_text(strip=True)
                            if price_text:
                                price_clean = price_text.replace('$', '').replace(',', '').strip()
                                if ' to ' in price_clean:
                                    price_clean = price_clean.split(' to ', 1)[0].strip()
                                try:
                                    price_val = int(float(price_clean))
                                except (ValueError, TypeError):
                                    price_val = None

                        image_url = None
                        img_elem = item.find('img', class_='s-item__image-img') or item.find('img')
                        if img_elem:
                            image_url = img_elem.get('src') or img_elem.get('data-src')
                            if image_url and image_url.startswith('//'):
                                image_url = f"https:{image_url}"
                            if image_url and image_url.startswith('http'):
                                if any(token in image_url for token in ('s-l64', 's-l50', 'data:')):
                                    image_url = img_elem.get('data-src') or image_url
                                    if image_url and image_url.startswith('//'):
                                        image_url = f"https:{image_url}"

                        handle_candidate(title, link, price_val, image_url)
                    except Exception as e:
                        logger.warning(f"Error parsing an eBay listing: {e}")
                        continue
            else:
                for entry in json_ld_items:
                    try:
                        title = entry.get("title")
                        link = entry.get("url")
                        if link:
                            link = urllib.parse.urljoin(BASE_URL, link)
                            if '?' in link:
                                link = link.split('?', 1)[0]

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
                save_seen_listings(seen_listings, SITE_NAME)
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
    global seen_listings
    
    # Check for recursion
    if check_recursion_guard(SITE_NAME):
        return
    
    set_recursion_guard(SITE_NAME, True)
    
    try:
        logger.info(f"Starting eBay scraper for user {user_id}")
        seen_listings = load_seen_listings(SITE_NAME)
        
        try:
            while running_flags.get(flag_name, True):
                try:
                    logger.debug(f"Running eBay scraper check for user {user_id}")
                    results = check_ebay(flag_name, user_id=user_id)
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
                
                settings = load_settings()
                # Delay dynamically based on interval
                human_delay(running_flags, flag_name, settings["interval"]*0.9, settings["interval"]*1.1)
                
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

