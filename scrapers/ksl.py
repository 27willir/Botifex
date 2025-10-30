import random, re, time, json
import threading
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import urllib.parse
from pathlib import Path
from lxml import html
from utils import debug_scraper_output, logger
from db import get_settings, save_listing
from error_handling import ErrorHandler, log_errors, ScraperError, NetworkError
from location_utils import geocode_location, get_location_coords, miles_to_km

# ======================
# CONFIGURATION
# ======================
ksl_url = "https://classifieds.ksl.com/search"
seen_listings = {}
_seen_listings_lock = threading.Lock()  # Thread safety for seen_listings

# ======================
# RECURSION GUARD
# ======================
_recursion_guard = threading.local()

# ======================
# RUNNING FLAG
# ======================
running_flags = {"ksl": True}

# ======================
# HELPER FUNCTIONS
# ======================
def human_delay(flag_dict, flag_name, min_sec=1.5, max_sec=4.5):
    total = random.uniform(min_sec, max_sec)
    step = 0.25
    while total > 0 and flag_dict.get(flag_name, True):
        sleep_time = min(step, total)
        time.sleep(sleep_time)
        total -= sleep_time

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
    """Return True if this listing is new or last seen more than 24h ago."""
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

def save_seen_listings(filename="ksl_seen.json"):
    """Save seen listings with timestamps to JSON."""
    try:
        with _seen_listings_lock:
            Path(filename).write_text(
                json.dumps({k: v.isoformat() for k, v in seen_listings.items()}, indent=2),
                encoding="utf-8"
            )
        logger.debug(f"Saved seen listings to {filename}")
    except (OSError, PermissionError) as e:
        logger.error(f"File system error saving seen listings: {e}")
    except Exception as e:
        logger.error(f"Error saving seen listings: {e}")

