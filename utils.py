# utils.py
import os, json, logging, sys
import ipaddress
from typing import Optional
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# Keep default recursion limit - increasing it masks the real problem
# Default is 1000 which is appropriate for proper code
# If we hit recursion errors, we need to fix the code, not increase the limit

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

def setup_logger(name="superbot", level=logging.INFO):
    """Setup logger with recursion protection and fail-safe design"""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    
    # Prevent propagation to root logger to avoid recursion
    logger.propagate = False
    logger.setLevel(level)
    
    # Use a simpler format to reduce complexity
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", 
                           datefmt="%Y-%m-%d %H:%M:%S")
    
    # Add stream handler with error handling - fail silently
    try:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        sh.setLevel(level)
        logger.addHandler(sh)
    except Exception as e:
        # Don't use logger here - would cause recursion
        print(f"Warning: Could not setup stream handler: {e}", file=sys.stderr, flush=True)
    
    # Add file handler with error handling - fail silently
    try:
        log_file = LOG_DIR / f"{name}.log"
        fh = logging.FileHandler(log_file, mode='a', encoding='utf-8')
        fh.setFormatter(fmt)
        fh.setLevel(level)
        logger.addHandler(fh)
    except Exception as e:
        # Don't use logger here - would cause recursion
        print(f"Warning: Could not setup file handler: {e}", file=sys.stderr, flush=True)
    
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
    """Create a Chrome WebDriver with proper configuration for various environments."""
    opts = webdriver.ChromeOptions()
    
    # Headless mode
    if headless:
        opts.add_argument("--headless=new")
    
    # Essential arguments for server/Docker environments
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")  # Overcome limited resource problems
    opts.add_argument("--disable-software-rasterizer")
    opts.add_argument("--window-size=1200,800")
    
    # User agent
    opts.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0 Safari/537.36")
    
    # Additional stability options
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-setuid-sandbox")
    opts.add_argument("--single-process")  # Helps in containerized environments
    opts.add_argument("--disable-infobars")
    opts.add_argument("--disable-notifications")
    
    # Try to find Chrome/Chromium binary in common locations
    chrome_paths = [
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
        "/snap/bin/chromium",
        "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
        "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
        os.environ.get("CHROME_BIN"),  # Environment variable (Render/Heroku)
    ]
    
    # Try to detect Chrome binary location
    chrome_binary = None
    for path in chrome_paths:
        if path and Path(path).exists():
            chrome_binary = path
            logger.info(f"Found Chrome binary at: {path}")
            break
    
    if chrome_binary:
        opts.binary_location = chrome_binary
    else:
        logger.warning("Chrome binary not found in common locations, relying on default detection")
    
    try:
        # Try to install and use ChromeDriver
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=opts)
        logger.info("✅ Successfully created Chrome WebDriver")
        return driver
    except Exception as e:
        # If ChromeDriverManager fails, try without service (system chromedriver)
        logger.warning(f"ChromeDriverManager failed ({e}), trying system chromedriver...")
        try:
            driver = webdriver.Chrome(options=opts)
            logger.info("✅ Successfully created Chrome WebDriver using system chromedriver")
            return driver
        except Exception as e2:
            logger.error(f"Failed to create Chrome WebDriver: {e2}")
            raise

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

