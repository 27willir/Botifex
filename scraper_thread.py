import threading
import time
from utils import logger, make_chrome_driver, debug_scraper_output, is_selenium_available
from error_handling import ErrorHandler, log_errors, ScraperError, NetworkError

# Make selenium imports optional
try:
    from selenium.webdriver.chrome.service import Service
    from selenium import webdriver
    from webdriver_manager.chrome import ChromeDriverManager
except ImportError:
    pass  # Selenium not available

# make sure this exists
_threads = {}
_drivers = {}  # Track active drivers
_thread_locks = {}  # Thread safety locks

# NOTE: each scraper module exposes its own running_flags dict
from scrapers.facebook import running_flags as fb_flags, run_facebook_scraper
from scrapers.craigslist import running_flags as cl_flags, run_craigslist_scraper
from scrapers.ksl import running_flags as ksl_flags, run_ksl_scraper
from scrapers.ebay import running_flags as ebay_flags, run_ebay_scraper

# ----------------------------
# CENTRALIZED DRIVER MANAGEMENT
# ----------------------------
@log_errors()
def _create_driver(site_name):
    """Create and track a new driver for the given site."""
    try:
        driver = make_chrome_driver(headless=True)
        _drivers[site_name] = driver
        _thread_locks[site_name] = threading.Lock()
        logger.info(f"✅ Created driver for {site_name}")
        return driver
    except (OSError, ConnectionError) as e:
        logger.error(f"❌ Network/system error creating driver for {site_name}: {e}")
        raise NetworkError(f"Failed to create driver due to network/system issue: {e}")
    except Exception as e:
        logger.error(f"❌ Failed to create driver for {site_name}: {e}")
        raise ScraperError(f"Failed to create driver: {e}")

@log_errors()
def _cleanup_driver(site_name):
    """Safely cleanup driver for the given site."""
    if site_name in _drivers:
        try:
            driver = _drivers[site_name]
            if driver:
                driver.quit()
                logger.info(f"✅ Cleaned up driver for {site_name}")
        except (OSError, ConnectionError) as e:
            logger.warning(f"⚠️ Network error cleaning up driver for {site_name}: {e}")
        except Exception as e:
            logger.error(f"⚠️ Error cleaning up driver for {site_name}: {e}")
        finally:
            _drivers.pop(site_name, None)
            _thread_locks.pop(site_name, None)

def _cleanup_all_drivers():
    """Cleanup all active drivers."""
    for site_name in list(_drivers.keys()):
        _cleanup_driver(site_name)

def _get_driver_lock(site_name):
    """Get thread lock for the given site."""
    return _thread_locks.get(site_name)

# ============================
# FACEBOOK SCRAPER THREADS
# ============================
def start_facebook():
    if not is_selenium_available():
        logger.warning("⚠️ Facebook scraper requires Selenium which is not available in this environment")
        return False
    
    if "facebook" in _threads and _threads["facebook"].is_alive():
        logger.warning("Facebook scraper is already running")
        return False
    
    fb_flags["facebook"] = True
    
    def target():
        driver = None
        try:
            # Create driver with proper error handling
            driver = _create_driver("facebook")
            if not driver:
                logger.error("Failed to create driver for Facebook scraper")
                return
            
            # Run scraper with timeout protection
            run_facebook_scraper(driver, "facebook")
            
        except NetworkError as e:
            logger.error(f"Facebook scraper network error: {e}")
        except ScraperError as e:
            logger.error(f"Facebook scraper error: {e}")
        except Exception as e:
            logger.error(f"Facebook scraper unexpected error: {e}")
        finally:
            # Always cleanup driver
            _cleanup_driver("facebook")
    
    t = threading.Thread(target=target, daemon=True, name="facebook_scraper")
    _threads["facebook"] = t
    t.start()
    logger.info("✅ Started Facebook scraper thread")
    return True

def stop_facebook():
    fb_flags["facebook"] = False
    t = _threads.get("facebook")
    if t:
        t.join(timeout=5)  # Give more time for graceful shutdown
        if t.is_alive():
            logger.warning("Facebook scraper thread did not stop gracefully")
    # Always cleanup driver regardless of thread status
    _cleanup_driver("facebook")
    logger.info("🛑 Stopped Facebook scraper")
    return True

def is_facebook_running():
    t = _threads.get("facebook")
    return t.is_alive() if t else False

