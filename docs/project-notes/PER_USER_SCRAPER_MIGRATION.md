# Per-User Scraper Migration Guide

## 🎯 Goal

Convert from global scrapers to per-user scraper instances for proper SaaS multi-tenancy.

---

## ✅ Progress So Far

### Completed:
1. ✅ Updated `scrapers/common.py` - `load_settings()` now accepts `username` parameter
2. ✅ Updated `scrapers/craigslist.py` as a complete reference example
3. ✅ Created this migration guide

### In Progress:
- Updating remaining scrapers (eBay, KSL, Mercari, Facebook, Poshmark)
- Updating `scraper_thread.py` for per-user thread management
- Updating `app.py` routes to pass user_id

---

## 📋 Changes Required Per Scraper

Each scraper file needs these modifications:

### 1. Update `check_<scraper>()` Function Signature

**Before:**
```python
def check_craigslist(flag_name=SITE_NAME):
    settings = load_settings()
```

**After:**
```python
def check_craigslist(flag_name=SITE_NAME, user_id=None):
    settings = load_settings(username=user_id)
```

### 2. Update `send_discord_message()` Function

**Before:**
```python
def send_discord_message(title, link, price=None, image_url=None):
    save_listing(title, price, link, image_url, SITE_NAME)
    logger.info(f"📢 New Craigslist: {title} | ${price} | {link}")
```

**After:**
```python
def send_discord_message(title, link, price=None, image_url=None, user_id=None):
    save_listing(title, price, link, image_url, SITE_NAME, user_id=user_id)
    logger.info(f"📢 New Craigslist for {user_id}: {title} | ${price} | {link}")
```

### 3. Update Calls to `send_discord_message()`

**Before:**
```python
send_discord_message(title, link, price_val, image_url)
```

**After:**
```python
send_discord_message(title, link, price_val, image_url, user_id=user_id)
```

### 4. Update `run_<scraper>_scraper()` Function

**Before:**
```python
def run_craigslist_scraper(flag_name=SITE_NAME):
    logger.info("Starting Craigslist scraper")
    # ...
    results = check_craigslist(flag_name)
```

**After:**
```python
def run_craigslist_scraper(flag_name=SITE_NAME, user_id=None):
    logger.info(f"Starting Craigslist scraper for user {user_id}")
    # ...
    results = check_craigslist(flag_name, user_id=user_id)
```

---

## 🔧 Scraper-Specific Notes

### Craigslist ✅ (COMPLETED - Use as Reference)
- Location: `scrapers/craigslist.py`
- Status: Fully updated
- All functions now accept and pass `user_id`

### eBay ⏳ (TODO)
- Location: `scrapers/ebay.py`
- Changes needed:
  - `check_ebay()` - add `user_id` parameter
  - `send_discord_message()` - add `user_id` parameter
  - `run_ebay_scraper()` - add `user_id` parameter
  - Update all calls to pass `user_id`

### KSL ⏳ (TODO)
- Location: `scrapers/ksl.py`
- Changes needed: Same as eBay

### Mercari ⏳ (TODO)
- Location: `scrapers/mercari.py`
- Has custom `load_settings()` - need to update or remove
- Changes needed: Same pattern as above

### Facebook ⏳ (TODO)
- Location: `scrapers/facebook.py`
- Uses `ErrorHandler.handle_database_error()` wrapper
- Has custom `load_settings()` - need to update or remove
- Changes needed: Same pattern, mind the error handler

### Poshmark ⏳ (TODO)
- Location: `scrapers/poshmark.py`
- Has custom `load_settings()` - need to update or remove
- Changes needed: Same pattern as above

---

## 🧵 Thread Management Changes

### Current State (`scraper_thread.py`)
```python
_threads = {}  # Single thread per scraper globally
_drivers = {}  # Single driver per scraper

# Example:
_threads['craigslist'] = Thread(...)  # ONE thread for ALL users
```

### New State (Required)
```python
_threads = {}  # Per-user threads: _threads[user_id][scraper_name]
_drivers = {}  # Per-user drivers: _drivers[user_id][scraper_name]

# Example:
_threads['alice']['craigslist'] = Thread(...)  # Alice's thread
_threads['bob']['craigslist'] = Thread(...)    # Bob's thread
```

### Required Changes to `scraper_thread.py`:

1. **Change data structures:**
```python
# Old:
_threads = {}
_drivers = {}

# New:
_threads = {}      # Format: {user_id: {scraper_name: thread}}
_drivers = {}      # Format: {user_id: {scraper_name: driver}}
_user_locks = {}   # Per-user locks for thread safety
```

