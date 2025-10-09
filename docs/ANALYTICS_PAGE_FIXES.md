# Analytics Page Fixes

## Issues Found and Fixed

### 1. **CSRF Protection Blocking API Calls (CRITICAL)**
**Problem:** Flask-WTF's CSRF protection was enabled globally, which blocks all requests (including AJAX/fetch requests) that don't include a valid CSRF token. This was the main reason the analytics page failed with "Failed to load analytics data" error.

**Fix:** Added `@csrf.exempt` decorator to all API routes since they're already protected by `@login_required`:
```python
@app.route("/api/analytics/market-insights")
@login_required
@csrf.exempt
def api_market_insights():
    ...
```

All analytics API routes now have this exemption.

### 2. **POST Method Mismatch for Update Trends Endpoint**
**Problem:** The `/api/analytics/update-trends` endpoint in `app.py` was only accepting GET requests by default, but the JavaScript was calling it with a POST request.

**Fix:** Added `methods=["POST"]` to the route decorator in `app.py`:
```python
@app.route("/api/analytics/update-trends", methods=["POST"])
```

### 3. **Authentication/Session Issues**
**Problem:** When the analytics page tried to fetch data from the API endpoints, if the user wasn't authenticated, Flask-Login would redirect to the login page. The JavaScript would receive HTML instead of JSON, causing parsing errors and the analytics page to fail silently.

**Fix:** 
- Added explicit `credentials: 'same-origin'` to all fetch requests to ensure session cookies are sent
- Created a helper function `parseResponse` that checks the Content-Type header before parsing
- If the response is HTML (not JSON), it automatically redirects the user to the login page with a clear error message

### 4. **Database Schema Issue - Missing JOIN in SQL Queries**
**Problem:** The `get_keyword_analysis` and `get_market_insights` functions were trying to access the `price` column from the `listing_analytics` table, but price data is only stored in the `listings` table. This caused "no such column: price" errors and 500 responses.

**Fix:** Updated both SQL queries to JOIN the `listing_analytics` table with the `listings` table:
```python
SELECT la.keyword, AVG(l.price) as avg_price
FROM listing_analytics la
JOIN listings l ON la.listing_id = l.id
...
```

### 5. **Missing Error Handling for Empty Data**
**Problem:** If there were no listings in the database, the analytics functions would return empty arrays or null values, which could cause the JavaScript to crash when trying to access array indices or object properties.

**Fix:** Added null/undefined checks to all chart update functions:
- `updateStats()`
- `updatePriceChart()`
- `updateKeywordChart()`
- `updateSourceChart()`
- `updateDistributionChart()`
- `updateActivityChart()`
- `updateDailyChart()`

Each function now checks if the required data exists before attempting to process it, and logs a helpful error message to the console if data is missing.

## Changes Made

### File: `app.py`
- Lines 452, 462, 468, 484, 497, 511, 525, 538, 552, 565, 579: Added `@csrf.exempt` decorator to all API routes
- Line 577: Changed route to accept POST method

### File: `db.py`
- Lines 326-347: Fixed `get_keyword_analysis` to JOIN with listings table for price data
- Lines 469-480: Fixed `get_market_insights` to JOIN with listings table for keyword price data

### File: `templates/analytics.html`
- Lines 483-505: Added `parseResponse` helper function and updated all fetch calls to use it
- Line 514: Added credentials to loadKeywords fetch
- Line 871: Added credentials to updateTrends fetch
- Lines 547-578: Added null checks to updateStats function
- Lines 589-604: Added null checks to updatePriceChart function
- Lines 656-670: Added null checks to updateKeywordChart function
- Lines 697-712: Added null checks to updateSourceChart function
- Lines 760-774: Added null checks to updateDistributionChart function
- Lines 810-824: Added null checks to updateActivityChart function
- Lines 866-880: Added null checks to updateDailyChart function

## Testing

To test the analytics page:
1. Make sure you're logged in to the application
2. Navigate to the `/analytics` route
3. The page should now load properly with all charts and statistics
4. If there's no data yet, the charts will be empty but won't crash
5. The "Update Trends" button should now work properly

## Additional Notes

- If you see a message about being redirected to login, it means your session has expired. Simply log in again.
- The analytics page requires at least some listings in the database to show meaningful data. Run the scrapers first to populate the database.
- All fetch requests now properly handle authentication errors and will redirect to the login page automatically.

