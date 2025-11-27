import random, re, time, json
import urllib.parse
import threading
from datetime import datetime
from collections import defaultdict

from lxml import html
from selenium.webdriver.common.by import By

from utils import debug_scraper_output, logger
from db import get_settings, save_listing
from error_handling import ErrorHandler, log_errors, ScraperError, NetworkError
from location_utils import geocode_location
from scrapers.metrics import ScraperMetrics

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

SITE_NAME = "facebook"
BASE_URL = "https://www.facebook.com"

seen_listings = defaultdict(dict)
_seen_listings_lock = threading.Lock()  # Thread safety for seen_listings

# ======================
# RECURSION GUARD
# ======================
_recursion_guard = threading.local()

# ======================
# RUNNING FLAG
# ======================
running_flags = {SITE_NAME: True}

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
        url = url.strip()
        if url.startswith("/"):
            url = urllib.parse.urljoin(BASE_URL, url)
        elif url.startswith("www.facebook.com") or url.startswith("facebook.com"):
            url = f"https://{url.lstrip('/')}"

        parsed = urllib.parse.urlparse(url)
        scheme = parsed.scheme or "https"
        netloc = parsed.netloc or urllib.parse.urlparse(BASE_URL).netloc
        normalized = urllib.parse.urlunparse(
            (scheme, netloc, parsed.path.rstrip("/"), "", "", "")
        )
        return normalized or None
    except Exception as e:
        logger.debug(f"Error normalizing URL {url}: {e}")
        return url


def resolve_listing_link(raw_href):
    """Resolve Facebook Marketplace listing href into a canonical absolute URL."""
    if not raw_href or not isinstance(raw_href, str):
        return None

    href = raw_href.strip()
    if not href or href.startswith("#") or href.lower().startswith("javascript:"):
        return None

    if href.startswith("/"):
        href = urllib.parse.urljoin(BASE_URL, href)
    elif href.startswith("www.facebook.com") or href.startswith("facebook.com"):
        href = f"https://{href.lstrip('/')}"
    elif href.startswith("http"):
        parsed = urllib.parse.urlparse(href)
        if parsed.netloc in {"l.facebook.com", "lm.facebook.com"}:
            query = urllib.parse.parse_qs(parsed.query)
            candidate = query.get("u") or query.get("url")
            if candidate and candidate[0]:
                href = urllib.parse.unquote(candidate[0])
    else:
        return None

    if href.startswith("/"):
        href = urllib.parse.urljoin(BASE_URL, href)

    return normalize_url(href)


def _xpath_literal(value):
    """Safely wrap a string for XPath literal usage."""
    if value is None:
        return "''"
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    parts = value.split("'")
    concat_parts = []
    for index, part in enumerate(parts):
        if part:
            concat_parts.append(f"'{part}'")
        if index != len(parts) - 1:
            concat_parts.append('"\'"')
    return "concat(" + ", ".join(concat_parts) + ")"

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


def get_facebook_flag_key(user_id=None, flag_name=SITE_NAME):
    """Public helper to compute the running flag key for a user."""
    return _flag_key(flag_name, user_id)


def is_new_listing(link, user_id=None):
    """Check if a listing has been seen within the last 24 hours."""
    normalized_link = normalize_url(link)
    if not normalized_link:
        # If URL normalization failed, treat as new to attempt processing
        logger.debug(f"URL normalization failed for {link}, treating as new")
        return True
    
    user_key = _user_key(user_id)
    with _seen_listings_lock:
        user_seen = seen_listings[user_key]
        last_seen = user_seen.get(normalized_link)
        if last_seen is None:
            return True
    return (datetime.now() - last_seen).total_seconds() > 86400

