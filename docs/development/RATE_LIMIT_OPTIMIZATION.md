# Rate Limit Optimization Guide

## Current Rate Limit Analysis

### Existing Limits
- **API endpoints**: 60 requests/minute
- **Scraper operations**: 10 requests/minute ⚠️ **TOO RESTRICTIVE**
- **Settings updates**: 30 requests/minute
- **Login attempts**: 5 requests/minute
- **Registration attempts**: 3 requests/minute

## Issues Identified

1. **Scraper limit too low**: 10 requests/minute severely limits legitimate scraping
2. **No user tier differentiation**: All users have same limits regardless of subscription
3. **No burst capacity**: Limits are strict per-minute with no short-term flexibility
4. **No endpoint-specific tuning**: Some endpoints may need different limits

## Recommended Optimizations

### 1. Increase Scraper Limits
```python
RATE_LIMITS = {
    'api': 60,           # Keep current
    'scraper': 30,       # Increase from 10 to 30
    'scraper_burst': 5,  # Allow 5 requests in 10 seconds
    'settings': 30,      # Keep current
    'login': 5,          # Keep current
    'register': 3,       # Keep current
}
```

### 2. Add Subscription-Based Limits
```python
SUBSCRIPTION_LIMITS = {
    'free': {
        'api': 30,
        'scraper': 15,
    },
    'premium': {
        'api': 120,
        'scraper': 60,
    },
    'admin': {
        'api': 1000,
        'scraper': 500,
    }
}
```

### 3. Implement Burst Allowance
```python
BURST_LIMITS = {
    'scraper': {
        'burst_requests': 5,
        'burst_window': 10,  # seconds
        'normal_requests': 30,
        'normal_window': 60  # seconds
    }
}
```

### 4. Add Rate Limit Headers
Include rate limit information in API responses:
```python
def add_rate_limit_headers(response):
    response.headers['X-RateLimit-Limit'] = str(limit)
    response.headers['X-RateLimit-Remaining'] = str(remaining)
    response.headers['X-RateLimit-Reset'] = str(reset_time)
    return response
```

## Implementation Steps

### Step 1: Update Rate Limit Configuration
1. Modify `rate_limiter.py` to include subscription-based limits
2. Add burst allowance logic
3. Update database schema if needed

### Step 2: Add Admin Controls
1. Create admin interface for rate limit management
2. Add ability to temporarily increase limits for specific users
3. Implement rate limit monitoring dashboard

### Step 3: Add Monitoring
1. Log rate limit hits for analysis
2. Create alerts for unusual rate limit patterns
3. Add metrics for rate limit effectiveness

## Quick Fixes for Current Issue

### Immediate Solutions:
1. **Reset current rate limits**: Use the provided script
2. **Temporarily increase scraper limits**: Change from 10 to 30
3. **Add rate limit bypass for admin users**

### Code Changes Needed:
```python
# In rate_limiter.py, add admin bypass
def rate_limit(endpoint_type, max_requests=None, window_minutes=1):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Admin bypass
            if current_user.is_authenticated and current_user.role == 'admin':
                return f(*args, **kwargs)
            
            # ... rest of rate limiting logic
```

## Monitoring Recommendations

1. **Track rate limit hits**: Log when users hit limits
2. **Monitor patterns**: Identify if limits are too restrictive
3. **User feedback**: Allow users to request limit increases
4. **Automatic scaling**: Increase limits based on user behavior

## Testing Recommendations

1. **Load testing**: Test with realistic user loads
2. **Edge case testing**: Test rate limit behavior under stress
3. **User experience testing**: Ensure limits don't break legitimate usage
4. **Security testing**: Ensure limits prevent abuse while allowing normal use
