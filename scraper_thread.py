import threading
import time
import sys
from selenium.webdriver.chrome.service import Service
from selenium import webdriver
from webdriver_manager.chrome import ChromeDriverManager
from utils import logger, make_chrome_driver, debug_scraper_output
from error_handling import ErrorHandler, log_errors, ScraperError, NetworkError

# PER-USER THREAD MANAGEMENT
# Format: {user_id: {scraper_name: thread}}
_threads = {}
_drivers = {}  # Format: {user_id: {scraper_name: driver}}
_thread_locks = {}  # Format: {user_id: Lock}
_scraper_errors = {}  # Format: {f"{user_id}_{scraper}": [timestamps]}
_scraper_error_messages = {}  # Format: {f"{user_id}_{scraper}": [error_dicts]}
_last_start_time = {}  # Format: {f"{user_id}_{scraper}": timestamp}

# Resource limits
MAX_SCRAPERS_PER_USER = 6  # User can run all 6 scrapers
MAX_CONCURRENT_USERS = 100  # System-wide limit

# Scraper recovery settings (Circuit Breaker Pattern)
COOLDOWN_BASE = 30  # Base cooldown period in seconds
MAX_ERRORS_PER_HOUR = 10  # Maximum errors before circuit opens
ERROR_RESET_PERIOD = 3600  # Reset error count after 1 hour

# NOTE: each scraper module exposes its own running_flags dict
from scrapers.facebook import running_flags as fb_flags, run_facebook_scraper
from scrapers.craigslist import running_flags as cl_flags, run_craigslist_scraper
from scrapers.ksl import running_flags as ksl_flags, run_ksl_scraper
from scrapers.ebay import running_flags as ebay_flags, run_ebay_scraper
from scrapers.poshmark import running_flags as poshmark_flags, run_poshmark_scraper
from scrapers.mercari import running_flags as mercari_flags, run_mercari_scraper

# ----------------------------
# RESOURCE MANAGEMENT
# ----------------------------
def get_active_scraper_count(user_id):
    """Count how many scrapers user has running"""
    if user_id not in _threads:
        return 0
    return sum(1 for thread in _threads[user_id].values() if thread.is_alive())

def get_total_active_users():
    """Count total users with active scrapers"""
    active_users = 0
    for user_id, user_threads in _threads.items():
        if any(thread.is_alive() for thread in user_threads.values()):
            active_users += 1
    return active_users

def get_total_active_scrapers():
    """Count total scrapers across all users"""
    total = 0
    for user_threads in _threads.values():
        total += sum(1 for thread in user_threads.values() if thread.is_alive())
    return total

def can_start_scraper(user_id):
    """Check if user can start another scraper"""
    user_count = get_active_scraper_count(user_id)
    total_users = get_total_active_users()
    
    if user_count >= MAX_SCRAPERS_PER_USER:
        return False, f"Maximum {MAX_SCRAPERS_PER_USER} scrapers already running"
    
    if total_users >= MAX_CONCURRENT_USERS:
        return False, f"System at capacity ({MAX_CONCURRENT_USERS} users)"
    
    return True, None

# ----------------------------
# USER INITIALIZATION
# ----------------------------
def _init_user_structures(user_id):
    """Initialize data structures for a new user"""
    if user_id not in _threads:
        _threads[user_id] = {}
    if user_id not in _drivers:
        _drivers[user_id] = {}
    if user_id not in _thread_locks:
        _thread_locks[user_id] = threading.Lock()

