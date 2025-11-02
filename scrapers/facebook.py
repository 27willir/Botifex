import random, re, time, json
import urllib.parse
import threading
from datetime import datetime
from lxml import html
from selenium.webdriver.common.by import By
from utils import debug_scraper_output, logger
from db import get_settings, save_listing
from error_handling import ErrorHandler, log_errors, ScraperError, NetworkError
from location_utils import geocode_location, get_location_coords, miles_to_km

# ======================
# CONFIGURATION
# ======================
# Facebook Marketplace Location IDs for common cities (fallback)
LOCATION_IDS = {
    "boise": "108420222512131",
    "salt lake city": "108659242498155",
    "portland": "108423525857649",
    "seattle": "108092845880969",
    "phoenix": "108124175896772",
    "los angeles": "108424279189115",
    "las vegas": "108118525888573",
    "denver": "108427449197415",
    "san francisco": "108659242498155",
    "sacramento": "108108715896878",
}

seen_listings = {}
_seen_listings_lock = threading.Lock()  # Thread safety for seen_listings

# ======================
# RECURSION GUARD
# ======================
_recursion_guard = threading.local()

# ======================
# RUNNING FLAG
# ======================
running_flags = {"facebook": True}

# ======================
# HELPER FUNCTIONS
# ======================
def human_delay(flag_dict, flag_name, min_sec=1.5, max_sec=4.5):
    """Pause between requests with human-like randomness, respecting stop flags."""
    total = random.uniform(min_sec, max_sec)
    step = 0.25  # smaller step for faster stop response
    while total > 0 and flag_dict.get(flag_name, True):
        sleep_time = min(step, total)
        time.sleep(sleep_time)
        total -= sleep_time

def human_scroll(driver, flag_dict, flag_name, min_scrolls=1, max_scrolls=3):
    """Simulate human scrolling behavior, stopping if flag is cleared."""
    for _ in range(random.randint(min_scrolls, max_scrolls)):
        if not flag_dict.get(flag_name, True):
            break
        driver.execute_script("window.scrollBy(0, 600);")
        human_delay(flag_dict, flag_name, min_sec=1, max_sec=2)

def normalize_url(url):
    """Normalize URL by removing query parameters and fragments for comparison."""
    if not url:
        return None
    try:
        # Remove query parameters and fragments
        parsed = urllib.parse.urlparse(url)
        normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        return normalized.rstrip('/')
    except Exception as e:
        logger.debug(f"Error normalizing URL {url}: {e}")
        return url

def is_new_listing(link):
    """Check if a listing has been seen within the last 24 hours."""
    normalized_link = normalize_url(link)
    if not normalized_link:
        # If URL normalization failed, treat as new to attempt processing
        logger.debug(f"URL normalization failed for {link}, treating as new")
        return True
    
    with _seen_listings_lock:
        if normalized_link not in seen_listings:
            return True
        last_seen = seen_listings[normalized_link]
        return (datetime.now() - last_seen).total_seconds() > 86400

def save_seen_listings(filename="facebook_seen.json"):
    """Save seen listings to JSON."""
    try:
        with _seen_listings_lock:
            with open(filename, "w") as f:
                json.dump({k: v.isoformat() for k, v in seen_listings.items()}, f, indent=2)
        logger.debug(f"Saved seen listings to {filename}")
    except (OSError, PermissionError) as e:
        logger.error(f"File system error saving seen listings: {e}")
    except Exception as e:
        logger.error(f"Failed to save seen listings: {e}")

def load_seen_listings(filename="facebook_seen.json"):
    """Load previously seen listings from JSON."""
    global seen_listings
    try:
        with open(filename, "r") as f:
            data = json.load(f)
        with _seen_listings_lock:
            seen_listings = {k: datetime.fromisoformat(v) for k, v in data.items()}
        logger.debug(f"Loaded {len(seen_listings)} seen listings from {filename}")
    except FileNotFoundError:
        logger.info(f"Seen listings file not found: {filename}, starting fresh")
        with _seen_listings_lock:
            seen_listings = {}
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"Invalid JSON in seen listings file: {e}")
        with _seen_listings_lock:
            seen_listings = {}
    except Exception as e:
        logger.error(f"Failed to load seen listings: {e}")
        with _seen_listings_lock:
            seen_listings = {}

def validate_listing(title, link, price=None):
    """Validate listing data before saving."""
    if not title or not isinstance(title, str) or len(title.strip()) == 0:
        return False, "Invalid or empty title"
    
    if not link or not isinstance(link, str) or not link.startswith("http"):
        return False, "Invalid or missing link"
    
    if price is not None and (not isinstance(price, (int, float)) or price < 0):
        return False, "Invalid price"
    
    return True, None

