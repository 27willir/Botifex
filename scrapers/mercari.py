import sys
import threading
import time
import random
import json
from datetime import datetime
import urllib.parse
from pathlib import Path
import requests
from bs4 import BeautifulSoup
from utils import debug_scraper_output, logger
from db import save_listing
from error_handling import ErrorHandler, log_errors, ScraperError, NetworkError
from location_utils import get_location_coords, miles_to_km
from scrapers.common import (
    human_delay, normalize_url, is_new_listing, save_seen_listings,
    load_seen_listings, validate_listing, load_settings, get_session,
    make_request_with_retry, validate_image_url, check_recursion_guard,
    set_recursion_guard, clear_recursion_guard, log_selector_failure, 
    log_parse_attempt, get_seen_listings_lock, get_random_user_agent,
    get_realistic_headers, initialize_session
)
from scrapers.metrics import ScraperMetrics

# ======================
# CONFIGURATION
# ======================
SITE_NAME = "mercari"
BASE_URL = "https://www.mercari.com"

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
        # Validate image URL
        validated_image = validate_image_url(image_url)
        
        # Validate data before saving
        is_valid, error = validate_listing(title, link, price)
        if not is_valid:
            logger.warning(f"⚠️ Skipping invalid listing: {error}")
            return
        
        # Save to database with user_id
        save_listing(title, price, link, validated_image, "mercari", user_id=user_id)
        logger.info(f"📢 New Mercari for {user_id}: {title} | ${price} | {link}")
    except Exception as e:
        logger.error(f"⚠️ Failed to save listing for {link}: {e}")