def save_seen_listings(user_id=None, filename=None):
    """Save seen listings to JSON."""
    try:
        user_key = _user_key(user_id)
        if filename is None:
            filename = (
                f"{SITE_NAME}_{user_key}_seen.json" if user_key != "global" else f"{SITE_NAME}_seen.json"
            )

        with _seen_listings_lock:
            user_seen = seen_listings[user_key]
            with open(filename, "w") as f:
                json.dump({k: v.isoformat() for k, v in user_seen.items()}, f, indent=2)
        logger.debug(f"Saved seen listings to {filename}")
    except (OSError, PermissionError) as e:
        logger.error(f"File system error saving seen listings: {e}")
    except Exception as e:
        logger.error(f"Failed to save seen listings: {e}")

def load_seen_listings(user_id=None, filename=None):
    """Load previously seen listings from JSON."""
    user_key = _user_key(user_id)
    try:
        if filename is None:
            filename = (
                f"{SITE_NAME}_{user_key}_seen.json" if user_key != "global" else f"{SITE_NAME}_seen.json"
            )
        with open(filename, "r") as f:
            data = json.load(f)
        with _seen_listings_lock:
            seen_listings[user_key] = {k: datetime.fromisoformat(v) for k, v in data.items()}
        logger.debug(f"Loaded {len(seen_listings[user_key])} seen listings from {filename}")
    except FileNotFoundError:
        logger.info(f"Seen listings file not found: {filename}, starting fresh")
        with _seen_listings_lock:
            seen_listings[user_key] = {}
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"Invalid JSON in seen listings file: {e}")
        with _seen_listings_lock:
            seen_listings[user_key] = {}
    except Exception as e:
        logger.error(f"Failed to load seen listings: {e}")
        with _seen_listings_lock:
            seen_listings[user_key] = {}

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
        ErrorHandler.handle_database_error(
            save_listing,
            title,
            price,
            link,
            image_url,
            SITE_NAME,
            user_id,
        )
        logger.info(f"📢 New Facebook Listing: {title} | ${price} | {link}")
    except Exception as e:
        logger.error(f"Failed to save Facebook listing for {link}: {e}")

DEFAULT_KEYWORDS = ["Firebird", "Camaro", "Corvette"]


def _sanitize_keywords(raw_keywords):
    """Normalize keywords state into a non-empty list."""
    keywords = []
    if isinstance(raw_keywords, str):
        keywords = [k.strip() for k in raw_keywords.split(",") if k.strip()]
    elif isinstance(raw_keywords, (list, tuple, set)):
        keywords = [str(k).strip() for k in raw_keywords if str(k).strip()]

    if not keywords:
        # Fall back to defaults when the user-provided list is empty
        return DEFAULT_KEYWORDS.copy()

    return keywords


