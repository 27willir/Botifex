"""Mercari scraper with shared anti-blocking defenses."""

import sys
import threading
import random
import json
import time
from datetime import datetime
import urllib.parse
import re

from bs4 import BeautifulSoup

from utils import debug_scraper_output, logger
from db import save_listing
from location_utils import get_location_coords, miles_to_km
from scrapers.common import (
    human_delay,
    normalize_url,
    is_new_listing,
    save_seen_listings,
    load_seen_listings,
    validate_listing,
    load_settings,
    get_session,
    make_request_with_retry,
    validate_image_url,
    check_recursion_guard,
    set_recursion_guard,
    log_selector_failure,
    log_parse_attempt,
    get_seen_listings_lock,
)
from scrapers.metrics import ScraperMetrics
from scrapers import anti_blocking


SITE_NAME = "mercari"
BASE_URL = "https://www.mercari.com"
SEARCH_PATH = "/search"


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


def get_mercari_flag_key(user_id=None, flag_name=SITE_NAME):
    """Expose running flag keys for orchestrators."""
    return _flag_key(flag_name, user_id)


seen_listings = {}


# ======================
# RUNNING FLAG
# ======================
running_flags = {SITE_NAME: True}
_seen_listings_lock = get_seen_listings_lock(SITE_NAME)


