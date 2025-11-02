# Scraper Recursion & Stability Fixes

## Date: October 30, 2025

## Issues Identified

### 1. **Maximum Recursion Depth Exceeded**
The scrapers (especially eBay and Craigslist) were hitting maximum recursion depth errors due to:
- Nested error handling with logging
- `@log_errors()` decorator applied to functions that already used `logger` internally
- Increased recursion limit (3000) was masking the problem instead of fixing it

### 2. **Circular Logging Dependencies**
Functions decorated with `@log_errors()` that also called `logger.error()` internally created a circular dependency:
```
Function with @log_errors() → Error occurs → Decorator logs → Logger fails → Decorator tries to log failure → Infinite loop
```

### 3. **Unstable Error Handling**
- No exponential backoff for repeated errors
- Fixed cooldown period regardless of error frequency
- No circuit breaker to prevent cascading failures

## Changes Made

### 1. Fixed `utils.py` - Logger Setup
**Before:**
```python
sys.setrecursionlimit(3000)  # BAD: Masks the problem
```

**After:**
```python
# Keep default recursion limit (1000)
# If we hit recursion errors, fix the code, don't increase the limit
```

**Improvements:**
- Removed artificially high recursion limit
- Enhanced logger setup with better error handling
- Added flush=True to stderr outputs
- Simplified log format to reduce complexity

### 2. Enhanced `error_handling.py` - Log Errors Decorator
**Before:**
```python
@log_errors()
def log_errors(logger_instance=None):
    # Could create recursion if logging fails
```

**After:**
```python
@log_errors()
def log_errors(logger_instance=None):
    """
    WARNING: Do NOT use this decorator on functions that already use logger internally.
    """
    # Added RecursionError handling
    # Improved nested error detection
    # Reduced logging complexity
```

**Improvements:**
- Special handling for `RecursionError` exceptions
- Better recursion guard with `_error_handling_lock.in_error_handler`
- Removed debug traceback logging to reduce nested calls
- Direct stderr output if logging fails

### 3. Fixed All Scraper Files
**Removed `@log_errors()` decorator from functions that already handle their own logging:**

#### Files Modified:
- `scrapers/ebay.py`
- `scrapers/craigslist.py`
- `scrapers/facebook.py`
- `scrapers/ksl.py`
- `scrapers/mercari.py`
- `scrapers/poshmark.py`

#### Functions Fixed:
```python
# BEFORE: Decorator + internal logging = recursion risk
@log_errors()
def save_seen_listings(filename):
    try:
        # ... code ...
        logger.debug("Saved listings")
    except Exception as e:
        logger.error(f"Error: {e}")
        raise

# AFTER: No decorator, just proper error handling
def save_seen_listings(filename):
    try:
        # ... code ...
        logger.debug("Saved listings")
    except Exception as e:
        logger.error(f"Error: {e}")
        # Don't raise - let function fail gracefully
```

Functions fixed in each scraper:
- `save_seen_listings()` - removed decorator, removed raise
- `load_seen_listings()` - removed decorator
- `send_discord_message()` - removed decorator, removed raise (Facebook only)
- `check_facebook()` - removed decorator (Facebook only)
- `run_*_scraper()` - removed decorator (Facebook only)

### 4. Enhanced Circuit Breaker Pattern in `scraper_thread.py`

**Before:**
- Fixed 30-second cooldown
- Simple error counting
- No exponential backoff

**After:**
```python
# Circuit Breaker Pattern with Exponential Backoff
COOLDOWN_BASE = 30  # Base: 30s
MAX_ERRORS_PER_HOUR = 10  # Open circuit after 10 errors
ERROR_RESET_PERIOD = 3600  # Reset after 1 hour

# Exponential backoff:
# Error 1: 30s cooldown
# Error 2: 60s cooldown
# Error 3: 120s cooldown
# Error 4: 240s cooldown
# Error 5+: 960s cooldown (capped)
```

**Improvements:**
- Exponential backoff based on error count
- Circuit opens (disables scraper) after MAX_ERRORS_PER_HOUR
- Errors reset after 1 hour of no issues
- Better logging with circuit breaker states
- Graceful degradation instead of crashes

## How to Verify the Fixes

### 1. Start the Scrapers
```bash
python app.py
```

### 2. Monitor for Recursion Errors
Check logs for:
- ✅ No "maximum recursion depth exceeded" errors
- ✅ Proper error messages with context
- ✅ Circuit breaker messages if errors occur
- ✅ Exponential backoff cooldown messages

### 3. Check Log Files
```bash
tail -f logs/superbot.log
```

Look for:
- Clean startup messages
- Proper error handling without stack traces
- Circuit breaker status messages

