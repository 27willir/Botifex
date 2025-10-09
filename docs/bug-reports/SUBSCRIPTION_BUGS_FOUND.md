# Subscription System - Bug Report

## Critical Bugs Found

### 1. **Bug in `get_keyword_limit()` and `get_max_platforms()` - subscriptions.py**

**Location:** `subscriptions.py` lines 98-102 and 116-121

**Issue:** The logic for checking unlimited keywords/platforms is incorrect.

```python
# Current code (WRONG):
def get_keyword_limit(tier_name):
    features = SubscriptionManager.get_user_tier_features(tier_name)
    max_keywords = features.get('max_keywords', 2)
    return max_keywords if max_keywords > 0 else float('inf')  # BUG!
```

**Problem:** The code returns `float('inf')` when `max_keywords <= 0`, but unlimited is defined as `-1` in the tier configuration (line 55). This means:
- When `max_keywords = -1` (unlimited), it incorrectly checks `if -1 > 0` which is False, so it returns `float('inf')` ✓ (works by accident)
- When `max_keywords = 0`, it also returns `float('inf')` which is wrong

**Fix:** Should explicitly check for `-1`:
```python
def get_keyword_limit(tier_name):
    features = SubscriptionManager.get_user_tier_features(tier_name)
    max_keywords = features.get('max_keywords', 2)
    return float('inf') if max_keywords == -1 else max_keywords
```

**Impact:** Medium - Currently works for the defined tiers but is fragile and semantically incorrect.

---

### 2. **Critical Bug in Webhook Handler - Missing stripe_customer_id in query**

**Location:** `app.py` lines 831-844

**Issue:** When handling subscription deletion webhook, the code tries to find user by `stripe_customer_id`, but the database query doesn't include this field.

```python
# Current code (WRONG):
elif result.get('status') == 'deleted':
    customer_id = result.get('customer_id')
    
    # Find user by customer_id
    subscriptions = db_enhanced.get_all_subscriptions()  # BUG: Doesn't include stripe_customer_id!
    for sub in subscriptions:
        if sub.get('stripe_customer_id') == customer_id:  # This will NEVER match!
            username = sub.get('username')
            # ... cancel subscription
```

**Root Cause:** The `get_all_subscriptions()` function in `db_enhanced.py` (lines 1591-1618) only returns:
- username
- tier
- status
- current_period_end
- created_at

It does NOT include `stripe_customer_id`.

**Fix Required:** Update `db_enhanced.get_all_subscriptions()` to include `stripe_customer_id`:

```python
# In db_enhanced.py line 1596:
query = """
    SELECT username, tier, status, stripe_customer_id, current_period_end, created_at 
    FROM subscriptions WHERE 1=1
"""

# And in the return dict (line 1612):
return [{
    'username': row[0],
    'tier': row[1],
    'status': row[2],
    'stripe_customer_id': row[3],  # ADD THIS
    'current_period_end': row[4],
    'created_at': row[5]
} for row in rows]
```

**Impact:** CRITICAL - Subscription cancellations via Stripe webhook will NEVER work. Users who cancel through Stripe will remain subscribed in the app.

---

### 3. **Inefficient Webhook Lookup - Database Design Issue**

**Location:** `app.py` lines 831-844

**Issue:** Even after fixing bug #2, the webhook handler loads ALL subscriptions to find one user:

```python
subscriptions = db_enhanced.get_all_subscriptions()  # Loads EVERYTHING
for sub in subscriptions:
    if sub.get('stripe_customer_id') == customer_id:
        # Found it
```

**Problem:** With 1000+ users, this is extremely inefficient. Should have a dedicated lookup function.

**Fix:** Add a new function to `db_enhanced.py`:

```python
@log_errors()
def get_subscription_by_customer_id(stripe_customer_id):
    """Get subscription by Stripe customer ID"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT username, tier, status, stripe_subscription_id, 
                   current_period_start, current_period_end
            FROM subscriptions
            WHERE stripe_customer_id = ?
        """, (stripe_customer_id,))
        
        row = c.fetchone()
        if row:
            return {
                'username': row[0],
                'tier': row[1],
                'status': row[2],
                'stripe_subscription_id': row[3],
                'current_period_start': row[4],
                'current_period_end': row[5]
            }
        return None
```

