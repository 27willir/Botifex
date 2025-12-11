import random, time, json
import threading
from datetime import datetime
import requests
from pathlib import Path
import urllib.parse
import re
from typing import Any, Dict, List, Optional
from utils import debug_scraper_output, logger
from db import get_settings, save_listing
from error_handling import ErrorHandler, log_errors, ScraperError, NetworkError
from location_utils import geocode_location, get_location_coords, miles_to_km
from scrapers.common import (
    parse_html_with_fallback, get_session, make_request_with_retry,
    make_request_with_cascade, reset_session, validate_response_structure,
    detect_block_type, is_zero_results_page, RequestStrategy
)
from scrapers import anti_blocking
from scrapers import health_monitor
from collections import defaultdict

# ======================
# CONFIGURATION
# ======================
SITE_NAME = "poshmark"
poshmark_url = "https://poshmark.com"
BASE_URL = "https://poshmark.com"

# Poshmark-specific fallback chain
POSHMARK_FALLBACK_CHAIN = [
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


def get_poshmark_flag_key(user_id=None, flag_name="poshmark"):
    """Expose per-user running flag keys for orchestrators."""
    return _flag_key(flag_name, user_id)


seen_listings = defaultdict(dict)
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

def is_new_listing(link, user_id=None):
    """Return True if this listing is new or last seen more than 24h ago."""
    normalized_link = normalize_url(link)
    if not normalized_link:
        # If URL normalization failed, treat as new to attempt processing
        # This prevents valid listings from being silently skipped
        logger.debug(f"URL normalization failed for {link}, treating as new")
        return True
    
    with _seen_listings_lock:
        user_key = _user_key(user_id)
        user_seen = seen_listings[user_key]
        last_seen = user_seen.get(normalized_link)
        if last_seen is None:
            return True
    return (datetime.now() - last_seen).total_seconds() > 86400

def save_seen_listings(user_id=None, filename="poshmark_seen.json"):
    """Save seen listings with timestamps to JSON."""
    try:
        with _seen_listings_lock:
            user_key = _user_key(user_id)
            if user_key != "global":
                filename = f"poshmark_{user_key}_seen.json"
            Path(filename).write_text(
                json.dumps({k: v.isoformat() for k, v in seen_listings[user_key].items()}, indent=2),
                encoding="utf-8"
            )
        logger.debug(f"Saved seen listings to {filename}")
    except (OSError, PermissionError) as e:
        logger.error(f"File system error saving seen listings: {e}")
    except Exception as e:
        logger.error(f"Error saving seen listings: {e}")

def load_seen_listings(user_id=None, filename="poshmark_seen.json"):
    """Load seen listings from JSON, if available."""
    global seen_listings
    try:
        user_key = _user_key(user_id)
        if user_key != "global":
            filename = f"poshmark_{user_key}_seen.json"
        text = Path(filename).read_text(encoding="utf-8")
        data = json.loads(text) if text else {}
        with _seen_listings_lock:
            seen_listings[user_key] = {k: datetime.fromisoformat(v) for k, v in data.items()}
        logger.debug(f"Loaded {len(seen_listings[user_key])} seen listings from {filename}")
    except FileNotFoundError:
        logger.info(f"Seen listings file not found: {filename}, starting fresh")
        with _seen_listings_lock:
            seen_listings[_user_key(user_id)] = {}
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"Invalid JSON in seen listings file: {e}")
        with _seen_listings_lock:
            seen_listings[_user_key(user_id)] = {}
    except Exception as e:
        logger.error(f"Error loading seen listings: {e}")
        with _seen_listings_lock:
            seen_listings[_user_key(user_id)] = {}

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
        
        # Save to database
        save_listing(title, price, link, image_url, "poshmark", user_id=user_id)
        logger.info(f"📢 New Poshmark: {title} | ${price} | {link}")
    except Exception as e:
        logger.error(f"⚠️ Failed to save listing for {link}: {e}")

