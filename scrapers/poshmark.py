import random, time, json
import threading
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

# ======================
# CONFIGURATION
# ======================
poshmark_url = "https://poshmark.com"

seen_listings = {}
_seen_listings_lock = threading.Lock()  # Thread safety for seen_listings

# ======================
# RECURSION GUARD
# ======================
_recursion_guard = threading.local()

# ======================
# RUNNING FLAG
# ======================
running_flags = {"poshmark": True}

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
        # This prevents valid listings from being silently skipped
        logger.debug(f"URL normalization failed for {link}, treating as new")
        return True
    
    with _seen_listings_lock:
        if normalized_link not in seen_listings:
            return True
        last_seen = seen_listings[normalized_link]
        return (datetime.now() - last_seen).total_seconds() > 86400

def save_seen_listings(filename="poshmark_seen.json"):
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

def load_seen_listings(filename="poshmark_seen.json"):
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

def send_discord_message(title, link, price=None, image_url=None, user_id=None):
    """Save listing to database and send notification."""
    try:
        # Validate data before saving
        is_valid, error = validate_listing(title, link, price)
        if not is_valid:
            logger.warning(f"⚠️ Skipping invalid listing: {error}")
            return
        
        # Save to database with user_id
        save_listing(title, price, link, image_url, "poshmark", user_id=user_id)
        logger.info(f"📢 New Poshmark for {user_id}: {title} | ${price} | {link}")
    except Exception as e:
        logger.error(f"⚠️ Failed to save listing for {link}: {e}")