def load_settings(user_id=None):
    """Load settings from database"""
    try:
        settings = get_settings(username=user_id)
        keywords = _sanitize_keywords(settings.get("keywords", DEFAULT_KEYWORDS))
        return {
            "keywords": keywords,
            "min_price": int(settings.get("min_price", 1000)),
            "max_price": int(settings.get("max_price", 30000)),
            "interval": int(settings.get("interval", 60)),
            "location": settings.get("location", "boise"),
            "radius": int(settings.get("radius", 50))
        }
    except Exception as e:
        logger.error(f"⚠️ Failed to load settings: {e}")
        return {
            "keywords": DEFAULT_KEYWORDS.copy(),
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
def check_facebook(driver, user_id=None, flag_key=None):
    with ScraperMetrics(SITE_NAME) as metrics:
        try:
            flag_key = flag_key or _flag_key(SITE_NAME, user_id)
            settings = ErrorHandler.handle_database_error(load_settings, user_id)
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
            human_delay(running_flags, flag_key, min_sec=3, max_sec=6)
            human_scroll(driver, running_flags, flag_key)

            tree = html.fromstring(driver.page_source)
            anchors = [a for a in tree.xpath("//a[@href]") if isinstance(a.get("href"), str)]

            price_pattern = re.compile(r"\$\s?([\d,]+)")
            keywords_lower = [k.lower() for k in keywords]
            bad_img_patterns = {"icon", "logo", "placeholder", "blank"}

            user_key = _user_key(user_id)
            with _seen_listings_lock:
                user_seen = seen_listings.setdefault(user_key, {})

            results = []
            for a in anchors:
                try:
                    raw_href = a.get("href")
                    link = resolve_listing_link(raw_href)
                    title = (a.text_content() or "").strip()

                    if not title or not link:
                        continue

                    price = None
                    price_match = price_pattern.search(title)
                    if price_match:
                        try:
                            price = int(price_match.group(1).replace(",", ""))
                        except (ValueError, AttributeError):
                            price = None

                    if price is not None and (price < min_price or price > max_price):
                        continue

                    title_lower = title.lower()
                    if not any(k in title_lower for k in keywords_lower):
                        continue

                    if not is_new_listing(link, user_id=user_id):
                        continue

                    normalized_link = normalize_url(link)
                    if not normalized_link:
                        normalized_link = link
                    with _seen_listings_lock:
                        user_seen[normalized_link] = datetime.now()

                    image_url = None
                    dom_href = raw_href.split("?", 1)[0].strip() if isinstance(raw_href, str) else None
                    try:
                        if dom_href:
                            xpath_value = _xpath_literal(dom_href)
                            parent_link = driver.find_element(By.XPATH, f"//a[@href={xpath_value}]")
                            images = parent_link.find_elements(By.TAG_NAME, "img")
                            for img in images:
                                src = img.get_attribute("src")
                                if src and src.startswith("https://"):
                                    src_lower = src.lower()
                                    if not any(pattern in src_lower for pattern in bad_img_patterns):
                                        image_url = src
                                        break

                        if not image_url:
                            imgs = driver.find_elements(
                                By.CSS_SELECTOR, "img[data-imgperflogname='marketplace_search_result_image']"
                            )
                            if imgs:
                                image_url = imgs[0].get_attribute("src")

                        if not image_url:
                            all_imgs = driver.find_elements(By.TAG_NAME, "img")
                            for img in all_imgs[:10]:
                                src = img.get_attribute("src")
                                if src and "scontent" in src and src.startswith("https://"):
                                    image_url = src
                                    break
                    except Exception:
                        pass  # Silently ignore image extraction errors

                    send_discord_message(title, link, price, image_url, user_id=user_id)
                    results.append(
                        {
                            "title": title,
                            "link": link,
                            "price": price,
                            "image": image_url,
                        }
                    )
                except Exception as exc:
                    logger.warning(f"Error processing Facebook listing: {exc}")
                    continue

            if results:
                save_seen_listings(user_id=user_id)
            else:
                logger.debug(f"No new Facebook listings. Next check in {check_interval}s...")

            metrics.success = True
            metrics.listings_found = len(results)

            debug_scraper_output("Facebook", results)
            return results

        except NetworkError as e:
            metrics.error = str(e)
            logger.error(f"Network error scraping Facebook: {e}")
            return []
        except ScraperError as e:
            metrics.error = str(e)
            logger.error(f"Scraper error on Facebook: {e}")
            return []
        except Exception as e:
            metrics.error = str(e)
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
    flag_key = _flag_key(flag_name, user_id)
    # Ensure we always start a fresh run with the flag enabled
    running_flags[flag_key] = True
    
    try:
        load_seen_listings(user_id=user_id)
        logger.info(f"Starting Facebook scraper for user {user_id}")
        
        try:
            while running_flags.get(flag_key, True):
                try:
                    check_facebook(driver, user_id=user_id, flag_key=flag_key)
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
                    human_delay(running_flags, flag_key, 30, 60)
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
                    settings = ErrorHandler.handle_database_error(load_settings, user_id)
                    human_delay(running_flags, flag_key, settings["interval"]*0.9, settings["interval"]*1.1)
                except Exception as e:
                    try:
                        logger.error(f"Error in Facebook scraper delay: {e}")
                    except:
                        import sys
                        print(f"ERROR: Error in Facebook scraper delay: {e}", file=sys.stderr, flush=True)
                    # Use default delay if settings fail
                    human_delay(running_flags, flag_key, 60, 90)
                
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