def load_seen_listings(filename="ksl_seen.json"):
    """Load seen listings from JSON, if available."""
    global seen_listings
    try:
        text = Path(filename).read_text(encoding="utf-8")
        data = json.loads(text) if text else {}
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
        logger.error(f"Error loading seen listings: {e}")
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
        save_listing(title, price, link, image_url, "ksl")
        logger.info(f"📢 New KSL: {title} | ${price} | {link}")
    except Exception as e:
        logger.error(f"⚠️ Failed to save listing for {link}: {e}")

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
# MAIN SCRAPER FUNCTION
# ======================
def check_ksl(flag_name="ksl"):
    settings = load_settings()
    keywords = settings["keywords"]
    min_price = settings["min_price"]
    max_price = settings["max_price"]
    check_interval = settings["interval"]
    location = settings.get("location", "boise")
    radius = settings.get("radius", 50)

    results = []
    max_retries = 3
    base_retry_delay = 2
    
    # Get location coordinates for distance filtering
    location_coords = get_location_coords(location)
    if location_coords:
        logger.debug(f"KSL: Searching {location} within {radius} miles")
    else:
        logger.warning(f"Could not geocode location '{location}', using default")
    
    for attempt in range(max_retries):
        try:
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

            response = requests.get(full_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
            response.raise_for_status()  # Raise exception for bad status codes
            tree = html.fromstring(response.text)
            break  # Success, exit retry loop
        except (requests.exceptions.RequestException, requests.exceptions.Timeout) as e:
            logger.warning(f"KSL request failed (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                # Exponential backoff: 2, 4, 8 seconds
                delay = base_retry_delay * (2 ** attempt)
                logger.info(f"Retrying in {delay} seconds...")
                time.sleep(delay)
                continue
            else:
                logger.error(f"KSL request failed after {max_retries} attempts: {e}")
                return []
        except Exception as e:
            logger.error(f"Unexpected error in KSL scraper: {e}")
            return []

    # Process the results if we successfully got the page
    try:
        # Try multiple XPath patterns for robustness
        posts = tree.xpath('//section[contains(@class,"listing")]')
        if not posts:
            # Fallback: try alternative patterns
            posts = tree.xpath('//div[contains(@class,"listing-item")]')
        if not posts:
            # Fallback: try article elements
            posts = tree.xpath('//article[contains(@class,"listing")]')
        
        for post in posts:
            try:
                # Try multiple ways to extract link
                link = None
                link_elems = post.xpath(".//a[@class='listing-item-link']/@href")
                if link_elems:
                    link = link_elems[0]
                elif post.xpath(".//a[contains(@class,'listing')]/@href"):
                    link = post.xpath(".//a[contains(@class,'listing')]/@href")[0]
                elif post.xpath(".//a/@href"):
                    # Last resort: any link
                    link = post.xpath(".//a/@href")[0]
                
                if not link:
                    continue
                    
                # Make sure it's a full URL
                if not link.startswith("http"):
                    link = "https://classifieds.ksl.com" + link
                
                # Try multiple ways to extract title
                title = None
                title_elems = post.xpath(".//h2/text()")
                if title_elems:
                    title = title_elems[0].strip()
                elif post.xpath(".//h3/text()"):
                    # Sometimes h3 might be title
                    title = post.xpath(".//h3/text()")[0].strip()
                elif post.xpath(".//div[contains(@class,'title')]/text()"):
                    title = post.xpath(".//div[contains(@class,'title')]/text()")[0].strip()
                
                if not title:
                    continue
                
                # Try multiple ways to extract price
                price = post.xpath(".//h3/text()")
                if not price:
                    price = post.xpath(".//span[contains(@class,'price')]/text()")
                if not price:
                    price = post.xpath(".//*[contains(text(),'$')]/text()")
                
                price_val = None
                if price:
                    try:
                        price_val = int(price[0].replace("$", "").replace(",", "").strip())
                    except (ValueError, AttributeError):
                        pass

                if price_val and (price_val < min_price or price_val > max_price):
                    continue

                if any(k.lower() in title.lower() for k in keywords) and is_new_listing(link):
                    normalized_link = normalize_url(link)
                    with _seen_listings_lock:
                        seen_listings[normalized_link] = datetime.now()
                    
                    # Extract image URL
                    image_url = None
                    try:
                        # Try to get the image from the listing
                        img_elem = post.xpath(".//img/@src")
                        if not img_elem:
                            # Try data-src attribute (lazy loading)
                            img_elem = post.xpath(".//img/@data-src")
                        
                        if img_elem:
                            image_url = img_elem[0]
                            # Make sure it's a full URL
                            if image_url and not image_url.startswith("http"):
                                image_url = "https://img.ksl.com" + image_url
                    except Exception as e:
                        logger.debug(f"Could not extract image for {link}: {e}")
                    
                    send_discord_message(title, link, price_val, image_url)
                    results.append({"title": title, "link": link, "price": price_val, "image": image_url})
            except Exception as e:
                logger.warning(f"Error parsing a KSL post: {e}")

        if results:
            save_seen_listings()
        else:
            logger.info(f"No new KSL listings. Next check in {check_interval}s...")

        debug_scraper_output("KSL", results)
        return results

    except Exception as e:
        logger.error(f"Error processing KSL results: {e}")
        return []

# ======================
# CONTINUOUS RUNNER
# ======================
def run_ksl_scraper(flag_name="ksl"):
    """Run KSL scraper with proper error handling."""
    # Check for recursion
    if getattr(_recursion_guard, 'in_scraper', False):
        import sys
        print("ERROR: Recursion detected in KSL scraper", file=sys.stderr, flush=True)
        return
    
    _recursion_guard.in_scraper = True
    
    try:
        logger.info("Starting KSL scraper")
        load_seen_listings()
        
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
                    import sys
                    print(f"ERROR: RecursionError in KSL scraper: {e}", file=sys.stderr, flush=True)
                    # Wait before retrying to avoid tight loop
                    time.sleep(10)
                    continue
                except Exception as e:
                    # Use fallback logging to avoid recursion in error handling
                    try:
                        logger.error(f"Error in KSL scraper iteration: {e}")
                    except:
                        import sys
                        print(f"ERROR: Error in KSL scraper iteration: {e}", file=sys.stderr, flush=True)
                    # Continue running but log the error
                    continue
                
                settings = load_settings()
                human_delay(running_flags, flag_name, settings["interval"]*0.9, settings["interval"]*1.1)
                
        except KeyboardInterrupt:
            logger.info("KSL scraper interrupted by user")
        except RecursionError as e:
            import sys
            print(f"FATAL: RecursionError in KSL scraper main loop: {e}", file=sys.stderr, flush=True)
        except Exception as e:
            try:
                logger.error(f"Fatal error in KSL scraper: {e}")
            except:
                import sys
                print(f"ERROR: Fatal error in KSL scraper: {e}", file=sys.stderr, flush=True)
        finally:
            logger.info("KSL scraper stopped")
    finally:
        _recursion_guard.in_scraper = False
