# ⚠️ User Isolation Issue - Scrapers & Settings

## 🔴 Critical Finding: Scrapers Are Globally Shared

**YES, users currently interfere with each other's scrapers and settings!**

This is a significant architectural issue that needs to be addressed for proper multi-user operation.

---

## 🔍 Problem Analysis

### Issue 1: **Global Scrapers**

Currently, scrapers run **globally** - only ONE instance of each scraper runs at a time for ALL users.

**Evidence:**
```python
# app.py lines 497-532
@app.route("/start/<site>")
@login_required
def start(site):
    if site == "facebook":
        start_facebook()  # ← Starts GLOBAL Facebook scraper
    elif site == "craigslist":
        start_craigslist()  # ← Starts GLOBAL Craigslist scraper
```

**What this means:**
- When User A starts Craigslist, it starts for the entire application
- When User B also starts Craigslist, they get the SAME running instance
- When User A stops it, it stops for User B too!

### Issue 2: **Global Settings**

Scrapers load settings WITHOUT specifying a user:

**Evidence:**
```python
# scrapers/facebook.py line 154
def load_settings():
    settings = get_settings()  # ← No username parameter!
```

**Database function:**
```python
# db_enhanced.py lines 1039-1048
def get_settings(username=None):
    if username:
        c.execute("SELECT key, value FROM settings WHERE username = ?", (username,))
    else:
        c.execute("SELECT key, value FROM settings WHERE username IS NULL")
    # ← Returns GLOBAL settings when username is None
```

**What this means:**
- All scrapers use the same **global settings**
- If User A wants to search for "Firebird", and User B wants "Camaro"
- They can't both run - last one to update settings wins!

### Issue 3: **Listings ARE User-Isolated (Good!)**

The good news: Listings are saved with a `user_id`:

```python
# db_enhanced.py line 1313
INSERT INTO listings (..., user_id) VALUES (..., ?)
```

**What this means:**
- Listings found are properly attributed to users
- Each user sees their own listings
- This part works correctly!

---

## 🎯 Current Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Flask Application                         │
│                                                              │
│  User A clicks "Start Craigslist" → Starts GLOBAL scraper   │
│  User B clicks "Start Craigslist" → Uses SAME scraper       │
│  User C clicks "Start Craigslist" → Uses SAME scraper       │
│                                                              │
│         ↓                                                    │
│  ONE Craigslist Scraper Instance (Shared)                   │
│         ↓                                                    │
│  Uses GLOBAL Settings (No user context)                     │
│         ↓                                                    │
│  Saves listings with user_id (This part works!)             │
└─────────────────────────────────────────────────────────────┘
```

---

## 💥 Real-World Impact

### Scenario 1: Settings Conflict
```
User A: Sets keywords="Firebird", location="boise", price=5000-15000
User B: Sets keywords="Tesla", location="seattle", price=30000-50000

Result: Last one wins! If User B updates after User A:
- Both scrapers now search for Tesla in Seattle
- User A sees Tesla listings instead of Firebirds
```

### Scenario 2: Scraper Control Conflict
```
User A: Starts Craigslist scraper
User B: Doesn't want Craigslist running (wants to save resources)
User B: Stops Craigslist scraper

Result: User A's scraper stops too!
```

### Scenario 3: Interval Conflict
```
User A: Sets interval to 30 seconds (wants fast updates)
User B: Sets interval to 300 seconds (wants slow, gentle scraping)

Result: Last setting wins - both users get same interval
```

---

## ✅ What's Already Isolated (Working Correctly)

1. **Listings** ✅
   - Each listing has a `user_id`
   - Users only see their own listings
   - Database: `listings.user_id FOREIGN KEY`

2. **Favorites** ✅
   - User-specific favorites
   - Database: `favorites.username FOREIGN KEY`

3. **Saved Searches** ✅
   - User-specific saved searches
   - Database: `saved_searches.username FOREIGN KEY`

4. **Price Alerts** ✅
   - User-specific alerts
   - Database: `price_alerts.username FOREIGN KEY`

5. **Subscriptions** ✅
   - User-specific subscription tiers
   - Proper access control per user

---

## 🚨 What's NOT Isolated (Problem Areas)

1. **Scraper Instances** ❌
   - Only ONE instance per scraper
   - Shared across all users
   - `scraper_thread.py` manages global threads

2. **Scraper Settings** ❌
   - Scrapers call `get_settings()` with no username
   - Uses global settings table entries
   - No user context in scraper execution

3. **Scraper Control** ❌
   - Start/stop affects all users
   - No per-user running state
   - Global `running_flags` dictionaries

---

## 🔧 Recommended Solutions

### Option 1: **Quick Fix - Admin-Only Scrapers** (Easiest)

Make scrapers admin-only and use global settings:

**Pros:**
- Minimal code changes
- Works for single-admin deployments
- Quick to implement

**Cons:**
- Not suitable for multi-user SaaS
- Users can't customize their searches
- Doesn't scale

**Implementation:**
```python
@app.route("/start/<site>")
@login_required
@admin_required  # ← Add this decorator
def start(site):
    # Only admins can control scrapers
