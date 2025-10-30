# Worker Timeout Fix Summary

## Problem
Production was experiencing critical worker timeouts on the `/login` endpoint:
- Request took 30,769ms (30.7 seconds)
- Worker timeout set to 30 seconds
- Worker killed with SIGKILL, possibly out of memory
- MonkeyPatchWarning about gevent SSL import order

## Root Cause
The issue was caused by **blocking database operations** during login:

1. **Security Middleware Blocking**: The `log_security_event()` function was using synchronous database writes with retry logic that could take 30+ seconds during database locks
2. **Login Activity Logging Blocking**: Multiple database writes during login (`update_user_login_and_log_activity()`, `log_user_activity()`) were blocking the request
3. **Gevent Monkey-Patch Order**: SSL was being imported before gevent patched it, causing compatibility issues
4. **Worker Timeout Too Low**: 30-second timeout wasn't sufficient for database operations under high load

## Solutions Implemented

### 1. Non-Blocking Security Event Logging
**File**: `security_middleware.py`

- Created async logging queue (`_security_log_queue`) with 1000 event capacity
- Implemented background worker thread (`_security_logger_worker()`) to process events
- Modified `log_security_event()` to queue events without blocking (uses `put_nowait()`)
- Events are processed in background with retry logic, no impact on request latency

**Benefits**:
- Login requests no longer blocked by security logging
- Failed logs don't impact user experience
- Queue prevents memory issues with bounded size

### 2. Non-Blocking Activity Logging
**File**: `db_enhanced.py`

- Created async activity queue (`_activity_log_queue`) with 2000 event capacity
- Implemented background worker thread (`_activity_logger_worker()`) to process login/activity logs
- Split functions into sync (`_update_user_login_and_log_activity_sync()`, `_log_user_activity_sync()`) and async versions
- Public APIs now queue operations without blocking

**Benefits**:
- Login completes immediately, logging happens in background
- Retry logic doesn't block request thread
- Higher queue capacity (2000) handles burst traffic

### 3. Fixed Gevent Monkey-Patching
**File**: `wsgi.py`

- Added gevent monkey-patch **BEFORE** any other imports
- Fixes SSL import order warning
- Ensures proper async operation with gevent worker

**Before**:
```python
import os
from app import app
```

**After**:
```python
try:
    from gevent import monkey
    monkey.patch_all()
except ImportError:
    pass

import os
from app import app
```

### 4. Increased Worker Timeout
**File**: `gunicorn_config.py`

- Increased worker timeout from 30s to 60s
- Increased graceful timeout from 15s to 30s
- Provides buffer for legitimate slow operations

## Performance Impact

### Before
- Login requests: 30+ seconds (timeout)
- Workers killed frequently
- Poor user experience

### After
- Login requests: < 500ms (estimated)
- Background logging: doesn't impact UX
- Workers remain stable

## Monitoring Recommendations

1. **Check Queue Sizes**: Monitor `_security_log_queue` and `_activity_log_queue` sizes
   - If frequently full, increase capacity or optimize database
   
2. **Worker Thread Health**: Ensure background threads are running
   - Check logs for "Security logger worker started" and "Activity logger worker started"

3. **Database Performance**: If queues fill up, investigate database locking
   - Consider increasing `CONNECTION_TIMEOUT` in `db_enhanced.py`
   - Review `POOL_SIZE` for connection pool

4. **Failed Log Warnings**: Watch for "Queue full" warnings in logs
   - Indicates high load or slow database
   - May need to scale database or increase pool size

## Testing Checklist

- [ ] Login completes in < 1 second
- [ ] No worker timeouts in logs
- [ ] Security events logged in database (check security_events table)
- [ ] User activity logged in database (check user_activity table)
- [ ] No gevent monkey-patch warnings
- [ ] Background threads start on application startup

## Rollback Plan

If issues arise, revert these commits and:
1. Restore synchronous logging (remove queue/thread code)
2. Increase worker timeout to 120s as temporary fix
3. Investigate database optimization separately

## Related Files Modified

1. `security_middleware.py` - Async security logging
2. `db_enhanced.py` - Async activity logging
3. `wsgi.py` - Gevent monkey-patch fix
4. `gunicorn_config.py` - Timeout adjustments

## Next Steps

Consider these future optimizations:
1. Migrate to PostgreSQL for better concurrency (SQLite has limitations)
2. Add Redis for session/cache storage
3. Implement connection pooling with pgbouncer
4. Add APM (Application Performance Monitoring) for real-time metrics