# ============================
# CRAIGSLIST SCRAPER THREADS
# ============================
def start_craigslist():
    if "craigslist" in _threads and _threads["craigslist"].is_alive():
        logger.warning("Craigslist scraper is already running")
        return False
    
    cl_flags["craigslist"] = True
    
    def target():
        try:
            logger.info("Starting Craigslist scraper")
            run_craigslist_scraper(flag_name="craigslist")
        except Exception as e:
            logger.error(f"Craigslist scraper thread error: {e}")
        finally:
            logger.info("Craigslist scraper thread finished")
    
    t = threading.Thread(target=target, daemon=True, name="craigslist_scraper")
    _threads["craigslist"] = t
    t.start()
    logger.info("✅ Started Craigslist scraper thread")
    return True

def stop_craigslist():
    cl_flags["craigslist"] = False
    t = _threads.get("craigslist")
    if t:
        t.join(timeout=5)  # Give more time for graceful shutdown
        if t.is_alive():
            logger.warning("Craigslist scraper thread did not stop gracefully")
    logger.info("🛑 Stopped Craigslist scraper")
    return True

def is_craigslist_running():
    t = _threads.get("craigslist")
    return t.is_alive() if t else False

# ============================
# KSL SCRAPER THREADS
# ============================
def start_ksl():
    if "ksl" in _threads and _threads["ksl"].is_alive():
        logger.warning("KSL scraper is already running")
        return False
    
    ksl_flags["ksl"] = True
    
    def target():
        try:
            logger.info("Starting KSL scraper")
            run_ksl_scraper(flag_name="ksl")
        except Exception as e:
            logger.error(f"KSL scraper thread error: {e}")
        finally:
            logger.info("KSL scraper thread finished")
    
    t = threading.Thread(target=target, daemon=True, name="ksl_scraper")
    _threads["ksl"] = t
    t.start()
    logger.info("✅ Started KSL scraper thread")
    return True

def stop_ksl():
    ksl_flags["ksl"] = False
    t = _threads.get("ksl")
    if t:
        t.join(timeout=5)  # Give more time for graceful shutdown
        if t.is_alive():
            logger.warning("KSL scraper thread did not stop gracefully")
    logger.info("🛑 Stopped KSL scraper")
    return True

def is_ksl_running():
    t = _threads.get("ksl")
    return t.is_alive() if t else False

# ============================
# EBAY SCRAPER THREADS
# ============================
def start_ebay():
    if "ebay" in _threads and _threads["ebay"].is_alive():
        logger.warning("eBay scraper is already running")
        return False
    
    ebay_flags["ebay"] = True
    
    def target():
        try:
            logger.info("Starting eBay scraper")
            run_ebay_scraper(flag_name="ebay")
        except Exception as e:
            logger.error(f"eBay scraper thread error: {e}")
        finally:
            logger.info("eBay scraper thread finished")
    
    t = threading.Thread(target=target, daemon=True, name="ebay_scraper")
    _threads["ebay"] = t
    t.start()
    logger.info("✅ Started eBay scraper thread")
    return True

def stop_ebay():
    ebay_flags["ebay"] = False
    t = _threads.get("ebay")
    if t:
        t.join(timeout=5)  # Give more time for graceful shutdown
        if t.is_alive():
            logger.warning("eBay scraper thread did not stop gracefully")
    logger.info("🛑 Stopped eBay scraper")
    return True

def is_ebay_running():
    t = _threads.get("ebay")
    return t.is_alive() if t else False

# ============================
# GLOBAL CLEANUP FUNCTIONS
# ============================
def stop_all_scrapers():
    """Stop all running scrapers and cleanup resources."""
    logger.info("🛑 Stopping all scrapers...")
    
    # Stop all scrapers
    stop_facebook()
    stop_craigslist()
    stop_ksl()
    stop_ebay()
    
    # Cleanup all drivers
    _cleanup_all_drivers()
    
    logger.info("✅ All scrapers stopped and resources cleaned up")

def get_scraper_status():
    """Get status of all scrapers."""
    return {
        "facebook": is_facebook_running(),
        "craigslist": is_craigslist_running(),
        "ksl": is_ksl_running(),
        "ebay": is_ebay_running()
    }

# ============================
# APP HELPER FUNCTIONS
# ============================
def list_sites():
    return ["facebook","craigslist","ksl","ebay"]

# Generic functions for app.py
def start_scraper(site):
    if site == "facebook":
        return start_facebook()
    elif site == "craigslist":
        return start_craigslist()
    elif site == "ksl":
        return start_ksl()
    elif site == "ebay":
        return start_ebay()
    return False

def stop_scraper(site):
    if site == "facebook":
        return stop_facebook()
    elif site == "craigslist":
        return stop_craigslist()
    elif site == "ksl":
        return stop_ksl()
    elif site == "ebay":
        return stop_ebay()
    return False

def running(site):
    if site == "facebook":
        return is_facebook_running()
    elif site == "craigslist":
        return is_craigslist_running()
    elif site == "ksl":
        return is_ksl_running()
    elif site == "ebay":
        return is_ebay_running()
    return False