Then update `app.py`:
```python
elif result.get('status') == 'deleted':
    customer_id = result.get('customer_id')
    subscription = db_enhanced.get_subscription_by_customer_id(customer_id)
    
    if subscription:
        username = subscription['username']
        db_enhanced.cancel_subscription(username)
        # ... rest of code
```

**Impact:** HIGH - Performance issue that will worsen with more users.

---

### 4. **Missing Index on stripe_customer_id**

**Location:** `db_enhanced.py` lines 312-341 (index creation)

**Issue:** There's no database index on `subscriptions.stripe_customer_id`, which is used for webhook lookups.

**Fix:** Add index in the init_db() function:
```python
"CREATE INDEX IF NOT EXISTS idx_subscriptions_customer_id ON subscriptions(stripe_customer_id)",
```

**Impact:** MEDIUM - Webhook lookups will be slow without this index.

---

### 5. **Parameter Type Inconsistency**

**Location:** Multiple files

**Issue:** `get_user_subscription()` expects `username` (string), but is called with `current_user.id` which could be interpreted different ways.

**Current:** In Flask-Login, `current_user.id` returns the username (set in load_user), so this is actually OK.

**However:** The parameter name is misleading. The function should accept `user_id` or the name should be changed to `get_user_subscription_by_username()` for clarity.

**Fix:** Rename parameter for clarity:
```python
def get_user_subscription(username):  # Keep as-is, just document
    """
    Get user's subscription information
    
    Args:
        username (str): The username (user_id) to look up
    """
```

**Impact:** LOW - Code works but is confusing.

---

### 6. **Missing Error Handling in Webhook**

**Location:** `app.py` line 781-851

**Issue:** If subscription update fails in the database during webhook processing, Stripe doesn't know about it.

**Current Code:**
```python
if username and tier:
    db_enhanced.create_or_update_subscription(...)  # What if this fails?
    db_enhanced.log_subscription_event(...)         # What if this fails?
```

**Fix:** Add proper error handling:
```python
if username and tier:
    try:
        db_enhanced.create_or_update_subscription(
            username=username,
            tier=tier,
            status='active',
            stripe_customer_id=customer_id,
            stripe_subscription_id=subscription_id
        )
        
        db_enhanced.log_subscription_event(
            username=username,
            tier=tier,
            action='subscription_created',
            stripe_event_id=event['id'],
            details=f'Subscription created via Stripe checkout'
        )
        
        logger.info(f"Subscription activated for {username} - {tier} tier")
    except Exception as e:
        logger.error(f"Failed to update subscription in database: {e}")
        # Return error so Stripe retries the webhook
        return jsonify({"error": "Database update failed"}), 500
```

**Impact:** HIGH - Failed database updates will cause subscription state mismatch.

---

### 7. **Subscription Status Not Updated from Stripe**

**Location:** `app.py` lines 311-322 (webhook handler for subscription.updated)

**Issue:** The `_handle_subscription_updated` handler doesn't actually update the database.

```python
@staticmethod
def _handle_subscription_updated(subscription):
    """Handle subscription update"""
    customer_id = subscription.get('customer')
    status = subscription.get('status')
    
    logger.info(f"Subscription updated for customer {customer_id} - status: {status}")
    
    return {
        'status': 'updated',
        'customer_id': customer_id,
        'subscription_status': status
    }
    # BUG: Returns info but doesn't update database!
```

**Fix:** Update the webhook handler in `app.py` to actually process the update:
```python
elif result.get('status') == 'updated':
    # Subscription status changed (active, past_due, canceled, etc.)
    customer_id = result.get('customer_id')
    subscription_status = result.get('subscription_status')
    
    # Find user and update status
    subscription = db_enhanced.get_subscription_by_customer_id(customer_id)
    if subscription:
        username = subscription['username']
        
        # Map Stripe status to our status
        # Stripe statuses: active, past_due, unpaid, canceled, incomplete, incomplete_expired, trialing
        our_status = 'active' if subscription_status in ['active', 'trialing'] else 'inactive'
        
        db_enhanced.create_or_update_subscription(
            username=username,
            tier=subscription['tier'],
            status=our_status,
            stripe_customer_id=customer_id,
            stripe_subscription_id=subscription.get('stripe_subscription_id')
        )
        
        db_enhanced.log_subscription_event(
            username=username,
            tier=subscription['tier'],
            action='subscription_updated',
            stripe_event_id=event['id'],
            details=f'Status changed to {subscription_status}'
        )
```