def send_discord_message(title, link, price=None, image_url=None):
    """Save listing to database and send notification."""
    try:
        # Validate data before saving
        is_valid, error = validate_listing(title, link, price)
        if not is_valid:
            logger.warning(f"⚠️ Skipping invalid listing: {error}")
            return
        
        # Save to database
        ErrorHandler.handle_database_error(save_listing, title, price, link, image_url, "facebook")
        logger.info(f"📢 New Facebook Listing: {title} | ${price} | {link}")
    except Exception as e:
        logger.error(f"Failed to save Facebook listing for {link}: {e}")

def load_settings():
    """Load settings from database"""
    try:
        settings = get_settings()  # Get global settings
        return {
            "keywords": [k.strip() for k in settings.get("keywords","Firebird,Camaro,Corvette").split(",") if k.strip()],
            "min_price": int(settings.get("min_price", 1000)),
            "max_price": int(settings.get("max_price", 30000)),
            "interval": int(settings.get("interval", 60)),
            "location": settings.get("location", "boise"),
            "radius": int(settings.get("radius", 50))
        }
    except Exception as e:
        logger.error(f"⚠️ Failed to load settings: {e}")
        return {
            "keywords": ["Firebird","Camaro","Corvette"],
            "min_price": 1000,
            "max_price": 30000,
            "interval": 60,
            "location": "boise",
            "radius": 50
        }

# ======================
# DYNAMIC FACEBOOK URL
# ======================
def get_facebook_url(settings):
    """
    Build the Marketplace URL based on current settings.
    Uses geocoding to support any city worldwide.
    Falls back to location IDs if geocoding fails.
    """
    location = settings.get("location", "boise").strip()
    location_lower = location.lower()
    
    # Convert radius from miles to kilometers (Facebook uses km)
    radius_miles = settings.get("radius", 50)
    radius_km = int(radius_miles * 1.60934)  # Miles to km conversion
    
    # Get keywords for search query
    keywords = settings.get("keywords", ["Firebird", "Camaro", "Corvette"])
    query = " ".join(keywords) if isinstance(keywords, list) else keywords
    
    # Try geocoding first for coordinates-based search
    try:
        coords = geocode_location(location)
    except Exception as e:
        logger.error(f"Error geocoding location '{location}': {e}")
        coords = None
    
    if coords:
        # Use coordinates-based URL (works for any location)
        lat, lon = coords
        base_url = "https://www.facebook.com/marketplace/category/vehicles"
        params = []
        if query:
            params.append(f"query={urllib.parse.quote(query)}")
        # Add location parameters
        params.append(f"minPrice=0")
        params.append(f"maxPrice=999999")
        params.append(f"latitude={lat}")
        params.append(f"longitude={lon}")
        params.append(f"radius={radius_km}")
        
        return f"{base_url}?{'&'.join(params)}"
    
    else:
        # Fallback to location ID method for known cities
        location_id = LOCATION_IDS.get(location_lower, LOCATION_IDS["boise"])
        base_url = f"https://www.facebook.com/marketplace/{location_id}/"
        
        params = []
        if query:
            params.append(f"query={urllib.parse.quote(query)}")
        params.append(f"radius={radius_km}")
        
        if params:
            return f"{base_url}?{'&'.join(params)}"
        
        return base_url