2. **Update `start_facebook_thread()`** (and similar):
```python
# Old signature:
def start_facebook_thread():
    if 'facebook' in _threads and _threads['facebook'].is_alive():
        return

# New signature:
def start_facebook_thread(user_id):
    if user_id not in _threads:
        _threads[user_id] = {}
        _drivers[user_id] = {}
    
    if 'facebook' in _threads[user_id] and _threads[user_id]['facebook'].is_alive():
        return
    
    driver = _create_driver('facebook', user_id)
    thread = threading.Thread(
        target=run_facebook_scraper,
        args=(driver, f"facebook_{user_id}", user_id),  # Pass user_id
        daemon=True,
        name=f"facebook_{user_id}"
    )
    _threads[user_id]['facebook'] = thread
    _drivers[user_id]['facebook'] = driver
    thread.start()
```

3. **Update ALL start/stop functions:**
- `start_facebook_thread(user_id)`
- `start_craigslist_thread(user_id)`
- `start_ksl_thread(user_id)`
- `start_ebay_thread(user_id)`
- `start_poshmark_thread(user_id)`
- `start_mercari_thread(user_id)`
- `stop_facebook_thread(user_id)`
- etc.

4. **Add resource limits:**
```python
MAX_SCRAPERS_PER_USER = 6  # All 6 scrapers max
MAX_CONCURRENT_USERS = 100  # System-wide limit

def get_active_scraper_count(user_id):
    """Count how many scrapers user has running"""
    if user_id not in _threads:
        return 0
    return sum(1 for thread in _threads[user_id].values() if thread.is_alive())

def get_total_active_scrapers():
    """Count total scrapers across all users"""
    total = 0
    for user_threads in _threads.values():
        total += sum(1 for thread in user_threads.values() if thread.is_alive())
    return total
```

---

## 🌐 App Route Changes

### Update `app.py` - Start/Stop Routes

**Before:**
```python
@app.route("/start/<site>")
@login_required
def start(site):
    if site == "facebook":
        start_facebook()
    # ... etc
```

**After:**
```python
@app.route("/start/<site>")
@login_required
def start(site):
    user_id = current_user.id  # ← Get current user
    
    # Check resource limits
    from scraper_thread import get_active_scraper_count, MAX_SCRAPERS_PER_USER
    if get_active_scraper_count(user_id) >= MAX_SCRAPERS_PER_USER:
        flash("Maximum scrapers already running. Please stop one first.", "error")
        return redirect(url_for("dashboard"))
    
    if site == "facebook":
        start_facebook(user_id)  # ← Pass user_id
    elif site == "craigslist":
        start_craigslist(user_id)  # ← Pass user_id
    # ... etc
```

**Stop routes:**
```python
@app.route("/stop/<site>")
@login_required
def stop(site):
    user_id = current_user.id  # ← Get current user
    
    if site == "facebook":
        stop_facebook(user_id)  # ← Pass user_id
    # ... etc
```

---

## 🔒 Resource Limits & Safety

### Per-User Limits
```python
MAX_SCRAPERS_PER_USER = 6  # Can run all 6 scrapers
SCRAPER_CHECK_INTERVAL_MIN = 30  # Minimum 30 seconds between checks
```

### System-Wide Limits
```python
MAX_CONCURRENT_USERS = 100  # Max users with active scrapers
MAX_TOTAL_SCRAPERS = 500   # System-wide scraper limit
```

### Memory Management
```python
# Clean up inactive user threads periodically
def cleanup_inactive_users():
    """Remove threads/drivers for users with no active scrapers"""
    inactive_users = []
    for user_id, user_threads in _threads.items():
        if all(not thread.is_alive() for thread in user_threads.values()):
            inactive_users.append(user_id)
    
    for user_id in inactive_users:
        # Clean up drivers
        if user_id in _drivers:
            for driver in _drivers[user_id].values():
                try:
                    driver.quit()
                except:
                    pass
            del _drivers[user_id]
        
        # Clean up thread references
        if user_id in _threads:
            del _threads[user_id]
```

---

## 📊 Database Schema (Already Supports This!)

Good news - the database already has everything we need:

### Settings Table
```sql
CREATE TABLE settings (
    username TEXT,      -- ← Already supports per-user!
    key TEXT,
    value TEXT,
    UNIQUE(username, key)
)
```

### Listings Table
```sql
CREATE TABLE listings (
    user_id TEXT,       -- ← Already tracks user!
    FOREIGN KEY (user_id) REFERENCES users (username)
)
```