# ----------------------------
# CENTRALIZED DRIVER MANAGEMENT
# ----------------------------
def _create_driver(site_name, user_id):
    """Create and track a new driver for the given site and user."""
    try:
        driver = make_chrome_driver(headless=True)
        _init_user_structures(user_id)
        _drivers[user_id][site_name] = driver
        print(f"✅ Created driver for {site_name} (user: {user_id})", file=sys.stderr, flush=True)
        return driver
    except RecursionError as e:
        print(f"❌ RECURSION ERROR creating driver for {site_name} (user: {user_id}): {e}", file=sys.stderr, flush=True)
        raise ScraperError(f"Failed to create driver due to recursion: {e}")
    except (OSError, ConnectionError) as e:
        print(f"❌ Network/system error creating driver for {site_name} (user: {user_id}): {e}", file=sys.stderr, flush=True)
        raise NetworkError(f"Failed to create driver due to network/system issue: {e}")
    except Exception as e:
        print(f"❌ Failed to create driver for {site_name} (user: {user_id}): {e}", file=sys.stderr, flush=True)
        raise ScraperError(f"Failed to create driver: {e}")

def _cleanup_driver(site_name, user_id):
    """Safely cleanup driver for the given site and user."""
    if user_id in _drivers and site_name in _drivers[user_id]:
        try:
            driver = _drivers[user_id][site_name]
            if driver:
                driver.quit()
                print(f"✅ Cleaned up driver for {site_name} (user: {user_id})", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"⚠️ Error cleaning up driver for {site_name} (user: {user_id}): {e}", file=sys.stderr, flush=True)
        finally:
            _drivers[user_id].pop(site_name, None)

def _cleanup_user(user_id):
    """Cleanup all resources for a user if they have no active scrapers"""
    if user_id not in _threads:
        return
    
    # Check if user has any active scrapers
    has_active = any(thread.is_alive() for thread in _threads[user_id].values())
    if has_active:
        return
    
    # Clean up all drivers for this user
    if user_id in _drivers:
        for site_name in list(_drivers[user_id].keys()):
            _cleanup_driver(site_name, user_id)
        del _drivers[user_id]
    
    # Clean up thread references
    if user_id in _threads:
        del _threads[user_id]
    
    if user_id in _thread_locks:
        del _thread_locks[user_id]
    
    print(f"✅ Cleaned up resources for user {user_id}", file=sys.stderr, flush=True)

def _track_scraper_error(site_name, user_id):
    """Track scraper errors with circuit breaker pattern."""
    key = f"{user_id}_{site_name}"
    now = time.time()
    
    if key not in _scraper_errors:
        _scraper_errors[key] = []
    
    _scraper_errors[key].append(now)
    
    # Clean up errors older than 1 hour
    hour_ago = now - ERROR_RESET_PERIOD
    _scraper_errors[key] = [t for t in _scraper_errors[key] if t > hour_ago]
    
    error_count = len(_scraper_errors[key])
    
    if error_count >= MAX_ERRORS_PER_HOUR:
        print(f"CIRCUIT OPEN: {site_name} scraper disabled for user {user_id} ({error_count} errors)", 
              file=sys.stderr, flush=True)
        return False, error_count, 0
    
    cooldown = COOLDOWN_BASE * (2 ** min(error_count - 1, 5))
    return True, error_count, cooldown

def _handle_scraper_exception(site_name, user_id, exception, context=""):
    """Handle scraper exceptions with circuit breaker pattern."""
    key = f"{user_id}_{site_name}"
    error_message = f"{context}: {str(exception)}" if context else str(exception)
    
    if key not in _scraper_error_messages:
        _scraper_error_messages[key] = []
    _scraper_error_messages[key].append({
        'timestamp': time.time(),
        'message': error_message,
        'type': type(exception).__name__
    })
    _scraper_error_messages[key] = _scraper_error_messages[key][-10:]
    
    print(f"ERROR in {site_name} scraper (user: {user_id}) {context}: {exception}", 
          file=sys.stderr, flush=True)
    
    can_continue, error_count, cooldown = _track_scraper_error(site_name, user_id)
    
    if not can_continue:
        try:
            logger.critical(f"{site_name} scraper disabled for user {user_id} after {error_count} errors")
        except:
            pass
        return False
    
    print(f"Applying {cooldown}s cooldown for {site_name} (user: {user_id}, error {error_count}/{MAX_ERRORS_PER_HOUR})", 
          file=sys.stderr, flush=True)
    time.sleep(cooldown)
    
    return True