# ======================
# MAIN SCRAPER FUNCTION
# ======================
def check_facebook(driver):
    try:
        settings = ErrorHandler.handle_database_error(load_settings)
        keywords = settings["keywords"]
        min_price = settings["min_price"]
        max_price = settings["max_price"]
        check_interval = settings["interval"]
        location = settings.get("location", "boise")
        radius = settings.get("radius", 50)

        url = get_facebook_url(settings)  # dynamically generate URL
        logger.debug(f"Facebook Marketplace: searching {location} within {radius} miles")

        # Navigate to page with network error handling
        ErrorHandler.handle_network_error(lambda: driver.get(url))
        human_delay(running_flags, "facebook", min_sec=3, max_sec=6)
        human_scroll(driver, running_flags, "facebook")

        tree = html.fromstring(driver.page_source)
        # Pre-filter anchors efficiently
        anchors = [a for a in tree.xpath("//a[@href]") if isinstance(a.get("href"), str)]

        # Pre-compile price pattern outside loop
        price_pattern = re.compile(r"\$\s?([\d,]+)")
        
        # Pre-compile keywords for faster matching
        keywords_lower = [k.lower() for k in keywords]
        
        # Pre-compile filter patterns for image validation
        bad_img_patterns = {"icon", "logo", "placeholder", "blank"}

        new_links = []
        for a in anchors:
            try:
                link = a.get("href").split("?", 1)[0].strip()
                title = (a.text_content() or "").strip()

                if not title or not link:
                    continue

                # Extract price from title (using pre-compiled pattern)
                price = None
                price_match = price_pattern.search(title)
                if price_match:
                    try:
                        price = int(price_match.group(1).replace(",", ""))
                    except (ValueError, AttributeError):
                        pass

                # Early exit if price out of range
                if price is not None and (price < min_price or price > max_price):
                    continue

                # Check keywords (use pre-lowercased)
                title_lower = title.lower()
                if not any(k in title_lower for k in keywords_lower):
                    continue
                
                # Check if new listing
                if not is_new_listing(link):
                    continue

                # Update seen listings
                normalized_link = normalize_url(link)
                with _seen_listings_lock:
                    seen_listings[normalized_link] = datetime.now()

                # Attempt to get image URL (simplified and optimized)
                image_url = None
                try:
                    # Method 1: Find images within the parent link element
                    parent_link = driver.find_element(By.XPATH, f"//a[@href='{link}']")
                    images = parent_link.find_elements(By.TAG_NAME, "img")
                    for img in images:
                        src = img.get_attribute("src")
                        # Fast filter check
                        if src and src.startswith("https://"):
                            src_lower = src.lower()
                            if not any(pattern in src_lower for pattern in bad_img_patterns):
                                image_url = src
                                break
                    
                    # Method 2: Marketplace-specific images (if method 1 failed)
                    if not image_url:
                        imgs = driver.find_elements(By.CSS_SELECTOR, "img[data-imgperflogname='marketplace_search_result_image']")
                        if imgs:
                            image_url = imgs[0].get_attribute("src")
                    
                    # Method 3: High-quality CDN images (if method 2 failed)
                    if not image_url:
                        all_imgs = driver.find_elements(By.TAG_NAME, "img")
                        for img in all_imgs[:10]:  # Check first 10 only
                            src = img.get_attribute("src")
                            if src and "scontent" in src and src.startswith("https://"):
                                image_url = src
                                break
                except Exception:
                    pass  # Silently ignore image extraction errors

                send_discord_message(title, link, price, image_url)
                new_links.append(link)
            except Exception as e:
                logger.warning(f"Error processing Facebook listing: {e}")
                continue

        if new_links:
            save_seen_listings()
        else:
            logger.debug(f"No new Facebook listings. Next check in {check_interval}s...")

        debug_scraper_output("Facebook", new_links)
        return new_links

    except NetworkError as e:
        logger.error(f"Network error scraping Facebook: {e}")
        return []
    except ScraperError as e:
        logger.error(f"Scraper error on Facebook: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error scraping Facebook: {e}")
        return []

# ======================
# CONTINUOUS RUNNER
# ======================
def run_facebook_scraper(driver, flag_name="facebook", user_id=None):
    """Run Facebook scraper with proper error handling and timeout protection."""
    # Check for recursion
    if getattr(_recursion_guard, 'in_scraper', False):
        import sys
        print("ERROR: Recursion detected in Facebook scraper", file=sys.stderr, flush=True)
        return
    
    _recursion_guard.in_scraper = True
    
    try:
        load_seen_listings()
        logger.info("Starting Facebook scraper")
        
        try:
            while running_flags.get(flag_name, True):
                try:
                    check_facebook(driver)
                except RecursionError as e:
                    import sys
                    print(f"ERROR: RecursionError in Facebook scraper: {e}", file=sys.stderr, flush=True)
                    # Wait before retrying to avoid tight loop
                    time.sleep(10)
                    continue
                except NetworkError as e:
                    try:
                        logger.error(f"Network error in Facebook scraper iteration: {e}")
                    except:
                        import sys
                        print(f"ERROR: Network error in Facebook scraper iteration: {e}", file=sys.stderr, flush=True)
                    # Wait longer before retry on network errors
                    human_delay(running_flags, flag_name, 30, 60)
                    continue
                except ScraperError as e:
                    try:
                        logger.error(f"Scraper error in Facebook iteration: {e}")
                    except:
                        import sys
                        print(f"ERROR: Scraper error in Facebook iteration: {e}", file=sys.stderr, flush=True)
                    # Continue running but log the error
                    continue
                except Exception as e:
                    try:
                        logger.error(f"Unexpected error in Facebook scraper iteration: {e}")
                    except:
                        import sys
                        print(f"ERROR: Unexpected error in Facebook scraper iteration: {e}", file=sys.stderr, flush=True)
                    continue
                
                try:
                    settings = ErrorHandler.handle_database_error(load_settings)
                    human_delay(running_flags, flag_name, settings["interval"]*0.9, settings["interval"]*1.1)
                except Exception as e:
                    try:
                        logger.error(f"Error in Facebook scraper delay: {e}")
                    except:
                        import sys
                        print(f"ERROR: Error in Facebook scraper delay: {e}", file=sys.stderr, flush=True)
                    # Use default delay if settings fail
                    human_delay(running_flags, flag_name, 60, 90)
                
        except KeyboardInterrupt:
            logger.info("🛑 Facebook scraper interrupted by user")
        except RecursionError as e:
            import sys
            print(f"FATAL: RecursionError in Facebook scraper main loop: {e}", file=sys.stderr, flush=True)
        except Exception as e:
            try:
                logger.error(f"❌ Fatal error in Facebook scraper: {e}")
            except:
                import sys
                print(f"ERROR: Fatal error in Facebook scraper: {e}", file=sys.stderr, flush=True)
        finally:
            logger.info("🛑 Facebook scraper stopped")
    finally:
        _recursion_guard.in_scraper = False
