# utils.py
import os, json, logging, sys
import ipaddress
from typing import Optional
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# Increase recursion limit to prevent issues with nested operations
# Default is 1000, increase to 3000 to handle complex operations
sys.setrecursionlimit(3000)

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

def setup_logger(name="superbot", level=logging.INFO):
    """Setup logger with recursion protection"""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    
    # Prevent propagation to root logger to avoid recursion
    logger.propagate = False
    logger.setLevel(level)
    
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    
    # Add stream handler with error handling
    try:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        logger.addHandler(sh)
    except Exception as e:
        print(f"Warning: Could not setup stream handler: {e}", file=sys.stderr)
    
    # Add file handler with error handling
    try:
        fh = logging.FileHandler(LOG_DIR / f"{name}.log")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception as e:
        print(f"Warning: Could not setup file handler: {e}", file=sys.stderr)
    
    return logger

logger = setup_logger()

def is_private_ip(ip_address: str) -> bool:
    """Return True if the given IP address is private or reserved.

    This treats RFC1918, loopback, link-local, and reserved ranges as private.
    """
    try:
        ip_obj = ipaddress.ip_address(ip_address)
        return (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_reserved
            or ip_obj.is_multicast
        )
    except Exception:
        # If parsing fails, treat as private to avoid misclassification
        return True

def get_client_ip(request) -> Optional[str]:
    """Best-effort extraction of the real client IP from a proxied request.

    Preference order:
    1) First public IP in X-Forwarded-For (left-most)
    2) X-Real-IP if public
    3) request.remote_addr (may be proxy IP)

    Returns the best candidate as a string. May return a private IP if no
    public IP is available.
    """
    try:
        # Check X-Forwarded-For (may be a comma-separated list)
        xff = request.headers.get('X-Forwarded-For', '')
        if xff:
            # Keep order; pick first public IP
            for part in [p.strip() for p in xff.split(',') if p.strip()]:
                try:
                    if not is_private_ip(part):
                        return part
                except Exception:
                    continue
            # If none public, fall back to first entry
            first = xff.split(',')[0].strip()
            if first:
                return first

        # Check X-Real-IP
        xri = request.headers.get('X-Real-IP')
        if xri and not is_private_ip(xri):
            return xri

    except Exception:
        # Ignore header parsing issues and fall back below
        pass

    # Fallback to remote_addr (may be proxy)
    return getattr(request, 'remote_addr', None)

def safe_json_load(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    try:
        data = path.read_text(encoding="utf-8").strip()
        return json.loads(data) if data else default
    except Exception as e:
        logger.exception("safe_json_load failed for %s: %s", path, e)
        return default

def safe_json_write(path, data):
    try:
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as e:
        logger.exception("safe_json_write failed for %s: %s", path, e)

def make_chrome_driver(headless=True):
    opts = webdriver.ChromeOptions()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--window-size=1200,800")
    # sensible user agent (not a bypass instruction — normal practice)
    opts.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0 Safari/537.36")
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)
    return driver

def build_craigslist_url(location: str, query: str = "", category: str = "sss") -> str:
    """
    Builds a Craigslist search URL.
    location: subdomain (like 'newyork', 'boise', 'saltlakecity')
    query: search keywords
    category: Craigslist category (default: 'sss' = for sale)
    """
    base_url = f"https://{location}.craigslist.org/search/{category}"
    if query:
        base_url += f"?query={query.replace(' ', '+')}"
    return base_url

def build_ksl_url(location: str, query: str = "", category: str = "cars") -> str:
    """
    Builds a KSL search URL.
    location: text param (like 'blackfoot', 'salt-lake-city')
    query: search keywords
    category: KSL category (like 'cars', 'real-estate', etc.)
    """
    base_url = f"https://classifieds.ksl.com/search/{category}?location={location}"
    if query:
        base_url += f"&keyword={query.replace(' ', '+')}"
    return base_url

def build_facebook_url(query: str = "", latitude: float = None, longitude: float = None, radius: int = 35) -> str:
    """
    Builds a Facebook Marketplace search URL.
    query: search keywords
    latitude, longitude: coordinates of the location
    radius: search radius in miles (default 35)
    """
    base_url = "https://www.facebook.com/marketplace/"
    
    params = []
    if query:
        params.append(f"query={query.replace(' ', '%20')}")
    if latitude and longitude:
        params.append(f"latitude={latitude}&longitude={longitude}&radius={radius}")
    
    if params:
        return base_url + "?" + "&".join(params)
    return base_url

def debug_scraper_output(scraper_name: str, results: list):
    """
    Debug output for scraper results.
    scraper_name: name of the scraper (e.g., "Facebook", "Craigslist", "KSL")
    results: list of results from the scraper
    """
    if results:
        logger.info(f"[DEBUG] {scraper_name} found {len(results)} new listings")
        for result in results:
            if isinstance(result, dict):
                title = result.get('title', 'Unknown')
                link = result.get('link', 'No link')
                price = result.get('price', 'No price')
                logger.info(f"  - {title} | ${price} | {link}")
            else:
                logger.info(f"  - {result}")
    else:
        logger.info(f"[DEBUG] {scraper_name} found no new listings")

