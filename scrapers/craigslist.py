import random, time, json
import threading
import sys
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from pathlib import Path
import urllib.parse
from lxml import html
from utils import debug_scraper_output, logger
from db import get_settings, save_listing
from error_handling import ErrorHandler, log_errors, ScraperError, NetworkError
from location_utils import geocode_location, get_location_coords, miles_to_km

# Thread-local recursion protection for logging
_recursion_guard = threading.local()

# ======================
# CONFIGURATION
# ======================
craigslist_url = "https://boise.craigslist.org/search/sss?query=Firebird"

seen_listings = {}
_seen_listings_lock = threading.Lock()  # Thread safety for seen_listings

# ======================
# RUNNING FLAG
# ======================
running_flags = {"craigslist": True}

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

def save_seen_listings(filename="craigslist_seen.json"):
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

def load_seen_listings(filename="craigslist_seen.json"):
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
        save_listing(title, price, link, image_url, "craigslist")
        logger.info(f"📢 New Craigslist: {title} | ${price} | {link}")
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
def check_craigslist(flag_name="craigslist"):
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
    
    for attempt in range(max_retries):
        try:
            url = f"https://{location}.craigslist.org/search/sss"
            params = {"query": " ".join(keywords), "min_price": min_price, "max_price": max_price}
            full_url = url + "?" + urllib.parse.urlencode(params)

            response = requests.get(full_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
            response.raise_for_status()  # Raise exception for bad status codes
            tree = html.fromstring(response.text)
            break  # Success, exit retry loop
        except (requests.exceptions.RequestException, requests.exceptions.Timeout) as e:
            logger.warning(f"Craigslist request failed (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                # Exponential backoff: 2, 4, 8 seconds
                delay = base_retry_delay * (2 ** attempt)
                logger.info(f"Retrying in {delay} seconds...")
                time.sleep(delay)
                continue
            else:
                logger.error(f"Craigslist request failed after {max_retries} attempts: {e}")
                return []
        except Exception as e:
            logger.error(f"Unexpected error in Craigslist scraper: {e}")
            return []

    # Process the results if we successfully got the page
    try:
        # Try multiple XPath patterns for robustness
        posts = tree.xpath('//li[@class="cl-static-search-result"]')
        if not posts:
            # Fallback: try alternative class patterns
            posts = tree.xpath('//li[contains(@class, "result-row")]')
        if not posts:
            # Fallback: try generic result items
            posts = tree.xpath('//li[contains(@class, "search-result")]')
        
        for post in posts:
            try:
                # Try multiple ways to extract link
                link = None
                title = None
                
                # Method 1: titlestring class
                link_elems = post.xpath(".//a[@class='titlestring']/@href")
                if link_elems:
                    link = link_elems[0]
                    title_elems = post.xpath(".//a[@class='titlestring']/text()")
                    if title_elems:
                        title = title_elems[0].strip()
                
                # Method 2: result-title class (fallback)
                if not link:
                    link_elems = post.xpath(".//a[contains(@class, 'result-title')]/@href")
                    if link_elems:
                        link = link_elems[0]
                        title_elems = post.xpath(".//a[contains(@class, 'result-title')]/text()")
                        if title_elems:
                            title = title_elems[0].strip()
                
                # Method 3: Any anchor with href (last resort)
                if not link:
                    link_elems = post.xpath(".//a/@href")
                    if link_elems:
                        link = link_elems[0]
                        title_elems = post.xpath(".//a/text()")
                        if title_elems:
                            title = title_elems[0].strip()
                
                if not link or not title:
                    continue
                
                # Extract price with multiple patterns
                price = post.xpath(".//span[@class='price']/text()")
                if not price:
                    price = post.xpath(".//span[contains(@class, 'price')]/text()")
                
                price_val = int(price[0].replace("$", "").replace(",", "")) if price else None

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
                        if img_elem:
                            image_url = img_elem[0]
                            # Make sure it's a full URL
                            if image_url and not image_url.startswith("http"):
                                image_url = "https://images.craigslist.org" + image_url
                    except Exception as e:
                        logger.debug(f"Could not extract image for {link}: {e}")
                    
                    send_discord_message(title, link, price_val, image_url)
                    results.append({"title": title, "link": link, "price": price_val, "image": image_url})
            except Exception as e:
                logger.warning(f"Error parsing a Craigslist post: {e}")

        if results:
            save_seen_listings()
        else:
            logger.info(f"No new Craigslist listings. Next check in {check_interval}s...")

        debug_scraper_output("Craigslist", results)
        return results

    except Exception as e:
        logger.error(f"Error processing Craigslist results: {e}")
        return []

# ======================
# CONTINUOUS RUNNER
# ======================
def run_craigslist_scraper(flag_name="craigslist"):
    """Run scraper continuously until stopped via running_flags."""
    # Check for recursion
    if getattr(_recursion_guard, 'in_scraper', False):
        print("ERROR: Recursion detected in Craigslist scraper", file=sys.stderr)
        return
    
    _recursion_guard.in_scraper = True
    
    try:
        logger.info("Starting Craigslist scraper")
        load_seen_listings()
        
        try:
            while running_flags.get(flag_name, True):
                try:
                    logger.debug("Running Craigslist scraper check")
                    results = check_craigslist(flag_name)
                    if results:
                        logger.info(f"Craigslist scraper found {len(results)} new listings")
                    else:
                        logger.debug("Craigslist scraper found no new listings")
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
        _recursion_guard.in_scraper = False
