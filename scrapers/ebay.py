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
ebay_url = "https://www.ebay.com/sch/i.html"

seen_listings = {}
_seen_listings_lock = threading.Lock()  # Thread safety for seen_listings

# ======================
# RUNNING FLAG
# ======================
running_flags = {"ebay": True}

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

@log_errors()
def save_seen_listings(filename="ebay_seen.json"):
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
        raise
    except Exception as e:
        logger.error(f"Error saving seen listings: {e}")
        raise

@log_errors()
def load_seen_listings(filename="ebay_seen.json"):
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
        save_listing(title, price, link, image_url, "ebay")
        logger.info(f"📢 New eBay: {title} | ${price} | {link}")
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
def check_ebay(flag_name="ebay"):
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
        logger.debug(f"eBay: Searching {location} within {radius} miles")
    else:
        logger.warning(f"Could not geocode location '{location}', using default")
    
    for attempt in range(max_retries):
        try:
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

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
            }

            response = requests.get(full_url, headers=headers, timeout=30)
            response.raise_for_status()  # Raise exception for bad status codes
            
            # Parse with BeautifulSoup for better HTML handling
            soup = BeautifulSoup(response.text, 'html.parser')
            break  # Success, exit retry loop
        except (requests.exceptions.RequestException, requests.exceptions.Timeout) as e:
            logger.warning(f"eBay request failed (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                # Exponential backoff: 2, 4, 8 seconds
                delay = base_retry_delay * (2 ** attempt)
                logger.info(f"Retrying in {delay} seconds...")
                time.sleep(delay)
                continue
            else:
                logger.error(f"eBay request failed after {max_retries} attempts: {e}")
                return []
        except Exception as e:
            logger.error(f"Unexpected error in eBay scraper: {e}")
            return []

    # Process the results if we successfully got the page
    try:
        # eBay uses different HTML structures, try multiple patterns
        # Method 1: s-item (most common structure)
        items = soup.find_all('div', class_='s-item__wrapper')
        if not items:
            # Method 2: Try alternative structure
            items = soup.find_all('li', class_='s-item')
        
        if not items:
            # Method 3: Try even more generic
            items = soup.find_all('div', attrs={'class': lambda x: x and 's-item' in x if x else False})
        
        logger.debug(f"Found {len(items)} eBay items to process")
        
        for item in items:
            try:
                # Extract title
                title_elem = item.find('div', class_='s-item__title')
                if not title_elem:
                    title_elem = item.find('h3', class_='s-item__title')
                if not title_elem:
                    title_elem = item.find('a', class_='s-item__link')
                
                if not title_elem:
                    continue
                
                title = title_elem.get_text(strip=True)
                
                # Skip shop listings or ads
                if "Shop on eBay" in title or title == "":
                    continue
                
                # Extract link
                link_elem = item.find('a', class_='s-item__link')
                if not link_elem:
                    link_elem = item.find('a', href=True)
                
                if not link_elem or not link_elem.get('href'):
                    continue
                
                link = link_elem['href']
                
                # Clean eBay link (remove tracking parameters)
                if '?' in link:
                    link = link.split('?')[0]
                
                # Extract price
                price_elem = item.find('span', class_='s-item__price')
                if not price_elem:
                    # Try alternative price location
                    price_elem = item.find('span', attrs={'class': lambda x: x and 'price' in x.lower() if x else False})
                
                price_val = None
                if price_elem:
                    price_text = price_elem.get_text(strip=True)
                    try:
                        # Handle different price formats
                        # "$1,234.56" or "$1234" or "1234.56"
                        price_clean = price_text.replace('$', '').replace(',', '').strip()
                        
                        # Handle range prices (take the first price)
                        if ' to ' in price_clean:
                            price_clean = price_clean.split(' to ')[0].strip()
                        
                        # Convert to float then int
                        price_val = int(float(price_clean))
                    except (ValueError, AttributeError) as e:
                        logger.debug(f"Could not parse price from '{price_text}': {e}")
                
                # Filter by price range
                if price_val and (price_val < min_price or price_val > max_price):
                    continue
                
                # Check if any keyword matches and if it's a new listing
                if any(k.lower() in title.lower() for k in keywords) and is_new_listing(link):
                    normalized_link = normalize_url(link)
                    with _seen_listings_lock:
                        seen_listings[normalized_link] = datetime.now()
                    
                    # Extract image URL
                    image_url = None
                    try:
                        img_elem = item.find('img', class_='s-item__image-img')
                        if not img_elem:
                            img_elem = item.find('img')
                        
                        if img_elem and img_elem.get('src'):
                            image_url = img_elem['src']
                            # Make sure it's a full URL and not a placeholder
                            if image_url and not image_url.startswith("http"):
                                continue
                            # Skip data URLs and tiny placeholder images
                            if image_url and ('data:' in image_url or 's-l64' in image_url or 's-l50' in image_url):
                                # Try to get higher quality image
                                if img_elem.get('data-src'):
                                    image_url = img_elem['data-src']
                    except Exception as e:
                        logger.debug(f"Could not extract image for {link}: {e}")
                    
                    send_discord_message(title, link, price_val, image_url)
                    results.append({"title": title, "link": link, "price": price_val, "image": image_url})
            except Exception as e:
                logger.warning(f"Error parsing an eBay listing: {e}")
                continue

        if results:
            save_seen_listings()
        else:
            logger.info(f"No new eBay listings. Next check in {check_interval}s...")

        debug_scraper_output("eBay", results)
        return results

    except Exception as e:
        logger.error(f"Error processing eBay results: {e}")
        return []

# ======================
# CONTINUOUS RUNNER
# ======================
def run_ebay_scraper(flag_name="ebay"):
    """Run scraper continuously until stopped via running_flags."""
    logger.info("Starting eBay scraper")
    load_seen_listings()
    
    try:
        while running_flags.get(flag_name, True):
            try:
                logger.debug("Running eBay scraper check")
                results = check_ebay(flag_name)
                if results:
                    logger.info(f"eBay scraper found {len(results)} new listings")
                else:
                    logger.debug("eBay scraper found no new listings")
            except Exception as e:
                logger.error(f"Error in eBay scraper iteration: {e}")
                # Continue running but log the error
                continue
            
            settings = load_settings()
            # Delay dynamically based on interval
            human_delay(running_flags, flag_name, settings["interval"]*0.9, settings["interval"]*1.1)
            
    except KeyboardInterrupt:
        logger.info("eBay scraper interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error in eBay scraper: {e}")
    finally:
        logger.info("eBay scraper stopped")