```

### Option 2: **Per-User Scrapers** (Recommended for SaaS)

Each user gets their own scraper instances:

**Pros:**
- True multi-tenancy
- Each user can customize everything
- Scales to many users
- Proper SaaS architecture

**Cons:**
- Significant code changes required
- More resource intensive
- Requires scraper thread management per user

**Architecture:**
```
User A → Scraper Instance A (uses User A's settings) → User A's listings
User B → Scraper Instance B (uses User B's settings) → User B's listings
User C → Scraper Instance C (uses User C's settings) → User C's listings
```

**Implementation Steps:**
1. Pass `user_id` to scraper functions
2. Update `load_settings()` to accept username
3. Create per-user thread management
4. Update `scraper_thread.py` to track user-specific threads
5. Resource limiting (max scrapers per user)

### Option 3: **Hybrid - User Settings + Shared Scrapers** (Middle Ground)

**Concept:** Keep global scrapers but search for ALL users' keywords:

**Pros:**
- Resource efficient (one scraper instance)
- Users can still customize keywords
- Less complex than Option 2

**Cons:**
- Can't customize location/radius per user
- May find too many listings
- Still some settings conflicts

**Implementation:**
- Aggregate all users' keywords
- Search for union of all keywords
- Filter and distribute results to relevant users

---

## 📊 Current Database Schema

### Settings Table (Supports per-user, but not used!)
```sql
CREATE TABLE settings (
    username TEXT,          -- ← Can be NULL (global) or specific user
    key TEXT,
    value TEXT,
    UNIQUE(username, key)
)
```

**The infrastructure exists!** We just need to use it.

### Listings Table (Already per-user)
```sql
CREATE TABLE listings (
    user_id TEXT,          -- ← Already tracks which user found it
    FOREIGN KEY (user_id) REFERENCES users (username)
)
```

---

## 🎯 Immediate Action Items

### Priority 1: **Document Current Behavior**
- ✅ Analyze architecture (DONE - this document)
- ⬜ Inform stakeholders of limitation
- ⬜ Decide on deployment model

### Priority 2: **Choose Architecture**
Based on use case:

**Single User / Admin Use:**
→ Go with Option 1 (Admin-only scrapers)

**Small Team (5-10 users):**
→ Go with Option 3 (Hybrid approach)

**SaaS Platform (Many users):**
→ Go with Option 2 (Per-user scrapers)

### Priority 3: **Implementation**
After deciding architecture:
1. Update scraper initialization
2. Pass user context to scrapers
3. Update settings loading
4. Update thread management
5. Add resource limits
6. Test multi-user scenarios

---

## 🧪 Testing Multi-User Scenarios

### Test Case 1: Settings Isolation
```
1. User A sets keywords="Firebird"
2. User B sets keywords="Tesla"
3. Start scrapers for both
4. Verify User A only sees Firebirds
5. Verify User B only sees Teslas
```

### Test Case 2: Scraper Control Isolation
```
1. User A starts Craigslist
2. User B starts Craigslist
3. User A stops Craigslist
4. Verify User B's scraper still runs
```

### Test Case 3: Concurrent Operation
```
1. User A starts all scrapers
2. User B starts all scrapers
3. Verify both users' scrapers run independently
4. Verify no conflicts or interference
```

---

## 💡 Workarounds for Current System

Until proper isolation is implemented:

### For Admins:
1. **Run scrapers centrally** - Admin controls all scrapers
2. **Use broad keywords** - Search for multiple users' interests
3. **Manual distribution** - Tag listings for specific users

### For Users:
1. **Coordinate timing** - Agree when each user runs scrapers
2. **Share keywords** - Use common search terms
3. **Filter after scraping** - Sort through all results

### For Developers:
1. **Document limitation** - Make it clear in docs
2. **Add warnings** - "Scraper settings are shared"
3. **Plan migration** - When to implement isolation

---

## 📚 Related Files

- `app.py` - Scraper start/stop routes (lines 497-576)
- `scraper_thread.py` - Global thread management
- `scrapers/*.py` - Individual scraper implementations
- `db_enhanced.py` - Settings and listings database functions
- `scrapers/common.py` - Shared scraper utilities

---

## ⚖️ Conclusion

**Current State:**
- ❌ Scrapers are globally shared
- ❌ Settings are global by default
- ✅ Listings are properly user-isolated
- ⚠️ System works but only for single-user or admin-controlled use

**Recommendation:**
Choose architecture based on deployment:
- **Personal/Admin Use** → Keep as-is or make admin-only
- **Team Use** → Implement hybrid approach
- **SaaS Platform** → Implement per-user scrapers

**Impact:**
This is a foundational architecture decision that affects scalability and user experience. Address early before user base grows.