# ======================
# HELPER FUNCTIONS
# ======================
def _parse_price_value(value):
    """Convert price fragments into integer dollars."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, dict):
        # Common Mercari offer payloads
        for key in ("price", "amount", "value", "lowPrice"):
            nested = value.get(key)
            parsed = _parse_price_value(nested)
            if parsed is not None:
                return parsed
        return None
    if isinstance(value, list):
        for entry in value:
            parsed = _parse_price_value(entry)
            if parsed is not None:
                return parsed
        return None

    value_str = str(value)
    digits = "".join(ch for ch in value_str if ch.isdigit())
    return int(digits) if digits else None


def _coerce_json_listing(candidate):
    """Normalize a JSON candidate into listing dict."""
    if not isinstance(candidate, dict):
        return None

    title = candidate.get("title") or candidate.get("name") or candidate.get("headline")

    link = (
        candidate.get("url")
        or candidate.get("href")
        or candidate.get("link")
        or candidate.get("permalink")
    )
    if not link and candidate.get("slug"):
        slug = candidate["slug"].strip("/")
        link = f"{BASE_URL}/item/{slug}/"

    price_val = _parse_price_value(
        candidate.get("price")
        or candidate.get("priceAmount")
        or candidate.get("offers")
    )

    image = candidate.get("image") or candidate.get("images") or candidate.get("thumbnail")
    if isinstance(image, list):
        image = image[0]

    if isinstance(image, dict):
        image = image.get("url") or image.get("src")

    if title and link:
        return {
            "title": title,
            "link": link,
            "price": price_val,
            "image": image,
        }
    return None


def _extract_listings_from_json(payload):
    """Recursively scan JSON payloads for listing dictionaries."""
    listings = []
    seen_links = set()

    def _walk(node):
        if isinstance(node, dict):
            listing = _coerce_json_listing(node)
            if listing:
                normalized_link = listing["link"]
                if normalized_link not in seen_links:
                    listings.append(listing)
                    seen_links.add(normalized_link)
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for value in node:
                _walk(value)

    _walk(payload)
    return listings


def _parse_json_results(soup):
    """Gather listings from structured JSON embedded in the page."""
    listings = []

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(script.string)
        except (TypeError, json.JSONDecodeError):
            continue
        listings.extend(_extract_listings_from_json(data))

    next_data = soup.find("script", id="__NEXT_DATA__")
    if next_data and next_data.string:
        try:
            data = json.loads(next_data.string)
            listings.extend(_extract_listings_from_json(data))
        except (TypeError, json.JSONDecodeError):
            pass

    return listings


def _coerce_html_listing(node):
    """Normalize BeautifulSoup nodes into listing dictionaries."""
    if node is None:
        return None

    link_elem = node if node.name == "a" else node.find("a", href=True)
    if not link_elem:
        return None

    link = link_elem.get("href")
    if not link:
        return None
    link = urllib.parse.urljoin(BASE_URL, link)

    title = (
        link_elem.get("aria-label")
        or link_elem.get("title")
        or link_elem.get_text(" ", strip=True)
    )
    if not title:
        title_elem = node.find(["p", "span", "h2", "h3"], string=True)
        title = title_elem.get_text(" ", strip=True) if title_elem else None

    price_elem = None
    for candidate in node.find_all(["span", "div", "p"], string=True):
        text = candidate.get_text(" ", strip=True)
        if "$" in text:
            price_elem = candidate
            break

    price_val = _parse_price_value(price_elem.get_text()) if price_elem else None

    img_elem = node.find("img")
    image_url = None
    if img_elem:
        image_url = (
            img_elem.get("src")
            or img_elem.get("data-src")
            or img_elem.get("data-original")
        )
        if image_url:
            if image_url.startswith("//"):
                image_url = f"https:{image_url}"
            elif image_url.startswith("/"):
                image_url = urllib.parse.urljoin(BASE_URL, image_url)

    if title and link:
        return {
            "title": title,
            "link": link,
            "price": price_val,
            "image": image_url,
        }
    return None


def _parse_html_results(soup):
    """Gather listing dictionaries using multiple HTML selector strategies."""
    selectors = [
        ("data-testid item tiles", soup.select('[data-testid="ItemTile"], [data-testid="item-tile"]')),
        ("modern anchor cards", soup.select('a[href*="/item/"]')),
        ("legacy item-box divs", soup.find_all("div", class_="item-box")),
    ]

    listings = []
    for index, (label, nodes) in enumerate(selectors, start=1):
        if not nodes:
            continue
        log_parse_attempt(SITE_NAME, index, label)
        for node in nodes:
            listing = _coerce_html_listing(node)
            if listing:
                listings.append(listing)
        if listings:
            break

    return listings


def send_discord_message(title, link, price=None, image_url=None, user_id=None):
    """Save listing to database and emit notification logs."""
    try:
        is_valid, error = validate_listing(title, link, price)
        if not is_valid:
            logger.warning(f"⚠️ Skipping invalid Mercari listing: {error}")
            return

        if image_url and not validate_image_url(image_url):
            logger.debug(f"Mercari listing image filtered as placeholder: {image_url}")
            image_url = None

        save_listing(title, price, link, image_url, SITE_NAME, user_id=user_id)
        logger.info(f"📢 New Mercari for {user_id}: {title} | ${price} | {link}")
    except Exception as exc:
        logger.error(f"⚠️ Failed to save Mercari listing for {link}: {exc}")


def check_mercari(flag_name=SITE_NAME, user_id=None, user_seen=None, flag_key=None):
    settings = load_settings(username=user_id)
    keywords = settings["keywords"]
    min_price = settings["min_price"]
    max_price = settings["max_price"]
    check_interval = settings["interval"]
    location = settings.get("location", "boise")
    radius = settings.get("radius", 50)

    results = []
    flag_key = flag_key or _flag_key(flag_name, user_id)
    user_key = _user_key(user_id)
    if user_seen is None:
        user_seen = seen_listings.setdefault(user_key, {})

    with ScraperMetrics(SITE_NAME) as metrics:
        try:
            if not running_flags.get(flag_key, True):
                metrics.error = "stopped"
                return []

            location_coords = get_location_coords(location)
            if location_coords:
                logger.debug(f"Mercari: Searching {location} within {radius} miles")
            else:
                logger.warning(f"Mercari: Could not geocode location '{location}', defaulting to keyword search")

            base_url = f"{BASE_URL}{SEARCH_PATH}"
            query = " ".join(keywords)

            params = {
                "keyword": query,
                "price_min": min_price,
                "price_max": max_price,
                "sort": "created_time",
                "order": "desc",
                "status": "on_sale",
                "limit": 80,
                "page": 1,
                "_": random.randint(100000, 999999),
            }

            if location_coords:
                lat, lon = location_coords
                params["latitude"] = lat
                params["longitude"] = lon
                params["distance"] = int(miles_to_km(radius))

            full_url = base_url + "?" + urllib.parse.urlencode(params)

            # Get persistent session with initialization
            session = get_session(SITE_NAME, initialize_url=BASE_URL, username=user_id)
            
            # Add extra delay before Mercari requests to avoid detection
            time.sleep(random.uniform(1.5, 3.0))
            
            response = make_request_with_retry(
                full_url,
                SITE_NAME,
                session=session,
                referer=BASE_URL,
                origin=BASE_URL,
                session_initialize_url=BASE_URL,
                username=user_id,
                max_retries=5,  # More retries for Mercari
            )

            if not response:
                metrics.error = "Failed to fetch page after retries"
                logger.warning("Mercari request exhausted retries without success")
                # Reset session after failure to get fresh cookies
                from scrapers.common import reset_session
                reset_session(SITE_NAME, initialize_url=BASE_URL, username=user_id)
                return []
            
            soup = BeautifulSoup(response.text, "html.parser")

            listings_by_link = {}

            json_candidates = _parse_json_results(soup)
            for candidate in json_candidates:
                if not candidate.get("link"):
                    continue
                listings_by_link.setdefault(candidate["link"], candidate)

            html_candidates = _parse_html_results(soup)
            for candidate in html_candidates:
                if not candidate.get("link"):
                    continue
                listings_by_link.setdefault(candidate["link"], candidate)

            if not listings_by_link:
                log_selector_failure(SITE_NAME, "html/json", "search results", "posts")
                text_snippet = soup.get_text(separator=" ").lower()[:2000]
                block_keywords = (
                    "please verify",
                    "access denied",
                    "unusual traffic",
                    "bot detection",
                    "slow down",
                )
                if any(keyword in text_snippet for keyword in block_keywords):
                    anti_blocking.record_block(SITE_NAME, "keyword:mercari-block", cooldown_hint=150)
                logger.warning("Mercari: No items found with HTML or JSON selectors")
                metrics.success = True
                metrics.listings_found = 0
                return []

            keywords_lower = [k.lower() for k in keywords]
            processed_links = set()
            lock = get_seen_listings_lock(SITE_NAME)

            for candidate in listings_by_link.values():
                link = candidate.get("link")
                title = (candidate.get("title") or "").strip()
                price_val = _parse_price_value(candidate.get("price"))
                image_url = candidate.get("image")

                if not link or not title:
                    continue

                link = urllib.parse.urljoin(BASE_URL, link)
                normalized_link = normalize_url(link)
                if not normalized_link or normalized_link in processed_links:
                    continue

                processed_links.add(normalized_link)

                if price_val and (price_val < min_price or price_val > max_price):
                    continue

                title_lower = title.lower()
                if keywords_lower and not any(keyword in title_lower for keyword in keywords_lower):
                    continue

                if not is_new_listing(link, user_seen, SITE_NAME):
                    continue

                with lock:
                    user_seen[normalized_link] = datetime.now()

                if image_url:
                    if image_url.startswith("//"):
                        image_url = f"https:{image_url}"
                    elif image_url.startswith("/"):
                        image_url = urllib.parse.urljoin(BASE_URL, image_url)
                    if not validate_image_url(image_url):
                        logger.debug(f"Mercari image rejected as placeholder: {image_url}")
                        image_url = None

                send_discord_message(title, link, price_val, image_url, user_id=user_id)
                results.append({
                    "title": title,
                    "link": link,
                    "price": price_val,
                    "image": image_url,
                })

            if results:
                save_seen_listings(user_seen, SITE_NAME, username=user_id)
                metrics.success = True
                metrics.listings_found = len(results)
            else:
                logger.info(f"No new Mercari listings. Next check in {check_interval}s...")
                metrics.success = True
                metrics.listings_found = 0

            debug_scraper_output("Mercari", results)
            return results

        except Exception as exc:
            logger.error(f"Error processing Mercari results: {exc}")
            metrics.error = str(exc)
            return []


# ======================
# CONTINUOUS RUNNER
# ======================
def run_mercari_scraper(flag_name=SITE_NAME, user_id=None):
    """Run Mercari scraper continuously until stopped."""
    if check_recursion_guard(SITE_NAME):
        return

    set_recursion_guard(SITE_NAME, True)
    flag_key = _flag_key(flag_name, user_id)
    running_flags.setdefault(flag_key, True)

    try:
        logger.info(f"Starting Mercari scraper for user {user_id}")
        user_key = _user_key(user_id)
        user_seen = load_seen_listings(SITE_NAME, username=user_id)
        seen_listings[user_key] = user_seen

        try:
            while running_flags.get(flag_key, True):
                try:
                    logger.debug(f"Running Mercari scraper check for user {user_id}")
                    results = check_mercari(flag_name, user_id=user_id, user_seen=user_seen, flag_key=flag_key)
                    if results:
                        logger.info(f"Mercari scraper found {len(results)} new listings for user {user_id}")
                    else:
                        logger.debug(f"Mercari scraper found no new listings for user {user_id}")
                except RecursionError as exc:
                    print(f"ERROR: RecursionError in Mercari scraper: {exc}", file=sys.stderr, flush=True)
                    time.sleep(10)
                    continue
                except Exception as exc:
                    try:
                        logger.error(f"Error in Mercari scraper iteration: {exc}")
                    except Exception:
                        print(f"ERROR: Error in Mercari scraper iteration: {exc}", file=sys.stderr, flush=True)
                    continue

                settings = load_settings(username=user_id)
                interval = settings.get("interval", 60)
                human_delay(running_flags, flag_key, interval * 0.9, interval * 1.1)

        except KeyboardInterrupt:
            logger.info("Mercari scraper interrupted by user")
        except RecursionError as exc:
            print(f"FATAL: RecursionError in Mercari scraper main loop: {exc}", file=sys.stderr, flush=True)
        except Exception as exc:
            try:
                logger.error(f"Fatal error in Mercari scraper: {exc}")
            except Exception:
                print(f"ERROR: Fatal error in Mercari scraper: {exc}", file=sys.stderr, flush=True)
        finally:
            logger.info("Mercari scraper stopped")

    finally:
        set_recursion_guard(SITE_NAME, False)