### 4. Test Error Recovery
Temporarily break a scraper (e.g., invalid URL) and verify:
1. First error: 30s cooldown
2. Second error: 60s cooldown
3. Third error: 120s cooldown
4. After 10 errors: Circuit opens, scraper stops
5. After 1 hour: Error count resets

## Best Practices Going Forward

### ❌ DON'T:
```python
# DON'T use @log_errors() on functions that use logger internally
@log_errors()
def my_function():
    logger.info("Starting...")  # ❌ Creates recursion risk
    logger.error("Failed!")     # ❌ Creates recursion risk

# DON'T increase recursion limit to hide problems
sys.setrecursionlimit(5000)  # ❌ Masks the real issue

# DON'T create nested error handlers
try:
    try:
        logger.error("Error")
    except:
        logger.error("Error in error handler")  # ❌ Recursion
except:
    logger.error("Error in error in error handler")  # ❌ Deep recursion
```

### ✅ DO:
```python
# DO use @log_errors() on simple functions without logging
@log_errors()
def calculate_distance(lat1, lon1, lat2, lon2):
    # No logger calls here - decorator will log errors
    return math.sqrt((lat2-lat1)**2 + (lon2-lon1)**2)

# DO handle errors explicitly in functions that use logger
def save_data():
    try:
        # ... save logic ...
        logger.info("Saved successfully")
    except Exception as e:
        logger.error(f"Save failed: {e}")
        # Return a default value or fail gracefully
        return False

# DO use stderr for critical errors
try:
    critical_operation()
except RecursionError as e:
    print(f"RECURSION ERROR: {e}", file=sys.stderr, flush=True)
    # Don't try to log recursion errors!

# DO use circuit breaker pattern for external services
def scrape_website():
    if error_count > MAX_ERRORS:
        print("Circuit open - skipping", file=sys.stderr)
        return []
    # ... scraping logic ...
```

## Testing Checklist

- [x] Remove increased recursion limit from utils.py
- [x] Enhance logger setup with fail-safe design
- [x] Improve log_errors decorator with recursion protection
- [x] Remove @log_errors from all scraper helper functions
- [x] Implement exponential backoff in circuit breaker
- [x] Add proper stderr logging for critical errors
- [x] Test error recovery with cooldown
- [x] Verify circuit breaker opens after max errors

## Expected Behavior After Fixes

### Normal Operation:
```
2025-10-30 10:00:00 [INFO] Starting eBay scraper
2025-10-30 10:00:05 [INFO] eBay scraper found 3 new listings
2025-10-30 10:01:00 [INFO] eBay scraper found 0 new listings
```

### Error with Recovery:
```
2025-10-30 10:00:00 [INFO] Starting eBay scraper
2025-10-30 10:00:05 [ERROR] Error in eBay scraper iteration: Connection timeout
Applying 30s cooldown for ebay scraper (error 1/10)
2025-10-30 10:00:35 [INFO] eBay scraper resumed after cooldown
```

### Circuit Breaker Activation:
```
2025-10-30 10:00:00 [INFO] Starting Craigslist scraper
2025-10-30 10:00:05 [ERROR] Error in Craigslist scraper: Invalid response
Applying 30s cooldown for craigslist scraper (error 1/10)
2025-10-30 10:01:00 [ERROR] Error in Craigslist scraper: Invalid response
Applying 60s cooldown for craigslist scraper (error 2/10)
... (more errors) ...
2025-10-30 10:05:00 [ERROR] Error in Craigslist scraper: Invalid response
CIRCUIT OPEN: craigslist scraper disabled (10 errors in last hour)
2025-10-30 10:05:00 [CRITICAL] craigslist scraper disabled after 10 errors in last hour
```

## Files Modified

1. `utils.py` - Fixed recursion limit and logger setup
2. `error_handling.py` - Enhanced log_errors decorator
3. `scrapers/ebay.py` - Removed problematic decorators
4. `scrapers/craigslist.py` - Removed problematic decorators
5. `scrapers/facebook.py` - Removed problematic decorators
6. `scrapers/ksl.py` - Removed problematic decorators
7. `scrapers/mercari.py` - Removed problematic decorators
8. `scrapers/poshmark.py` - Removed problematic decorators
9. `scraper_thread.py` - Enhanced circuit breaker pattern

## Summary

The recursion errors were caused by nested error handling where the `@log_errors()` decorator was applied to functions that already used `logger` internally. When an error occurred in logging, the decorator would try to log it, creating infinite recursion.

The fixes involve:
1. **Removing the problematic decorator** from functions that handle their own logging
2. **Keeping the default recursion limit** instead of masking problems
3. **Implementing a circuit breaker** with exponential backoff for stability
4. **Using stderr for critical errors** to avoid logging recursion

These changes make the scrapers much more stable and resilient to errors, with proper graceful degradation instead of crashes.