def load_settings(user_id=None):
    """Load settings from database"""
    try:
        settings = get_settings(username=user_id)  # Get user-specific settings
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
def check_poshmark(flag_name="poshmark", user_id=None, flag_key=None):
    settings = load_settings(user_id=user_id)
    keywords = settings["keywords"]
    min_price = settings["min_price"]
    max_price = settings["max_price"]
    check_interval = settings["interval"]
    location = settings.get("location", "boise")
    radius = settings.get("radius", 50)

    results = []
    flag_key = flag_key or _flag_key(flag_name, user_id)
    if not running_flags.get(flag_key, True):
        return []
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
            
            # Use randomized param order to avoid fingerprinting
            full_url = base_url + "?" + anti_blocking.randomize_params_order(params)
            
            session = get_session(SITE_NAME, initialize_url=BASE_URL, username=user_id)
            
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
                fallback_chain=POSHMARK_FALLBACK_CHAIN,
            )
            
            response_time = time.time() - start_time
            
            if not response:
                logger.error("Poshmark request failed after all fallbacks")
                health_monitor.record_failure(SITE_NAME, "all_fallbacks_exhausted")
                reset_session(SITE_NAME, initialize_url=BASE_URL, username=user_id)
                return []
            
            # Record successful request
            health_monitor.record_success(SITE_NAME, response_time, strategy_used)
            
            if strategy_used:
                logger.debug(f"Poshmark: Request succeeded using strategy '{strategy_used}'")

            encoding_candidates = []
            if response.encoding:
                encoding_candidates.append(response.encoding)
            apparent_encoding = getattr(response, "apparent_encoding", None)
            if apparent_encoding and apparent_encoding not in encoding_candidates:
                encoding_candidates.append(apparent_encoding)

            # Parse with fallback-aware HTML parser handling
            soup = parse_html_with_fallback(
                response.text,
                parser_order=("html.parser", "lxml"),
                encodings=encoding_candidates,
                raw_bytes=response.content,
                site_name="Poshmark",
            )
            break  # Success, exit retry loop
        except ScraperError as e:
            logger.error(f"Poshmark parser failed after fallbacks: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error in Poshmark scraper: {e}")
            return []

    # Process the results if we successfully got the page
    try:
        # Enhanced item extraction with multiple selector strategies
        # Updated for December 2024 Poshmark layout
        items = []
        parse_strategies = [
            # Current Poshmark selectors
            (1, "div.tile class", lambda: soup.find_all('div', class_='tile')),
            (2, "div.card patterns", lambda: soup.find_all('div', attrs={'class': lambda x: x and ('card' in str(x).lower() or 'Card' in str(x)) if x else False})),
            (3, "data-test tile", lambda: soup.select('[data-test="tile"], [data-test="listing"]')),
            (4, "article.tile", lambda: soup.find_all('article', class_='tile')),
            # Listing patterns
            (5, "div.listing pattern", lambda: soup.find_all('div', attrs={'class': lambda x: x and 'listing' in str(x).lower() if x else False})),
            (6, "div.item pattern", lambda: soup.find_all('div', attrs={'class': lambda x: x and 'item' in str(x).lower() if x else False})),
            # Product grid items
            (7, "div.product-card", lambda: soup.find_all('div', attrs={'class': lambda x: x and 'product' in str(x).lower() if x else False})),
            # Links with listing paths
            (8, "links with /listing/ in href", lambda: soup.find_all('a', href=lambda x: x and '/listing/' in str(x) if x else False)),
            (9, "links with /closet/ in href", lambda: soup.find_all('a', href=lambda x: x and '/closet/' in str(x) if x else False)),
            (10, "div.tile-container", lambda: soup.find_all('div', attrs={'class': lambda x: x and 'tile' in str(x).lower() if x else False})),
        ]
        
        for method_num, description, strategy in parse_strategies:
            try:
                items = strategy()
                if items:
                    logger.debug(f"Poshmark: Found {len(items)} items using method {method_num} ({description})")
                    break
            except Exception as e:
                logger.debug(f"Poshmark: Method {method_num} failed: {e}")
                continue
        
        logger.debug(f"Found {len(items)} Poshmark items to process")
        
        # Pre-compile keywords for faster matching
        keywords_lower = [k.lower() for k in keywords]
        user_key = _user_key(user_id)
        
        for item in items:
            try:
                # Enhanced title extraction with multiple fallbacks
                title = None
                title_selectors = [
                    item.find('a', class_='title'),
                    item.find('div', class_='title'),
                    item.find('h2'),
                    item.find('h3'),
                    item.find('h4'),
                    item.find('a', href=True),
                    item.find('span', class_=lambda x: x and 'title' in str(x).lower() if x else False),
                ]
                for title_elem in title_selectors:
                    if title_elem:
                        title_text = title_elem.get_text(strip=True) if hasattr(title_elem, 'get_text') else str(title_elem).strip()
                        if title_text:
                            title = title_text
                            break
                
                if not title:
                    continue
                
                # Enhanced link extraction with multiple fallbacks
                link = None
                link_selectors = [
                    item.find('a', href=True),
                    item.find('a', class_='title'),
                    item.find('a', class_='link'),
                ]
                for link_elem in link_selectors:
                    if link_elem:
                        link = link_elem.get('href')
                        if link:
                            break
                
                if not link:
                    continue
                
                # Make sure link is absolute (fast path check)
                if link.startswith('/'):
                    link = "https://poshmark.com" + link
                elif not link.startswith('http'):
                    link = "https://poshmark.com/" + link.lstrip('/')
                
                # Enhanced price extraction with multiple fallbacks
                price_val = None
                price_selectors = [
                    item.find('span', class_='price'),
                    item.find('div', class_='price'),
                    item.find('span', class_=lambda x: x and 'price' in str(x).lower() if x else False),
                    item.find('div', class_=lambda x: x and 'price' in str(x).lower() if x else False),
                    item.find('*', string=lambda x: x and '$' in str(x) if x else False),
                ]
                for price_elem in price_selectors:
                    if price_elem:
                        price_text = price_elem.get_text(strip=True) if hasattr(price_elem, 'get_text') else str(price_elem).strip()
                        if price_text:
                            try:
                                # Handle price formats efficiently
                                price_clean = price_text.replace('$', '').replace(',', '').strip()
                                price_val = int(float(price_clean))
                                if price_val:
                                    break
                            except (ValueError, AttributeError):
                                continue
                
                # Early exit if price out of range
                if price_val and (price_val < min_price or price_val > max_price):
                    continue
                
                # Check keywords (use pre-lowercased)
                title_lower = title.lower()
                if not any(k in title_lower for k in keywords_lower):
                    continue
                
                # Check if new listing
                if not is_new_listing(link, user_id=user_id):
                    continue
                
                # Update seen listings for this user
                normalized_link = normalize_url(link)
                with _seen_listings_lock:
                    seen_listings[user_key][normalized_link] = datetime.now()
                
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
            save_seen_listings(user_id=user_id)
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
    flag_key = _flag_key(flag_name, user_id)
    running_flags.setdefault(flag_key, True)
    
    try:
        logger.info(f"Starting Poshmark scraper for user {user_id}")
        load_seen_listings(user_id=user_id)
        
        try:
            while running_flags.get(flag_key, True):
                try:
                    logger.debug(f"Running Poshmark scraper check for user {user_id}")
                    results = check_poshmark(flag_name, user_id=user_id, flag_key=flag_key)
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
                
                settings = load_settings(user_id=user_id)
                # Delay dynamically based on interval
                human_delay(running_flags, flag_key, settings["interval"]*0.9, settings["interval"]*1.1)
                
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

