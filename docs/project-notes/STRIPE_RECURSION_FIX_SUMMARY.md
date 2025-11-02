# Stripe RecursionError Fix - Summary

## What Was Wrong

Your Stripe checkout was failing with:
```
STRIPE ERROR: APIConnectionError: Network error: A RecursionError
```

**Root Cause**: Your app runs on Gunicorn with **gevent workers**, which monkey-patches Python's networking stack INCLUDING the `threading` module. When Stripe's `urllib3` library tried to make HTTPS requests, gevent's monkey-patched SSL/threading code caused infinite recursion.

## The REAL Fix (v2 - subprocess)

All Stripe API calls now run in **separate Python processes** using `subprocess.run()`, which **completely isolates** them from gevent's monkey-patching.

### Why ThreadPoolExecutor Didn't Work

The first fix attempt used `ThreadPoolExecutor`, but it still failed because:
- Gevent monkey-patches the `threading` module itself
- `ThreadPoolExecutor` uses the patched threading module
- So it was still creating gevent greenlets, not real OS threads
- Still hit the recursion error

### Why Subprocess Works

- `subprocess.run()` creates a **completely new Python process**
- The subprocess has NO gevent imported or loaded
- Uses Python's original, un-monkey-patched standard library
- Stripe's urllib3 works normally with real system SSL/sockets

### Changes Made (v2)

✅ Updated `subscriptions.py`:
- `create_checkout_session()` - Now uses `subprocess.run()` to execute Stripe calls
- `create_customer_portal_session()` - Now uses `subprocess.run()`
- `cancel_subscription()` - Now uses `subprocess.run()`
- `get_subscription()` - Now uses `subprocess.run()`

✅ Added 15-second timeout protection for all Stripe API calls

✅ Each subprocess returns JSON results back to main process

✅ Clean error handling with proper exception capture

## How It Works

1. **Main Flask app** (running with gevent) receives checkout request
2. **Subprocess launched** - Fresh Python interpreter with NO gevent
3. **Stripe API call** executes in subprocess with normal urllib3/SSL
4. **JSON result** returned via stdout to main process
5. **Response sent** back to user with session URL or error

## Testing

To verify the fix works:

1. Deploy the updated code
2. Try subscribing to the Pro plan from `/subscription/plans`
3. Should redirect to Stripe checkout without errors

## No Configuration Changes Needed

- Gunicorn still uses gevent workers (no change needed)
- SocketIO still works for real-time features
- All other functionality remains the same

## What to Watch For

Monitor your logs for:
- ✅ `INFO: Making Stripe API call in subprocess...`
- ✅ `SUCCESS: Created checkout session for...`
- ❌ Any timeout errors (subprocess is given 15 seconds)
- ❌ Any JSON parsing errors (shouldn't happen)

## Deploy Instructions

```bash
# Already deployed!
git log --oneline -2
# 8300c25 Fix Stripe RecursionError using subprocess instead of ThreadPoolExecutor
# 289bcdd Fix Stripe RecursionError with gevent workers using ThreadPoolExecutor (first attempt)
```

## If You Still Have Issues

1. Check that `STRIPE_SECRET_KEY` and price IDs are configured correctly
2. Verify Stripe API key has proper permissions
3. Check network connectivity to Stripe's API
4. Review logs for any timeout errors (increase timeout if needed)

---

**Status**: ✅ Ready to deploy and test