# ======================
# MAIN SCRAPER FUNCTION
# ======================
def check_mercari(flag_name=SITE_NAME, user_id=None):
    settings = load_settings(username=user_id)
    keywords = settings["keywords"]
    min_price = settings["min_price"]
    max_price = settings["max_price"]
    check_interval = settings["interval"]
    location = settings.get("location", "boise")
    radius = settings.get("radius", 50)

    results = []
    max_retries = 5  # Increased for 403 handling
    base_retry_delay = 3  # Longer initial delay
    
    # Get location coordinates for distance filtering
    location_coords = get_location_coords(location)
    if location_coords:
        logger.debug(f"Mercari: Searching {location} within {radius} miles")
    else:
        logger.warning(f"Could not geocode location '{location}', using default")
    
    for attempt in range(max_retries):
        try:
            # Build Mercari search URL
            # Mercari uses /search for search queries
            base_url = "https://www.mercari.com/search"
            
            # Join keywords with spaces for search
            query = " ".join(keywords)
            
            # Build URL with parameters
            params = {
                "keyword": query,
                "price_min": min_price,
                "price_max": max_price,
                "sort": "created_time",
                "order": "desc",
                "status": "on_sale"
            }
            
            # Add location filtering if coordinates available
            if location_coords:
                lat, lon = location_coords
                radius_km = int(miles_to_km(radius))
                params["latitude"] = lat
                params["longitude"] = lon
                params["distance"] = radius_km
            
            full_url = base_url + "?" + urllib.parse.urlencode(params)

            # Use realistic headers to avoid detection
            headers = get_realistic_headers()
            # Add referer for subsequent requests
            if attempt > 0:
                headers["Referer"] = "https://www.mercari.com/"
            
            # Add random delay before request to seem more human
            if attempt > 0:
                time.sleep(random.uniform(1, 3))

            # Use session for cookie persistence
            session = get_session(SITE_NAME, BASE_URL)
            response = session.get(full_url, headers=headers, timeout=30)
            
            # Handle 403 specifically - likely bot detection
            if response.status_code == 403:
                logger.warning(f"Mercari returned 403 (bot detection). Attempt {attempt + 1}/{max_retries}")
                if attempt < max_retries - 1:
                    # Clear session and reinitialize with fresh session
                    session.cookies.clear()
                    delay = base_retry_delay * (2 ** attempt) + random.uniform(5, 15)
                    logger.info(f"Reinitializing session and retrying in {delay:.1f} seconds...")
                    time.sleep(delay)
                    # Try to reinitialize session by visiting homepage
                    initialize_session(SITE_NAME, BASE_URL)
                    continue
                else:
                    logger.error(f"Mercari blocking requests after {max_retries} attempts. Waiting longer before next attempt...")
                    # Return empty instead of continuing to hammer the server
                    return []
            
            response.raise_for_status()  # Raise exception for other bad status codes
            
            # Parse with BeautifulSoup for better HTML handling
            soup = BeautifulSoup(response.text, 'html.parser')
            break  # Success, exit retry loop
        except (requests.exceptions.RequestException, requests.exceptions.Timeout) as e:
            logger.warning(f"Mercari request failed (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                # Exponential backoff: 2, 4, 8 seconds
                delay = base_retry_delay * (2 ** attempt)
                logger.info(f"Retrying in {delay} seconds...")
                time.sleep(delay)
                continue
            else:
                logger.error(f"Mercari request failed after {max_retries} attempts: {e}")
                return []
        except Exception as e:
            logger.error(f"Unexpected error in Mercari scraper: {e}")
            return []

    # Process the results if we successfully got the page
    try:
        # Try to find listing items (consolidated selectors)
        items = (soup.find_all('div', class_='item-box') or 
                soup.find_all('div', attrs={'class': lambda x: x and 'item' in x.lower() if x else False}) or 
                soup.find_all('div', attrs={'class': lambda x: x and 'listing' in x.lower() if x else False}))
        
        logger.debug(f"Found {len(items)} Mercari items to process")
        
        # Pre-compile keywords for faster matching
        keywords_lower = [k.lower() for k in keywords]
        
        for item in items:
            try:
                # Extract title (consolidated selector)
                title_elem = (item.find('h3', class_='item-name') or 
                             item.find('a', class_='item-name') or 
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
                    link = "https://www.mercari.com" + link
                
                # Extract and parse price (consolidated)
                price_elem = item.find('div', class_='item-price') or item.find('span', class_='price')
                
                price_val = None
                if price_elem:
                    price_text = price_elem.get_text(strip=True)
                    try:
                        # Handle different price formats efficiently
                        price_clean = price_text.replace('$', '').replace('¥', '').replace(',', '').strip()
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
                if not is_new_listing(link, seen_listings, SITE_NAME):
                    continue
                
                # Update seen listings
                normalized_link = normalize_url(link)
                lock = get_seen_listings_lock(SITE_NAME)
                with lock:
                    seen_listings[normalized_link] = datetime.now()
                
                # Extract image URL
                image_url = None
                img_elem = item.find('img')
                if img_elem:
                    image_url = img_elem.get('src') or img_elem.get('data-src') or img_elem.get('data-original')
                    # Make sure it's a full URL (fast path checks)
                    if image_url:
                        if not image_url.startswith("http"):
                            if image_url.startswith('//'):
                                image_url = 'https:' + image_url
                            elif image_url.startswith('/'):
                                image_url = "https://www.mercari.com" + image_url
                
                send_discord_message(title, link, price_val, image_url, user_id=user_id)
                results.append({"title": title, "link": link, "price": price_val, "image": image_url})
            except Exception as e:
                logger.warning(f"Error parsing a Mercari listing: {e}")
                continue

        if results:
            save_seen_listings(seen_listings, SITE_NAME)
        else:
            logger.info(f"No new Mercari listings. Next check in {check_interval}s...")

        debug_scraper_output("Mercari", results)
        return results

    except Exception as e:
        logger.error(f"Error processing Mercari results: {e}")
        return []

# ======================
# CONTINUOUS RUNNER
# ======================
def run_mercari_scraper(flag_name="mercari", user_id=None):
    """Run scraper continuously until stopped via running_flags."""
    # Check for recursion
    if check_recursion_guard(SITE_NAME):
        import sys
        print("ERROR: Recursion detected in Mercari scraper", file=sys.stderr, flush=True)
        return
    
    set_recursion_guard(SITE_NAME, True)
    
    try:
        logger.info(f"Starting Mercari scraper for user {user_id}")
        seen_listings.update(load_seen_listings(SITE_NAME))
        
        # Initialize session by visiting homepage first
        initialize_session(SITE_NAME, BASE_URL)
        
        try:
            while running_flags.get(flag_name, True):
                try:
                    logger.debug(f"Running Mercari scraper check for user {user_id}")
                    results = check_mercari(flag_name, user_id=user_id)
                    if results:
                        logger.info(f"Mercari scraper found {len(results)} new listings for user {user_id}")
                    else:
                        logger.debug(f"Mercari scraper found no new listings for user {user_id}")
                except RecursionError as e:
                    import sys
                    print(f"ERROR: RecursionError in Mercari scraper: {e}", file=sys.stderr, flush=True)
                    # Wait before retrying to avoid tight loop
                    time.sleep(10)
                    continue
                except Exception as e:
                    # Use fallback logging to avoid recursion in error handling
                    try:
                        logger.error(f"Error in Mercari scraper iteration: {e}")
                    except:
                        import sys
                        print(f"ERROR: Error in Mercari scraper iteration: {e}", file=sys.stderr, flush=True)
                    # Continue running but log the error
                    continue
                
                settings = load_settings(username=user_id)
                # Delay dynamically based on interval
                human_delay(running_flags, flag_name, settings["interval"]*0.9, settings["interval"]*1.1)
                
        except KeyboardInterrupt:
            logger.info("Mercari scraper interrupted by user")
        except RecursionError as e:
            import sys
            print(f"FATAL: RecursionError in Mercari scraper main loop: {e}", file=sys.stderr, flush=True)
        except Exception as e:
            try:
                logger.error(f"Fatal error in Mercari scraper: {e}")
            except:
                import sys
                print(f"ERROR: Fatal error in Mercari scraper: {e}", file=sys.stderr, flush=True)
        finally:
            logger.info("Mercari scraper stopped")
    finally:
        clear_recursion_guard(SITE_NAME)

