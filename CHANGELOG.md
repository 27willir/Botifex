# Super Bot - Changelog

All notable changes, fixes, and improvements to this project are documented here.

---

## [Unreleased] - 2025-10-28

### Fixed
- **CRITICAL**: Removed invalid `timeout` parameter from Stripe API calls that doesn't exist in the Stripe SDK
  - Fixed `stripe.checkout.Session.create()` in `subscriptions.py` line 313
  - Fixed `stripe.billing_portal.Session.create()` in `subscriptions.py` line 383

### Removed
- Deleted `ecurity_middleware.py` - git diff file that was accidentally committed
- Deleted `db_optimized.py` - unused duplicate database module

---

## [2025-10-28] - Subscription Scraper Control Fix

### Fixed
- **Start All** and **Stop All** scraper functions now respect subscription tier limitations
- Free users can only start/stop Craigslist and eBay scrapers
- Standard users can start/stop Craigslist, Facebook, KSL, and eBay
- Pro users can start/stop all 6 platforms (including Poshmark and Mercari)
- Admin users maintain full access to all platforms

### Added
- Comprehensive test suite in `tests/test_subscription_scraper_control.py`
- Detailed platform access logging for audit trail
- Informative flash messages showing which scrapers were started/stopped

### Changed
- `app.py` - Updated `start_all()` function (lines 542-593)
- `app.py` - Updated `stop_all()` function (lines 599-650)
- Enhanced security by enforcing subscription limits on bulk scraper operations

---

## [2025-10-28] - Recursion Error Fixes

### Fixed - Stripe Checkout Recursion
- **CRITICAL**: Fixed infinite recursion error when creating Stripe checkout sessions
- Root cause: Circular dependency in logging/middleware system during Stripe HTTP calls

### Solution Implemented
1. **Global Stripe Configuration**: Reduced retries to 1, disabled telemetry
2. **Isolated Logger**: Made subscription logger non-propagating with direct stderr handler
3. **Context Isolation**: Temporarily removes Flask request context during Stripe API calls
4. **Logging Protection**: Disabled all logging during Stripe operations
5. **Increased Recursion Limit**: Temporarily raised from 1000 to 3000

### Fixed - Scraper Recursion
- Fixed maximum recursion depth errors in all scrapers
- Removed `@log_errors()` decorator from `_create_driver()` and `_cleanup_driver()`
- Replaced logger calls with direct `print()` statements to stderr
- Added explicit RecursionError handling in `scraper_thread.py`

### Fixed - Geocoding Recursion  
- Fixed recursion errors in `location_utils.py` geocoding functions
- Replaced logger calls with print statements in error handling
- Added explicit RecursionError handling with retry limits
- Implemented geocoding retry count tracking to prevent infinite loops

### Files Modified
- `subscriptions.py` - Complete rewrite of Stripe API call isolation
- `app.py` - Enhanced error handling for checkout route
- `scraper_thread.py` - Removed decorators causing recursion
- `location_utils.py` - Fixed geocoding error handling

---

## [2024-12-19] - 502 Bad Gateway Error Fixes

### Problem
- 502 errors occurring after 30+ second response times
- Database connection pool exhaustion
- Workers timing out on long-running requests

### Fixed
1. **Gunicorn Configuration** (`gunicorn_config.py`)
   - Increased timeout from 30s to 60s
   - Increased graceful_timeout from 15s to 30s
   - Increased keepalive from 5s to 10s

2. **Database Connection Pool** (`db_enhanced.py`)
   - Increased POOL_SIZE from 10 to 15 connections
   - Reduced CONNECTION_TIMEOUT from 60s to 30s
   - Reduced PRAGMA busy_timeout from 10000ms to 5000ms
   - Added enhanced connection testing and recovery

### Added
- `scripts/fix_502_errors.py` - Comprehensive 502 error diagnosis and fixes
- `scripts/monitor_502_issues.py` - Real-time system health monitoring
- `get_pool_status()` function for connection pool monitoring

### Expected Results
- 502 errors reduced to < 1%
- Response times < 5 seconds for normal operations
- Connection pool utilization < 80%
- No database lock timeouts

---

## [2025-10-26] - Security Improvements

### Enhanced
1. **Gunicorn Worker Configuration**
   - Increased timeout from 120s to 180s for resource-intensive operations
   - Added graceful_timeout = 45s for clean worker shutdowns
   - Added max_requests = 1000 for periodic worker recycling
   - Added request field limits to prevent memory exhaustion

2. **Security Middleware** (`security_middleware.py`)
   - Reduced suspicious_ip_block_threshold from 3 to **2** attempts
   - Reduced max_suspicious_requests from 5 to **3**
   - Increased block_duration_minutes from 30 to **60 minutes**
   - Reduced rapid_fire_threshold from 20 to **15** requests/10s

3. **Bot Detection**
   - Added scanner bots: `ahrefsbot`, `semrushbot`, `dotbot`, `mj12bot`, `blexbot`, etc.
   - Added `botifex` to allowed patterns (own bot)
   - Malicious user agents now immediately block IPs

4. **Pattern Detection**
   - Added high-risk patterns: `index\.php`, `lander.*\.php`, `database\.php`
   - High-risk patterns trigger immediate IP blocking