**No database migrations needed!** Just need to use the existing columns properly.

---

## 🧪 Testing Plan

### Test Case 1: Settings Isolation
```python
# Create two test users
user_a = "test_alice"
user_b = "test_bob"

# Set different settings
update_setting("keywords", "Firebird", username=user_a)
update_setting("keywords", "Tesla", username=user_b)

# Start scrapers for both
start_craigslist(user_a)
start_craigslist(user_b)

# Verify:
# - Alice's scraper searches for "Firebird"
# - Bob's scraper searches for "Tesla"
# - Alice sees only Firebird listings
# - Bob sees only Tesla listings
```

### Test Case 2: Independent Control
```python
# User A starts scraper
start_craigslist(user_a)

# User B starts scraper
start_craigslist(user_b)

# User A stops their scraper
stop_craigslist(user_a)

# Verify:
# - User A's scraper stopped
# - User B's scraper still running
```

### Test Case 3: Resource Limits
```python
# User tries to start 7th scraper
for i in range(7):
    start_scraper(user_a, scraper_names[i])

# Verify:
# - First 6 scrapers start successfully
# - 7th scraper rejected with error message
```

---

## 📁 File Checklist

- [ ] `scrapers/common.py` ✅ (DONE)
- [ ] `scrapers/craigslist.py` ✅ (DONE)
- [ ] `scrapers/ebay.py` ⏳
- [ ] `scrapers/ksl.py` ⏳
- [ ] `scrapers/mercari.py` ⏳
- [ ] `scrapers/facebook.py` ⏳
- [ ] `scrapers/poshmark.py` ⏳
- [ ] `scraper_thread.py` ⏳ (Major refactor needed)
- [ ] `app.py` (routes) ⏳
- [ ] Test multi-user scenarios ⏳

---

## ⚡ Quick Implementation Script

Here's a Python script to help update scrapers programmatically:

```python
import re

def update_scraper_file(filepath):
    """Update a scraper file to support per-user operation"""
    with open(filepath, 'r') as f:
        content = f.read()
    
    # 1. Update check_<scraper> signature
    content = re.sub(
        r'def check_(\w+)\(flag_name=SITE_NAME\):',
        r'def check_\1(flag_name=SITE_NAME, user_id=None):',
        content
    )
    
    # 2. Update load_settings calls
    content = content.replace(
        'settings = load_settings()',
        'settings = load_settings(username=user_id)'
    )
    
    # 3. Update send_discord_message signature
    content = re.sub(
        r'def send_discord_message\(title, link, price=None, image_url=None\):',
        r'def send_discord_message(title, link, price=None, image_url=None, user_id=None):',
        content
    )
    
    # 4. Update save_listing calls
    content = re.sub(
        r'save_listing\((.*?), SITE_NAME\)',
        r'save_listing(\1, SITE_NAME, user_id=user_id)',
        content
    )
    
    # 5. Update run_<scraper>_scraper signature
    content = re.sub(
        r'def run_(\w+)_scraper\(flag_name=SITE_NAME\):',
        r'def run_\1_scraper(flag_name=SITE_NAME, user_id=None):',
        content
    )
    
    # Write back
    with open(filepath, 'w') as f:
        f.write(content)
    
    print(f"Updated {filepath}")

# Usage:
# update_scraper_file('scrapers/ebay.py')
# update_scraper_file('scrapers/ksl.py')
# etc.
```

---

## 🎯 Next Steps

1. **Decision Point**: Do you want me to:
   - A) Continue and update all remaining scrapers now?
   - B) Provide you with this guide to complete manually?
   - C) Create the update script and let you run it?

2. **After scrapers are updated**, need to:
   - Refactor `scraper_thread.py` for per-user threads
   - Update `app.py` routes
   - Add resource limits
   - Test with multiple users

3. **Deployment considerations**:
   - Announce maintenance window
   - Backup database before deployment
   - Test with 2-3 users first
   - Monitor resource usage
   - Gradually roll out to all users

---

## 📞 Support

This is a significant architectural change. Consider:
- Testing thoroughly in staging environment
- Starting with a small user subset
- Monitoring server resources (RAM, CPU)
- Having rollback plan ready
- Documenting new behavior for users

---

## 💰 Cost/Benefit

**Costs:**
- Development time: ~2-4 hours
- Testing time: ~2-3 hours
- Increased server resources: ~2-3x RAM usage

**Benefits:**
- True multi-tenancy
- No user interference
- Scalable to thousands of users
- Professional SaaS architecture
- Happy users!

**ROI:** Essential for SaaS platform - worth the investment!

