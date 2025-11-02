"""Mercari scraper with shared anti-blocking defenses."""

import sys
import time
from datetime import datetime
import urllib.parse

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
SEARCH_ENDPOINT = f"{BASE_URL}/search"

seen_listings = {}
running_flags = {SITE_NAME: True}
_seen_listings_lock = get_seen_listings_lock(SITE_NAME)


def _build_search_url(keywords, min_price, max_price, location_coords, radius):
    params = {
        "keyword": " ".join(keywords),
        "price_min": min_price,
        "price_max": max_price,
        "sort": "created_time",
        "order": "desc",
        "status": "on_sale",
    }

    if location_coords:
        lat, lon = location_coords
        distance_km = max(1, int(round(miles_to_km(radius))))
        params["latitude"] = lat
        params["longitude"] = lon
        params["distance"] = distance_km

    return f"{SEARCH_ENDPOINT}?{urllib.parse.urlencode(params)}"


def _send_listing(title, link, price=None, image_url=None, user_id=None):
    try:
        is_valid, error = validate_listing(title, link, price)
        if not is_valid:
            logger.warning(f"⚠️ Skipping invalid listing: {error}")
            return

        if image_url and not validate_image_url(image_url):
            logger.debug(f"Invalid/placeholder image URL for Mercari listing, dropping image: {image_url}")
            image_url = None

        save_listing(title, price, link, image_url, SITE_NAME, user_id=user_id)
        prefix = f"{SITE_NAME.title()} for {user_id}" if user_id else SITE_NAME.title()
        logger.info(f"📢 New {prefix}: {title} | ${price} | {link}")
    except Exception as exc:
        logger.error(f"⚠️ Failed to save Mercari listing {link}: {exc}")


def _extract_image_url(item):
    image_url = None
    img_elem = item.find("img")
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

    return image_url


def check_mercari(flag_name=SITE_NAME, user_id=None):
    settings = load_settings(username=user_id)
    keywords = settings["keywords"]
    min_price = settings["min_price"]
    max_price = settings["max_price"]
    check_interval = settings["interval"]
    location = settings.get("location", "boise")
    radius = settings.get("radius", 50)

    results = []
    keywords_lower = [k.lower() for k in keywords]

    with ScraperMetrics(SITE_NAME) as metrics:
        try:
            location_coords = get_location_coords(location)
            if location_coords:
                logger.debug(f"Mercari: searching {location} within {radius} miles")
            else:
                logger.debug(f"Mercari: location '{location}' not resolved, using global search")

            search_url = _build_search_url(keywords, min_price, max_price, location_coords, radius)
            session = get_session(SITE_NAME, BASE_URL)
            response = make_request_with_retry(
                search_url,
                SITE_NAME,
                max_retries=5,
                session=session,
                headers={"Referer": BASE_URL},
            )

            if not response:
                metrics.error = "Failed to fetch search results"
                return []

            soup = BeautifulSoup(response.text, "html.parser")

            selector_attempts = [
                ("item-box cards", lambda doc: doc.find_all("div", class_="item-box")),
                (
                    "div[class*=item]",
                    lambda doc: doc.find_all(
                        "div",
                        attrs={"class": lambda cls: cls and "item" in cls.lower()},
                    ),
                ),
                (
                    "div[class*=listing]",
                    lambda doc: doc.find_all(
                        "div",
                        attrs={"class": lambda cls: cls and "listing" in cls.lower()},
                    ),
                ),
            ]

            items = []
            for idx, (description, extractor) in enumerate(selector_attempts, start=1):
                log_parse_attempt(SITE_NAME, idx, description)
                items = extractor(soup)
                if items:
                    break

            if not items:
                log_selector_failure(SITE_NAME, "css", "Mercari listing containers", "posts")
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
                metrics.success = True
                metrics.listings_found = 0
                logger.info("Mercari: no listings returned by current selectors")
                return []

            for item in items:
                try:
                    title_elem = (
                        item.find("h3", class_="item-name")
                        or item.find("a", class_="item-name")
                        or item.find("h3")
                        or item.find("a", href=True)
                    )
                    if not title_elem:
                        continue

                    title = title_elem.get_text(strip=True)
                    if not title:
                        continue

                    link_elem = item.find("a", href=True)
                    if not link_elem:
                        continue

                    link = urllib.parse.urljoin(BASE_URL, link_elem.get("href"))
                    if not link:
                        continue

                    price_val = None
                    price_elem = item.find("div", class_="item-price") or item.find("span", class_="price")
                    if price_elem:
                        price_text = price_elem.get_text(strip=True)
                        try:
                            cleaned = (
                                price_text.replace("$", "")
                                .replace("¥", "")
                                .replace(",", "")
                                .strip()
                            )
                            if cleaned:
                                price_val = int(float(cleaned))
                        except (ValueError, TypeError):
                            logger.debug(f"Mercari: unable to parse price '{price_text}'")

                    if price_val and (price_val < min_price or price_val > max_price):
                        continue

                    title_lower = title.lower()
                    if keywords_lower and not any(k in title_lower for k in keywords_lower):
                        continue

                    if not is_new_listing(link, seen_listings, SITE_NAME):
                        continue

                    normalized_link = normalize_url(link)
                    with _seen_listings_lock:
                        seen_listings[normalized_link] = datetime.now()

                    image_url = _extract_image_url(item)

                    _send_listing(title, link, price_val, image_url, user_id=user_id)
                    results.append({
                        "title": title,
                        "link": link,
                        "price": price_val,
                        "image": image_url,
                    })
                except Exception as exc:
                    logger.warning(f"Mercari: error parsing listing: {exc}")

            if results:
                save_seen_listings(seen_listings, SITE_NAME)
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


def run_mercari_scraper(flag_name=SITE_NAME, user_id=None):
    """Run the Mercari scraper continuously until stopped."""

    global seen_listings

    if check_recursion_guard(SITE_NAME):
        return

    set_recursion_guard(SITE_NAME, True)

    try:
        logger.info(f"Starting Mercari scraper for user {user_id}")
        seen_listings = load_seen_listings(SITE_NAME)

        try:
            while running_flags.get(flag_name, True):
                try:
                    logger.debug(f"Running Mercari scraper check for user {user_id}")
                    results = check_mercari(flag_name, user_id=user_id)
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
                    except Exception:  # pragma: no cover - fallback logging
                        print(f"ERROR: Error in Mercari scraper iteration: {exc}", file=sys.stderr, flush=True)
                    continue

                settings = load_settings(username=user_id)
                interval = settings.get("interval", 60)
                human_delay(running_flags, flag_name, interval * 0.9, interval * 1.1)

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