def load_settings(username=None):
    """Load settings from database"""
    try:
        settings = get_settings(username=username)  # Get user-specific or global settings
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
def check_poshmark(flag_name="poshmark", user_id=None):
    settings = load_settings(username=user_id)
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
        logger.debug(f"Poshmark: Searching {location} within {radius} miles")
    else:
        logger.warning(f"Could not geocode location '{location}', using default")
    
    for attempt in range(max_retries):
        try:
            # Build Poshmark search URL
            # Poshmark uses /search for search queries
            base_url = "https://poshmark.com/search"
            
            # Join keywords with spaces for search
            query = " ".join(keywords)
            
            # Build URL with parameters
            params = {
                "query": query,
                "type": "listings",
                "department": "All",
                "min_price": min_price,
                "max_price": max_price,
                "sort_by": "newest_first"  # Sort by newest first
            }
            
            # Add location filtering if coordinates available
            if location_coords:
                lat, lon = location_coords
                radius_km = int(miles_to_km(radius))
                params["latitude"] = lat
                params["longitude"] = lon
                params["distance"] = radius_km
            
            full_url = base_url + "?" + urllib.parse.urlencode(params)

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Referer": "https://poshmark.com/",
                "Origin": "https://poshmark.com"
            }

            response = requests.get(full_url, headers=headers, timeout=30)
            response.raise_for_status()  # Raise exception for bad status codes
            
            # Parse with BeautifulSoup for better HTML handling
            soup = BeautifulSoup(response.text, 'html.parser')
            break  # Success, exit retry loop
        except (requests.exceptions.RequestException, requests.exceptions.Timeout) as e:
            logger.warning(f"Poshmark request failed (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                # Exponential backoff: 2, 4, 8 seconds
                delay = base_retry_delay * (2 ** attempt)
                logger.info(f"Retrying in {delay} seconds...")
                time.sleep(delay)
                continue
            else:
                logger.error(f"Poshmark request failed after {max_retries} attempts: {e}")
                return []
        except Exception as e:
            logger.error(f"Unexpected error in Poshmark scraper: {e}")
            return []

    # Process the results if we successfully got the page
    try:
        # Try to find listing items (consolidated selectors)
        items = (soup.find_all('div', class_='tile') or 
                soup.find_all('div', attrs={'class': lambda x: x and 'listing' in x.lower() if x else False}) or 
                soup.find_all('div', attrs={'class': lambda x: x and 'item' in x.lower() if x else False}))
        
        logger.debug(f"Found {len(items)} Poshmark items to process")
        
        # Pre-compile keywords for faster matching
        keywords_lower = [k.lower() for k in keywords]
        
        for item in items:
            try:
                # Extract title (consolidated selector)
                title_elem = (item.find('a', class_='title') or 
                             item.find('div', class_='title') or 
                             item.find('h3') or 
                             item.find('a', href=True))
                
                if not title_elem:
                    continue
                
                title = title_elem.get_text(strip=True)
                if not title:
                    continue
                
                # Extract link
                link_elem = item.find('a', href=True)
                if not link_elem:
                    continue
                
                link = link_elem.get('href')
                if not link:
                    continue
                
                # Make sure link is absolute (fast path check)
                if link.startswith('/'):
                    link = "https://poshmark.com" + link
                
                # Extract and parse price (consolidated)
                price_elem = item.find('span', class_='price') or item.find('div', class_='price')
                
                price_val = None
                if price_elem:
                    price_text = price_elem.get_text(strip=True)
                    try:
                        # Handle price formats efficiently
                        price_clean = price_text.replace('$', '').replace(',', '').strip()
                        price_val = int(float(price_clean))
                    except (ValueError, AttributeError):
                        pass
                
                # Early exit if price out of range
                if price_val and (price_val < min_price or price_val > max_price):
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
                
                # Extract image URL
                image_url = None
                img_elem = item.find('img')
                if img_elem:
                    image_url = img_elem.get('src') or img_elem.get('data-src')
                    # Make sure it's a full URL (fast path checks)
                    if image_url:
                        if not image_url.startswith("http"):
                            if image_url.startswith('//'):
                                image_url = 'https:' + image_url
                            elif image_url.startswith('/'):
                                image_url = "https://poshmark.com" + image_url
                
                send_discord_message(title, link, price_val, image_url, user_id=user_id)
                results.append({"title": title, "link": link, "price": price_val, "image": image_url})
            except Exception as e:
                logger.warning(f"Error parsing a Poshmark listing: {e}")
                continue

        if results:
            save_seen_listings()
        else:
            logger.info(f"No new Poshmark listings. Next check in {check_interval}s...")

        debug_scraper_output("Poshmark", results)
        return results

    except Exception as e:
        logger.error(f"Error processing Poshmark results: {e}")
        return []

# ======================
# CONTINUOUS RUNNER
# ======================
def run_poshmark_scraper(flag_name="poshmark", user_id=None):
    """Run scraper continuously until stopped via running_flags."""
    # Check for recursion
    if getattr(_recursion_guard, 'in_scraper', False):
        import sys
        print("ERROR: Recursion detected in Poshmark scraper", file=sys.stderr, flush=True)
        return
    
    _recursion_guard.in_scraper = True
    
    try:
        logger.info(f"Starting Poshmark scraper for user {user_id}")
        load_seen_listings()
        
        try:
            while running_flags.get(flag_name, True):
                try:
                    logger.debug(f"Running Poshmark scraper check for user {user_id}")
                    results = check_poshmark(flag_name, user_id=user_id)
                    if results:
                        logger.info(f"Poshmark scraper found {len(results)} new listings for user {user_id}")
                    else:
                        logger.debug(f"Poshmark scraper found no new listings for user {user_id}")
                except RecursionError as e:
                    import sys
                    print(f"ERROR: RecursionError in Poshmark scraper: {e}", file=sys.stderr, flush=True)
                    # Wait before retrying to avoid tight loop
                    time.sleep(10)
                    continue
                except Exception as e:
                    # Use fallback logging to avoid recursion in error handling
                    try:
                        logger.error(f"Error in Poshmark scraper iteration: {e}")
                    except:
                        import sys
                        print(f"ERROR: Error in Poshmark scraper iteration: {e}", file=sys.stderr, flush=True)
                    # Continue running but log the error
                    continue
                
                settings = load_settings()
                # Delay dynamically based on interval
                human_delay(running_flags, flag_name, settings["interval"]*0.9, settings["interval"]*1.1)
                
        except KeyboardInterrupt:
            logger.info("Poshmark scraper interrupted by user")
        except RecursionError as e:
            import sys
            print(f"FATAL: RecursionError in Poshmark scraper main loop: {e}", file=sys.stderr, flush=True)
        except Exception as e:
            try:
                logger.error(f"Fatal error in Poshmark scraper: {e}")
            except:
                import sys
                print(f"ERROR: Fatal error in Poshmark scraper: {e}", file=sys.stderr, flush=True)
        finally:
            logger.info("Poshmark scraper stopped")
    finally:
        _recursion_guard.in_scraper = False