# ============================
# FACEBOOK SCRAPER THREADS
# ============================
def start_facebook(user_id):
    _init_user_structures(user_id)
    
    if "facebook" in _threads[user_id] and _threads[user_id]["facebook"].is_alive():
        logger.warning(f"Facebook scraper already running for user {user_id}")
        return False
    
    can_start, reason = can_start_scraper(user_id)
    if not can_start:
        logger.warning(f"Cannot start Facebook scraper for {user_id}: {reason}")
        return False
    
    fb_flags["facebook"] = True
    
    def target():
        driver = None
        retry_delay = 30
        
        while fb_flags.get("facebook", True):
            try:
                driver = _create_driver("facebook", user_id)
                if not driver:
                    time.sleep(retry_delay)
                    continue
                
                run_facebook_scraper(driver, "facebook", user_id=user_id)
                break
                
            except RecursionError as e:
                if not _handle_scraper_exception("facebook", user_id, e, "recursion error"):
                    break
            except NetworkError as e:
                if not _handle_scraper_exception("facebook", user_id, e, "network error"):
                    break
            except ScraperError as e:
                print(f"Facebook scraper error (user: {user_id}): {e}, retrying in {retry_delay}s...", file=sys.stderr, flush=True)
                time.sleep(retry_delay)
            except Exception as e:
                if not _handle_scraper_exception("facebook", user_id, e, "unexpected error"):
                    break
            finally:
                _cleanup_driver("facebook", user_id)
                driver = None
        
        _cleanup_user(user_id)
        print(f"Facebook scraper thread exiting for user {user_id}", file=sys.stderr, flush=True)
    
    t = threading.Thread(target=target, daemon=True, name=f"facebook_scraper_{user_id}")
    _threads[user_id]["facebook"] = t
    t.start()
    logger.info(f"✅ Started Facebook scraper for user {user_id}")
    return True

def stop_facebook(user_id):
    if user_id not in _threads or "facebook" not in _threads[user_id]:
        return True
    
    fb_flags["facebook"] = False
    t = _threads[user_id]["facebook"]
    if t:
        t.join(timeout=5)
        if t.is_alive():
            logger.warning(f"Facebook scraper thread did not stop gracefully for user {user_id}")
    
    _cleanup_driver("facebook", user_id)
    _cleanup_user(user_id)
    logger.info(f"🛑 Stopped Facebook scraper for user {user_id}")
    return True

def is_facebook_running(user_id):
    if user_id not in _threads or "facebook" not in _threads[user_id]:
        return False
    return _threads[user_id]["facebook"].is_alive()

# ============================
# CRAIGSLIST SCRAPER THREADS
# ============================
def start_craigslist(user_id):
    _init_user_structures(user_id)
    
    if "craigslist" in _threads[user_id] and _threads[user_id]["craigslist"].is_alive():
        logger.warning(f"Craigslist scraper already running for user {user_id}")
        return False
    
    can_start, reason = can_start_scraper(user_id)
    if not can_start:
        logger.warning(f"Cannot start Craigslist scraper for {user_id}: {reason}")
        return False
    
    cl_flags["craigslist"] = True
    
    def target():
        try:
            run_craigslist_scraper(flag_name="craigslist", user_id=user_id)
        except RecursionError as e:
            _handle_scraper_exception("craigslist", user_id, e, "recursion error")
        except Exception as e:
            _handle_scraper_exception("craigslist", user_id, e, "thread error")
        finally:
            _cleanup_user(user_id)
    
    t = threading.Thread(target=target, daemon=True, name=f"craigslist_scraper_{user_id}")
    _threads[user_id]["craigslist"] = t
    t.start()
    logger.info(f"✅ Started Craigslist scraper for user {user_id}")
    return True

