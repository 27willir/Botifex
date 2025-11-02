# User Isolation & Scraper Bug Fixes

## Date: November 2, 2025

## Issues Fixed

### 1. ✅ Missing `get_scraper_health()` Function
**Problem:** Function was imported in `app.py` but didn't exist in `scraper_thread.py`
**Fix:** Created the `get_scraper_health(user_id)` function that returns detailed health information for each scraper including:
- Running status
- Error count
- Recent errors
- Last start time

**Location:** `scraper_thread.py` lines 564-582

---

### 2. ✅ Missing `user_id` in `/start-all` Route
**Problem:** The `/start-all` endpoint was calling scraper start functions without passing the `user_id` parameter
**Error:** `start_craigslist() missing 1 required positional argument: 'user_id'`

**Fix:** Added `user_id = current_user.id` and passed it to all scraper start calls:
```python
start_facebook(user_id)
start_craigslist(user_id)
start_ksl(user_id)
start_ebay(user_id)
start_poshmark(user_id)
start_mercari(user_id)
```

**Location:** `app.py` lines 573, 589-605

---

### 3. ✅ Missing `user_id` in `api_scraper_health()` Endpoint
**Problem:** The `/api/scraper-health` endpoint was calling `get_scraper_health()` without passing `user_id`
**Error:** `get_scraper_health() missing 1 required positional argument: 'user_id'`

**Fix:** Added `user_id = current_user.id` and passed it to the function:
```python
user_id = current_user.id
health = get_scraper_health(user_id)
```

**Location:** `app.py` lines 1605-1606

---

### 4. ✅ System Health Monitor Using Wrong Function
**Problem:** `error_recovery.py` was calling `get_scraper_status(user_id)` without a user_id parameter
**Error:** `get_scraper_status() missing 1 required positional argument: 'user_id'`

**Fix:** Changed to use `get_system_stats()` instead, which returns system-wide statistics:
```python
from scraper_thread import get_system_stats
stats = get_system_stats()
if stats['total_scrapers'] > 0:
    # System is healthy
```

**Location:** `error_recovery.py` lines 103-106

---

### 5. ✅ Session Loss Across Multiple Workers (CRITICAL)
**Problem:** App configured with 2 Gunicorn workers, but Flask's default sessions are in-memory per worker. When a user's request hits Worker 1 they're logged in, but when the next request hits Worker 2, that worker doesn't have their session, causing redirects to login.

**Evidence from logs:**
- Multiple internal IPs handling same external IP's requests
- Authenticated user getting 302 redirects to `/login` on API calls
- Rate limit errors on login page due to repeated redirects

**Fix:** Implemented server-side session storage using `Flask-Session` with filesystem backend:

1. **Added Flask-Session dependency:**
   - `requirements.txt`: Added `Flask-Session==0.8.0`

2. **Configured session storage in app.py:**
```python
from flask_session import Session

app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = './flask_session'
app.config['SESSION_PERMANENT'] = True
app.config['SESSION_USE_SIGNER'] = True
app.config['SESSION_KEY_PREFIX'] = 'superbot_session:'
Session(app)
```

3. **Updated .gitignore:**
   - Added `flask_session/` to ignore session files

**Location:** 
- `app.py` lines 4, 57-63
- `requirements.txt` line 4
- `.gitignore` line 42

---

## Root Cause Analysis

### User Isolation Issues
All scraper functions were recently refactored to accept a `user_id` parameter for multi-tenant support, but several endpoints and health check functions weren't updated to pass this parameter.

### Session Issues
The multi-worker configuration (`WEB_CONCURRENCY=2` in `render.yaml`) combined with in-memory sessions created a race condition where users would appear logged out randomly depending on which worker handled their request.

---

## Testing Recommendations

1. **Test user-specific scraper operations:**
   - Start individual scrapers
   - Start all scrapers
   - Check scraper health
   - Verify scrapers run only for the authenticated user

2. **Test session persistence:**
   - Log in from one browser
   - Make multiple API calls to `/api/status`, `/api/listings`, `/api/scraper-health`
   - Verify no redirects to `/login` occur
   - Check that session persists across page refreshes

3. **Test multi-user scenarios:**
   - Create 2 users
   - Log in as User A, start scrapers
   - Log in as User B (different browser), start scrapers
   - Verify User A's scrapers don't show in User B's dashboard
   - Verify both users stay logged in

4. **Load testing:**
   - Simulate multiple concurrent users
   - Verify sessions remain stable
   - Check session file cleanup

---

## Deployment Notes

### Before Deployment:
- [ ] Ensure `flask_session/` directory will be created with write permissions on server
- [ ] Verify `Flask-Session==0.8.0` is installed: `pip install Flask-Session`
- [ ] Test locally with multiple workers: `gunicorn --workers 2 wsgi:application`

### After Deployment:
- [ ] Monitor logs for any session-related errors
- [ ] Verify no more "missing user_id" errors
- [ ] Check that users stay authenticated across API calls
- [ ] Monitor session directory size (cleanup old sessions if needed)

---

## Files Modified

1. `scraper_thread.py` - Added `get_scraper_health()` function
2. `app.py` - Fixed `/start-all`, `/api/scraper-health`, added Flask-Session
3. `error_recovery.py` - Fixed health monitor to use `get_system_stats()`
4. `requirements.txt` - Added Flask-Session
5. `.gitignore` - Added flask_session/ directory

---

## Success Criteria

✅ No more "missing 1 required positional argument: 'user_id'" errors
✅ Users stay authenticated across multiple API requests
✅ Sessions persist across multiple Gunicorn workers
✅ Health monitoring works without errors
✅ Multi-tenant user isolation maintained

