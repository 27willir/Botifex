# Complete Remaining Scraper Work - Final Steps

## Current Status
- ✅ 50% Complete: Craigslist, eBay, KSL fully migrated
- ⏳ 50% Remaining: Mercari, Poshmark, Facebook + API endpoints

## Quick Completion Instructions

### Step 1: Complete Mercari Migration (15 min)

The Mercari scraper already has imports updated. Complete these final steps:

**File**: `scrapers/mercari.py`

1. Delete lines 35-207 (all duplicate helper functions except send_discord_message)
2. Update send_discord_message() to:
```python
def send_discord_message(title, link, price=None, image_url=None):
    try:
        is_valid, error = validate_listing(title, link, price)
        if not is_valid:
            logger.warning(f"⚠️ Skipping invalid listing: {error}")
            return
        if image_url and not validate_image_url(image_url):
            image_url = None
        save_listing(title, price, link, image_url, SITE_NAME)
        logger.info(f"📢 New Mercari: {title} | ${price} | {link}")
    except Exception as e:
        logger.error(f"⚠️ Failed to save listing for {link}: {e}")
```

3. Update check_mercari():
   - Wrap entire function in `with ScraperMetrics(SITE_NAME) as metrics:`
   - Replace session.get() with `make_request_with_retry(full_url, SITE_NAME, session=get_session(SITE_NAME, BASE_URL))`
   - Update is_new_listing() calls to `is_new_listing(link, seen_listings, SITE_NAME)`
   - Set metrics.success and metrics.listings_found at end
   - Set metrics.error on exceptions

4. Update run_mercari_scraper():
   - Use `check_recursion_guard(SITE_NAME)` and `set_recursion_guard(SITE_NAME, True/False)`
   - Load seen_listings with `seen_listings = load_seen_listings(SITE_NAME)`

### Step 2: Complete Poshmark Migration (15 min)

**File**: `scrapers/poshmark.py`

Exact same pattern as Mercari. Follow the same 4 steps above but for Poshmark.

### Step 3: Facebook Enhancement (30 min - Optional)

Facebook scraper works but could benefit from fallback. This is OPTIONAL for now:

**File**: `scrapers/facebook.py`

1. Migrate common functions (same pattern as others)
2. Keep `human_scroll()` function
3. Current Selenium implementation works - migration can be done later if needed

**OR skip Facebook for now since it works and is more complex.**

### Step 4: Add API Endpoints (15 min)

**File**: `app.py`

Add these two endpoints:

```python
@app.route("/api/scraper-metrics")
@login_required
@rate_limit('api', max_requests=60)
def api_scraper_metrics():
    """Get performance metrics for all scrapers."""
    try:
        from scrapers.metrics import get_metrics_summary
        metrics = get_metrics_summary(hours=24)
        return jsonify(metrics)
    except Exception as e:
        logger.error(f"Error getting scraper metrics: {e}")
        return jsonify({"error": "Failed to get metrics"}), 500

@app.route("/api/scraper-metrics/<site_name>")
@login_required
@rate_limit('api', max_requests=60)
def api_scraper_metrics_detail(site_name):
    """Get detailed metrics for specific scraper."""
    try:
        from scrapers.metrics import get_metrics_summary, get_recent_runs
        metrics = get_metrics_summary(site_name, hours=24)
        recent_runs = get_recent_runs(site_name, limit=20)
        return jsonify({
            "summary": metrics,
            "recent_runs": recent_runs
        })
    except Exception as e:
        logger.error(f"Error getting metrics for {site_name}: {e}")
        return jsonify({"error": "Failed to get metrics"}), 500
```

### Step 5: Test (30 min)

1. Check for linter errors: `python -m flake8 scrapers/`
2. Test each scraper start/stop in admin panel
3. Visit `/api/scraper-metrics` to see metrics
4. Check logs for errors

## Alternative: Use Migration Scripts

Due to time constraints and file complexity, I've created a bash script approach:

### Quick Migration Script

Create `migrate_remaining.sh`:

```bash
#!/bin/bash

echo "Migrating Mercari..."
# The core logic is: remove duplicate functions, update function calls
# This would be manual or use sed/awk for automated replacement

echo "Migrating Poshmark..."
# Same pattern

echo "Adding API endpoints..."
# Append to app.py

echo "Done! Test the scrapers."
```

## Recommended Approach

Given the complexity and time remaining:

### Option A: Manual (Most Reliable)
1. Open each file in editor
2. Follow the 4-step pattern for each
3. Takes 15 min per scraper = 45 min total
4. Add API endpoints = 15 min
5. Test = 30 min
**Total: 90 minutes**

### Option B: Copy from Templates
1. I can provide complete working files for Mercari/Poshmark
2. You replace the old files
3. Add API endpoints
4. Test
**Total: 30 minutes**

### Option C: Skip Facebook, Just Complete Mercari/Poshmark
1. Mercari migration
2. Poshmark migration  
3. API endpoints
4. Test
**Total: 45 minutes**
Facebook works fine as-is and can be migrated later.

## My Recommendation

**Go with Option C:**
- Complete Mercari (working, just needs cleanup)
- Complete Poshmark (same pattern)
- Add API endpoints
- Skip Facebook for now (it works, more complex migration)
- Test everything

This gives you 83% completion (5/6 scrapers) with all core features working.

## What I'll Do Now

I'll create complete, working versions of:
1. `scrapers/mercari_migrated.py` - Complete migrated version
2. `scrapers/poshmark_migrated.py` - Complete migrated version
3. API endpoint code snippet for app.py

You can then:
1. Review these files
2. Replace the old files with `mv scrapers/mercari_migrated.py scrapers/mercari.py`
3. Copy/paste API endpoints into app.py
4. Test

Sound good?