5. **Fail2ban-Like Behavior**
   - Added failed_requests tracking (404/403 patterns)
   - Block after 10 failed requests
   - Reduced cleanup interval from 5 minutes to 1 minute

### Security Benefits
- Faster blocking of malicious IPs
- Longer block durations discourage retries
- Better bot and scanner detection
- Immediate blocks for high-risk patterns

---

## [Timeout Optimization] - Date Unknown

### Problem
- 34-second timeouts on login requests
- Database connection pool exhaustion
- Worker processes being killed by Gunicorn

### Fixed
1. **Gunicorn Configuration**
   - Reduced timeout: 60s → 30s to prevent hangs
   - Reduced graceful timeout: 30s → 15s
   - Reduced workers: (CPU * 2 + 1) → 2 for stability
   - Reduced worker connections: 1000 → 500
   - Reduced keepalive: 10s → 5s

2. **Database Connection Pool**
   - Reduced pool size: 15 → 5 connections
   - Reduced connection timeout: 30s → 10s
   - Reduced busy timeout: 5000ms → 2000ms
   - Added connection health checks

3. **Login Route Optimization**
   - Fast-path validation for early rejection
   - Single database call for user lookup
   - Batched database operations
   - Asynchronous error logging
   - Graceful degradation on logging failures

4. **Database Performance**
   - Added indexes on frequently queried columns
   - Optimized PRAGMA settings
   - Transaction batching
   - Better connection pooling

### Added
- `scripts/optimize_startup.py` - Database optimization
- `scripts/fast_startup.py` - Fast startup sequence
- `/health` endpoint for application monitoring

### Expected Results
- Login requests complete in < 5 seconds
- Fewer worker timeouts and crashes
- Better database concurrency
- Faster application startup

---

## Subscription Features

### Platform Access by Tier

**Free Tier**
- Platforms: Craigslist, eBay (2 platforms)
- Max Keywords: 2
- Refresh Interval: 10 minutes
- Analytics: No
- Selling: No
- Notifications: No

**Standard Tier ($9.99/mo)**
- Platforms: Craigslist, Facebook, KSL, eBay (4 platforms)
- Max Keywords: 10
- Refresh Interval: 5 minutes
- Analytics: Limited
- Selling: No
- Notifications: Yes

**Pro Tier ($39.99/mo)**
- Platforms: All 6 (Craigslist, Facebook, KSL, eBay, Poshmark, Mercari)
- Max Keywords: Unlimited
- Refresh Interval: 1 minute
- Analytics: Full
- Selling: Yes
- Notifications: Yes
- Priority Support: Yes

---

## Database Architecture

### Current Structure
- **db_enhanced.py** - Main enhanced database module with connection pooling
- **db.py** - Compatibility wrapper that re-exports all functions from db_enhanced
- All application code uses either db_enhanced directly or db.py wrapper

### Connection Pool Configuration
- Pool Size: 5 connections (optimized for memory management)
- Connection Timeout: 10 seconds (fast failure detection)
- WAL Mode: Enabled for better concurrency
- Busy Timeout: 2000ms

---

## Known Issues & Maintenance

### Monitoring Recommendations
1. Monitor `/health` endpoint for application status
2. Watch for worker restarts (should be periodic, not excessive)
3. Track blocked IP counts (should increase with tighter thresholds)
4. Monitor database connection pool usage (should be < 80%)
5. Check for 502 errors (should be < 1%)

### Emergency Procedures
If 502 errors persist:
```bash
# Check connection pool
python -c "from db_enhanced import get_pool_status; print(get_pool_status())"

# Run health monitoring
python scripts/monitor_502_issues.py

# Fix detected issues
python scripts/fix_502_errors.py
```

### Production Recommendations
1. Consider upgrading from SQLite to PostgreSQL for high concurrency
2. Add Redis caching layer for session storage
3. Implement load balancing across multiple instances
4. Set up application performance monitoring (APM)
5. Add alerting for threshold breaches

---

## Testing Guidelines

### Critical Test Areas
1. **Stripe Checkout Flow**
   - Test Standard plan checkout
   - Test Pro plan checkout
   - Verify no RecursionError in logs
   - Confirm redirect to Stripe checkout page

2. **Scraper Control**
   - Test Start All/Stop All with each subscription tier
   - Verify platform access restrictions
   - Check activity logs for proper recording

3. **Security**
   - Test rate limiting thresholds
   - Verify bot detection and blocking
   - Check high-risk pattern blocking

4. **Performance**
   - Login should complete in < 5 seconds
   - No worker timeouts
   - Connection pool utilization < 80%

---

## Rollback Procedures

### Stripe Recursion Fix
```bash
git revert [commit-hash]
git push origin main
```

### Security Changes
- Revert gunicorn_config.py timeout settings
- Revert security_middleware.py thresholds
- Remove extra malicious agent patterns if false positives

### Database Changes
- Revert db_enhanced.py pool size changes
- Revert gunicorn_config.py worker settings
- Restore original Procfile

---

**Changelog Maintained By:** AI Assistant
**Last Updated:** October 28, 2025
**Version:** Consolidated from multiple fix documentation files