def stop_craigslist(user_id):
    if user_id not in _threads or "craigslist" not in _threads[user_id]:
        return True
    
    cl_flags["craigslist"] = False
    t = _threads[user_id]["craigslist"]
    if t:
        t.join(timeout=5)
    
    _cleanup_user(user_id)
    logger.info(f"🛑 Stopped Craigslist scraper for user {user_id}")
    return True

def is_craigslist_running(user_id):
    if user_id not in _threads or "craigslist" not in _threads[user_id]:
        return False
    return _threads[user_id]["craigslist"].is_alive()

# ============================
# KSL SCRAPER THREADS
# ============================
def start_ksl(user_id):
    _init_user_structures(user_id)
    
    if "ksl" in _threads[user_id] and _threads[user_id]["ksl"].is_alive():
        logger.warning(f"KSL scraper already running for user {user_id}")
        return False
    
    can_start, reason = can_start_scraper(user_id)
    if not can_start:
        logger.warning(f"Cannot start KSL scraper for {user_id}: {reason}")
        return False
    
    ksl_flags["ksl"] = True
    
    def target():
        try:
            run_ksl_scraper(flag_name="ksl", user_id=user_id)
        except RecursionError as e:
            _handle_scraper_exception("ksl", user_id, e, "recursion error")
        except Exception as e:
            _handle_scraper_exception("ksl", user_id, e, "thread error")
        finally:
            _cleanup_user(user_id)
    
    t = threading.Thread(target=target, daemon=True, name=f"ksl_scraper_{user_id}")
    _threads[user_id]["ksl"] = t
    t.start()
    logger.info(f"✅ Started KSL scraper for user {user_id}")
    return True

def stop_ksl(user_id):
    if user_id not in _threads or "ksl" not in _threads[user_id]:
        return True
    
    ksl_flags["ksl"] = False
    t = _threads[user_id]["ksl"]
    if t:
        t.join(timeout=5)
    
    _cleanup_user(user_id)
    logger.info(f"🛑 Stopped KSL scraper for user {user_id}")
    return True

def is_ksl_running(user_id):
    if user_id not in _threads or "ksl" not in _threads[user_id]:
        return False
    return _threads[user_id]["ksl"].is_alive()

# ============================
# EBAY SCRAPER THREADS
# ============================
def start_ebay(user_id):
    _init_user_structures(user_id)
    
    if "ebay" in _threads[user_id] and _threads[user_id]["ebay"].is_alive():
        logger.warning(f"eBay scraper already running for user {user_id}")
        return False
    
    can_start, reason = can_start_scraper(user_id)
    if not can_start:
        logger.warning(f"Cannot start eBay scraper for {user_id}: {reason}")
        return False
    
    ebay_flags["ebay"] = True
    
    def target():
        try:
            run_ebay_scraper(flag_name="ebay", user_id=user_id)
        except RecursionError as e:
            _handle_scraper_exception("ebay", user_id, e, "recursion error")
        except Exception as e:
            _handle_scraper_exception("ebay", user_id, e, "thread error")
        finally:
            _cleanup_user(user_id)
    
    t = threading.Thread(target=target, daemon=True, name=f"ebay_scraper_{user_id}")
    _threads[user_id]["ebay"] = t
    t.start()
    logger.info(f"✅ Started eBay scraper for user {user_id}")
    return True

def stop_ebay(user_id):
    if user_id not in _threads or "ebay" not in _threads[user_id]:
        return True
    
    ebay_flags["ebay"] = False
    t = _threads[user_id]["ebay"]
    if t:
        t.join(timeout=5)
    
    _cleanup_user(user_id)
    logger.info(f"🛑 Stopped eBay scraper for user {user_id}")
    return True

def is_ebay_running(user_id):
    if user_id not in _threads or "ebay" not in _threads[user_id]:
        return False
    return _threads[user_id]["ebay"].is_alive()