**Impact:** HIGH - Subscription status changes (payment failures, etc.) won't be reflected in the app.

---

### 8. **Race Condition in Subscription Check**

**Location:** `subscription_middleware.py` lines 33-34

**Issue:** User subscription is fetched on every request without caching, and there's no transaction isolation.

```python
subscription = db_enhanced.get_user_subscription(current_user.id)
user_tier = subscription.get('tier', 'free')
```

**Problem:** If a subscription is being updated via webhook at the same time a user makes a request, they might get inconsistent data.

**Fix:** This is already somewhat mitigated by SQLite's default isolation level, but consider adding a short cache (already implemented in `add_subscription_context`).

**Impact:** LOW - SQLite handles this reasonably well, but consider adding Redis for high-scale.

---

### 9. **No Validation of Stripe Price IDs**

**Location:** `subscriptions.py` lines 38, 53

**Issue:** Price IDs come from environment variables but are never validated on startup.

```python
'price_id': os.getenv('STRIPE_STANDARD_PRICE_ID'),  # Could be None!
```

**Fix:** Add validation in the StripeManager or on app startup:
```python
def validate_stripe_config():
    """Validate Stripe configuration on startup"""
    if not stripe.api_key:
        logger.warning("Stripe API key not configured")
        return False
    
    required_price_ids = {
        'standard': os.getenv('STRIPE_STANDARD_PRICE_ID'),
        'pro': os.getenv('STRIPE_PRO_PRICE_ID')
    }
    
    for tier, price_id in required_price_ids.items():
        if not price_id:
            logger.warning(f"Missing STRIPE_{tier.upper()}_PRICE_ID in environment")
            return False
    
    return True
```

**Impact:** MEDIUM - App will fail when users try to checkout if price IDs are missing.

---

### 10. **Webhook Secret Not Validated**

**Location:** `subscriptions.py` line 16

**Issue:** Webhook secret could be None if not set in environment.

```python
STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET')  # Could be None!
```

Then in line 259:
```python
event = stripe.Webhook.construct_event(
    payload, sig_header, STRIPE_WEBHOOK_SECRET  # Fails if None!
)
```

**Fix:** Validate on startup and handle gracefully:
```python
STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET')

if not STRIPE_WEBHOOK_SECRET:
    logger.warning("STRIPE_WEBHOOK_SECRET not set - webhooks will not work!")
```

**Impact:** MEDIUM - Webhooks will fail if secret is not configured.

---

## Summary

### Critical (Must Fix Immediately):
1. ❗ **Bug #2**: Webhook subscription deletion lookup will never work
2. ❗ **Bug #7**: Subscription status updates from Stripe are ignored

### High Priority:
3. **Bug #3**: Inefficient webhook lookup (performance issue)
4. **Bug #6**: Missing error handling in webhook could cause data inconsistency

### Medium Priority:
5. **Bug #1**: Incorrect logic for unlimited keywords/platforms
6. **Bug #4**: Missing database index on stripe_customer_id
7. **Bug #9**: No validation of Stripe price IDs
8. **Bug #10**: No validation of webhook secret

### Low Priority:
9. **Bug #5**: Parameter naming confusion
10. **Bug #8**: Potential race condition (already mostly mitigated)

## Recommendations

1. **Immediate Actions:**
   - Fix bug #2 (add stripe_customer_id to query)
   - Fix bug #7 (handle subscription.updated events)
   - Add comprehensive error handling to webhook endpoint

2. **Short Term:**
   - Add `get_subscription_by_customer_id()` function
   - Add database index on stripe_customer_id
   - Validate Stripe configuration on startup

3. **Long Term:**
   - Add integration tests for webhook handlers
   - Consider adding Redis for caching subscription data
   - Add monitoring/alerting for failed webhook processing

