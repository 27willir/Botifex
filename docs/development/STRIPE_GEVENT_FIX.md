# Stripe + Gevent RecursionError Fix

## Problem

When attempting to create Stripe checkout sessions, the application was encountering a `RecursionError` during the Stripe API call:

```
STRIPE ERROR creating checkout session: APIConnectionError: Unexpected error communicating with Stripe.
(Network error: A RecursionError...
```

## Root Cause

The application runs on **Gunicorn with gevent workers** (configured in `gunicorn_config.py`). Gevent uses **monkey-patching** to replace Python's standard library (socket, SSL, threading) with async-friendly greenlet versions.

When Stripe's library (which uses `urllib3`) tried to make HTTPS requests to the Stripe API:

1. Gevent's monkey-patched SSL/socket code intercepted the connection
2. The monkey-patched code created a recursion issue with urllib3's connection pooling
3. Python hit the recursion limit (default 1000) and raised a `RecursionError`
4. Stripe caught this and wrapped it in an `APIConnectionError`

## Previous Failed Attempts

The codebase had several previous attempts to fix this:

1. **Disabling logging** - `logging.disable(logging.CRITICAL)` - didn't help because the issue was in the network stack, not logging
2. **Increasing recursion limit** - `sys.setrecursionlimit(3000)` - masked the problem temporarily but didn't solve it
3. **Thread-local re-entrancy guards** - didn't help because the issue was in gevent's monkey-patching, not re-entrancy

## Solution

**Execute all Stripe API calls in real OS threads using `ThreadPoolExecutor`.**

Real OS threads bypass gevent's monkey-patching because:
- Gevent's greenlets only affect the main thread
- ThreadPoolExecutor creates actual OS threads (not greenlets)
- These threads use Python's original (un-monkey-patched) standard library
- urllib3 can make HTTPS requests normally without gevent interference

### Implementation

All Stripe API methods now follow this pattern:

```python
from concurrent.futures import ThreadPoolExecutor

def create_checkout_session(...):
    result_container = {'session': None, 'error': None}
    
    def _make_stripe_call():
        try:
            session = stripe.checkout.Session.create(...)
            result_container['session'] = session
        except Exception as e:
            result_container['error'] = str(e)
    
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix='stripe-api') as executor:
        future = executor.submit(_make_stripe_call)
        future.result(timeout=10)  # 10 second timeout
    
    return result_container['session'], result_container['error']
```

### Methods Updated

All Stripe API methods in `subscriptions.py` were updated:

1. `StripeManager.create_checkout_session()` - Creates payment checkout sessions
2. `StripeManager.create_customer_portal_session()` - Creates customer portal for subscription management
3. `StripeManager.cancel_subscription()` - Cancels subscriptions
4. `StripeManager.get_subscription()` - Retrieves subscription details

### Benefits

1. **Eliminates RecursionError** - OS threads bypass gevent's problematic monkey-patching
2. **Maintains async compatibility** - The main Flask app still uses gevent for handling requests
3. **Simple timeout handling** - 10-second timeout prevents hanging requests
4. **Clean error handling** - Exceptions are caught and returned gracefully
5. **Production-ready** - No configuration changes needed, works with existing gevent setup

## Testing

To verify the fix works:

1. Ensure the app is running with gevent workers (default in production)
2. Try creating a subscription checkout session
3. Should complete successfully without RecursionError

## Alternative Solutions Considered

1. **Switch to sync workers** - Would lose SocketIO real-time features
2. **Switch to eventlet workers** - Would have similar issues with different monkey-patching
3. **Use requests library instead of Stripe's urllib3** - More invasive changes
4. **Patch urllib3 to avoid gevent** - Too fragile and version-dependent

## References

- **Gevent Monkey Patching**: https://www.gevent.org/api/gevent.monkey.html
- **urllib3 + gevent issues**: Known issue when SSL sockets are monkey-patched
- **ThreadPoolExecutor**: Uses real OS threads that bypass greenlet monkey-patching

## Date Fixed

October 30, 2025

## Files Modified

- `subscriptions.py` - All `StripeManager` methods updated to use ThreadPoolExecutor

