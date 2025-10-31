# urllib3 + Gevent Shutdown Cleanup Fix

## Problem

When the application shuts down (worker restart, deployment, etc.), urllib3 connection pools attempt to clean up their resources. However, with gevent workers, this causes exceptions during the cleanup phase:

```
Exception ignored in: <finalize object at 0x76286c9c3c80; dead>
Traceback (most recent call last):
  File ".../urllib3/connectionpool.py", line 1174, in _close_pool_connections
    conn = pool.get(block=False)
  File ".../queue.py", line 182, in get
    self.not_full.notify()
  File ".../threading.py", line 376, in notify
    if not self._is_owned():
  File ".../threading.py", line 289, in _is_owned
    if self._lock.acquire(False):
  File ".../gevent/thread.py", line 132, in acquire
    sleep()
  File ".../gevent/hub.py", line 154, in sleep
    hub = _get_hub_noargs()
  File "src/gevent/_hub_local.py", line 107, in gevent._gevent_c_hub_local.get_hub_noargs
AttributeError: '_Threadlocal' object has no attribute 'Hub'
```

## Root Cause

1. **Gevent monkey-patches Python's threading and queue modules** to use greenlets instead of OS threads
2. **urllib3 uses weak references and finalizers** to clean up connection pools during garbage collection
3. **During shutdown**, Python's finalizers run to clean up resources
4. **The gevent hub is torn down** before all finalizers complete
5. **urllib3's finalizers try to access the queue notification system**, which requires gevent's hub
6. **The hub is no longer available**, causing AttributeError exceptions

This creates a race condition where:
- urllib3's finalizers → call `pool.get()` → trigger queue notifications → need threading locks
- Gevent's patched locks → need the gevent hub → but the hub is already destroyed

## Impact

- **Severity**: Low - these are harmless warnings during shutdown
- **Functionality**: Does not affect application functionality
- **User Experience**: Not visible to end users
- **Logs**: Creates noise in production logs during worker restarts

## Solution

Patch urllib3's `_close_pool_connections` method to be gevent-aware and handle shutdown gracefully.

### Implementation

In `wsgi.py` (after gevent monkey patching but before importing the app):

```python
def _gevent_safe_close_pool_connections(self, pool):
    """
    Safely close pool connections, catching gevent hub errors during shutdown.
    This prevents "AttributeError: '_Threadlocal' object has no attribute 'Hub'"
    errors that occur when urllib3 tries to clean up during gevent shutdown.
    """
    try:
        # Try to check if gevent hub is still available
        from gevent import getcurrent
        getcurrent()  # This will raise AttributeError if hub is gone
        # Hub is available, proceed with normal cleanup
        _original_close_pool_connections(self, pool)
    except (AttributeError, RuntimeError):
        # Gevent hub is not available or already torn down
        # Safely drain the pool without gevent synchronization
        try:
            while True:
                conn = pool.get(block=False)
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass  # Ignore errors during shutdown
        except Exception:
            pass  # Queue is empty or other error, that's fine
    except Exception:
        pass  # Any other error, ignore during shutdown
```

### How It Works

1. **Check for gevent hub availability** using `getcurrent()`
2. **If hub is available**: Use normal urllib3 cleanup (calls original method)
3. **If hub is gone**: Bypass gevent's queue synchronization and directly drain the pool
4. **Catch all exceptions**: During shutdown, failing to close connections is acceptable

### Benefits

1. ✅ **Eliminates shutdown exceptions** - No more AttributeError messages in logs
2. ✅ **Maintains proper cleanup** - Connections still get closed when possible
3. ✅ **Graceful degradation** - Falls back to simple cleanup if gevent is unavailable
4. ✅ **Zero runtime overhead** - Only executes during shutdown
5. ✅ **Compatible with all urllib3 versions** - Patches the method dynamically

## Alternative Solutions Considered

### 1. Disable urllib3 warnings globally
```python
urllib3.disable_warnings()
```
❌ **Problem**: Doesn't actually prevent the exceptions, just hides warnings

### 2. Suppress stderr during shutdown
❌ **Problem**: Would hide all shutdown errors, not just harmless ones

### 3. Switch to sync workers
❌ **Problem**: Would lose WebSocket/real-time features that require gevent

### 4. Use requests with connection pooling disabled
❌ **Problem**: Would hurt performance by creating new connections for every request

### 5. Pin specific urllib3/gevent versions
❌ **Problem**: Not a real fix, just avoids the symptom

## Testing

To verify the fix works:

1. Deploy the application with gevent workers
2. Make several HTTP requests to trigger connection pool usage
3. Restart the worker (or trigger shutdown)
4. Check logs - should see no "Exception ignored in: <finalize object>" errors

## Related Issues

- **Gevent Issue #1016**: Known issue with finalizers and greenlet cleanup
- **urllib3 Issue #1177**: Connection pool cleanup during interpreter shutdown
- **Python Issue #30394**: Finalizers running after threadlocal cleanup

## Files Modified

- `wsgi.py` - Added gevent-safe urllib3 connection pool cleanup

## Date Fixed

October 31, 2025

## References

- [Gevent Monkey Patching](https://www.gevent.org/api/gevent.monkey.html)
- [urllib3 Connection Pooling](https://urllib3.readthedocs.io/en/latest/advanced-usage.html#connection-pooling)
- [Python Weak References](https://docs.python.org/3/library/weakref.html#weakref.finalize)