# ============================
# POSHMARK SCRAPER THREADS
# ============================
def start_poshmark(user_id):
    _init_user_structures(user_id)
    
    if "poshmark" in _threads[user_id] and _threads[user_id]["poshmark"].is_alive():
        logger.warning(f"Poshmark scraper already running for user {user_id}")
        return False
    
    can_start, reason = can_start_scraper(user_id)
    if not can_start:
        logger.warning(f"Cannot start Poshmark scraper for {user_id}: {reason}")
        return False
    
    poshmark_flags["poshmark"] = True
    
    def target():
        try:
            run_poshmark_scraper(flag_name="poshmark", user_id=user_id)
        except RecursionError as e:
            _handle_scraper_exception("poshmark", user_id, e, "recursion error")
        except Exception as e:
            _handle_scraper_exception("poshmark", user_id, e, "thread error")
        finally:
            _cleanup_user(user_id)
    
    t = threading.Thread(target=target, daemon=True, name=f"poshmark_scraper_{user_id}")
    _threads[user_id]["poshmark"] = t
    t.start()
    logger.info(f"✅ Started Poshmark scraper for user {user_id}")
    return True

def stop_poshmark(user_id):
    if user_id not in _threads or "poshmark" not in _threads[user_id]:
        return True
    
    poshmark_flags["poshmark"] = False
    t = _threads[user_id]["poshmark"]
    if t:
        t.join(timeout=5)
    
    _cleanup_user(user_id)
    logger.info(f"🛑 Stopped Poshmark scraper for user {user_id}")
    return True

def is_poshmark_running(user_id):
    if user_id not in _threads or "poshmark" not in _threads[user_id]:
        return False
    return _threads[user_id]["poshmark"].is_alive()

# ============================
# MERCARI SCRAPER THREADS
# ============================
def start_mercari(user_id):
    _init_user_structures(user_id)
    
    if "mercari" in _threads[user_id] and _threads[user_id]["mercari"].is_alive():
        logger.warning(f"Mercari scraper already running for user {user_id}")
        return False
    
    can_start, reason = can_start_scraper(user_id)
    if not can_start:
        logger.warning(f"Cannot start Mercari scraper for {user_id}: {reason}")
        return False
    
    mercari_flags["mercari"] = True
    
    def target():
        try:
            run_mercari_scraper(flag_name="mercari", user_id=user_id)
        except RecursionError as e:
            _handle_scraper_exception("mercari", user_id, e, "recursion error")
        except Exception as e:
            _handle_scraper_exception("mercari", user_id, e, "thread error")
        finally:
            _cleanup_user(user_id)
    
    t = threading.Thread(target=target, daemon=True, name=f"mercari_scraper_{user_id}")
    _threads[user_id]["mercari"] = t
    t.start()
    logger.info(f"✅ Started Mercari scraper for user {user_id}")
    return True

def stop_mercari(user_id):
    if user_id not in _threads or "mercari" not in _threads[user_id]:
        return True
    
    mercari_flags["mercari"] = False
    t = _threads[user_id]["mercari"]
    if t:
        t.join(timeout=5)
    
    _cleanup_user(user_id)
    logger.info(f"🛑 Stopped Mercari scraper for user {user_id}")
    return True

def is_mercari_running(user_id):
    if user_id not in _threads or "mercari" not in _threads[user_id]:
        return False
    return _threads[user_id]["mercari"].is_alive()

# ============================
# GLOBAL CLEANUP FUNCTIONS
# ============================
def stop_all_scrapers(user_id=None):
    """Stop all scrapers for a user, or all users if user_id is None."""
    if user_id:
        logger.info(f"🛑 Stopping all scrapers for user {user_id}...")
        stop_facebook(user_id)
        stop_craigslist(user_id)
        stop_ksl(user_id)
        stop_ebay(user_id)
        stop_poshmark(user_id)
        stop_mercari(user_id)
        _cleanup_user(user_id)
    else:
        logger.info("🛑 Stopping all scrapers for all users...")
        for uid in list(_threads.keys()):
            stop_all_scrapers(uid)
    
    logger.info("✅ All scrapers stopped")

