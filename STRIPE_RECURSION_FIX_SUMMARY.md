# Stripe RecursionError Fix - Summary

## What Was Wrong

Your Stripe checkout was failing with:
```
STRIPE ERROR: APIConnectionError: Network error: A RecursionError
```

**Root Cause**: Your app runs on Gunicorn with **gevent workers**, which monkey-patches Python's networking stack. When Stripe's `urllib3` library tried to make HTTPS requests, gevent's monkey-patched SSL code caused infinite recursion.

## The Fix

All Stripe API calls now run in **real OS threads** using `ThreadPoolExecutor`, which bypasses gevent's problematic monkey-patching.

### Changes Made

✅ Updated `subscriptions.py`:
- `create_checkout_session()` - Now uses ThreadPoolExecutor
- `create_customer_portal_session()` - Now uses ThreadPoolExecutor  
- `cancel_subscription()` - Now uses ThreadPoolExecutor
- `get_subscription()` - Now uses ThreadPoolExecutor

✅ Added 10-second timeout protection for all Stripe API calls

✅ Cleaned up old recursion prevention code (thread-local locks, logging disables, recursion limit changes) that didn't work

✅ Created documentation: `docs/development/STRIPE_GEVENT_FIX.md`

## Why This Works

- **Gevent** only monkey-patches the main greenlet/thread
- **ThreadPoolExecutor** creates real OS threads (not greenlets)
- Real OS threads use the **original un-monkey-patched** Python standard library
- Stripe's urllib3 can now make HTTPS requests normally

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
- ✅ `INFO: Making Stripe API call in OS thread...`
- ✅ `SUCCESS: Created checkout session for...`
- ❌ Any timeout errors (if Stripe API is slow)

## Deploy Instructions

```bash
# Commit the changes
git add subscriptions.py docs/development/STRIPE_GEVENT_FIX.md STRIPE_RECURSION_FIX_SUMMARY.md
git commit -m "Fix Stripe RecursionError with gevent workers using ThreadPoolExecutor"

# Push to deploy
git push origin main
```

## If You Still Have Issues

1. Check that `STRIPE_SECRET_KEY` and price IDs are configured correctly
2. Verify Stripe API key has proper permissions
3. Check network connectivity to Stripe's API
4. Review logs for any timeout errors (increase timeout if needed)

---

**Status**: ✅ Ready to deploy and test