def get_scraper_status(user_id):
    """Get status of all scrapers for a specific user."""
    return {
        "facebook": is_facebook_running(user_id),
        "craigslist": is_craigslist_running(user_id),
        "ksl": is_ksl_running(user_id),
        "ebay": is_ebay_running(user_id),
        "poshmark": is_poshmark_running(user_id),
        "mercari": is_mercari_running(user_id)
    }

def get_system_stats():
    """Get system-wide statistics."""
    return {
        "total_users": len(_threads),
        "active_users": get_total_active_users(),
        "total_scrapers": get_total_active_scrapers(),
        "max_concurrent_users": MAX_CONCURRENT_USERS,
        "max_scrapers_per_user": MAX_SCRAPERS_PER_USER
    }

def get_scraper_health():
    """Get health information for all scrapers across all users."""
    sites = ["facebook", "craigslist", "ksl", "ebay", "poshmark", "mercari"]
    health = {}
    now = time.time()
    hour_ago = now - ERROR_RESET_PERIOD
    
    for site in sites:
        # Count active instances across all users
        active_count = 0
        total_errors = 0
        recent_errors = []
        
        for user_id in _threads.keys():
            # Check if running for this user
            if user_id in _threads and site in _threads[user_id]:
                if _threads[user_id][site].is_alive():
                    active_count += 1
            
            # Get error info for this user/site combo
            key = f"{user_id}_{site}"
            if key in _scraper_errors:
                # Count recent errors (last hour)
                recent = [t for t in _scraper_errors[key] if t > hour_ago]
                total_errors += len(recent)
                
                # Get error messages if available
                if key in _scraper_error_messages and _scraper_error_messages[key]:
                    recent_errors.extend(_scraper_error_messages[key][-3:])  # Last 3 errors
        
        health[site] = {
            "active_instances": active_count,
            "error_count_last_hour": total_errors,
            "status": "healthy" if total_errors < MAX_ERRORS_PER_HOUR else "degraded",
            "recent_errors": recent_errors[-5:]  # Keep last 5 errors across all users
        }
    
    return {
        "scrapers": health,
        "system": get_system_stats(),
        "timestamp": now
    }

# ============================
# APP HELPER FUNCTIONS
# ============================
def list_sites():
    return ["facebook", "craigslist", "ksl", "ebay", "poshmark", "mercari"]

def start_scraper(site, user_id):
    if site == "facebook":
        return start_facebook(user_id)
    elif site == "craigslist":
        return start_craigslist(user_id)
    elif site == "ksl":
        return start_ksl(user_id)
    elif site == "ebay":
        return start_ebay(user_id)
    elif site == "poshmark":
        return start_poshmark(user_id)
    elif site == "mercari":
        return start_mercari(user_id)
    return False

def stop_scraper(site, user_id):
    if site == "facebook":
        return stop_facebook(user_id)
    elif site == "craigslist":
        return stop_craigslist(user_id)
    elif site == "ksl":
        return stop_ksl(user_id)
    elif site == "ebay":
        return stop_ebay(user_id)
    elif site == "poshmark":
        return stop_poshmark(user_id)
    elif site == "mercari":
        return stop_mercari(user_id)
    return False

def running(site, user_id):
    if site == "facebook":
        return is_facebook_running(user_id)
    elif site == "craigslist":
        return is_craigslist_running(user_id)
    elif site == "ksl":
        return is_ksl_running(user_id)
    elif site == "ebay":
        return is_ebay_running(user_id)
    elif site == "poshmark":
        return is_poshmark_running(user_id)
    elif site == "mercari":
        return is_mercari_running(user_id)
    return False
