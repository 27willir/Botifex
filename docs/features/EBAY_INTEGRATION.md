# eBay Scraper Integration

## Overview
A fully integrated eBay scraper has been added to the Super-Bot application. eBay is now included in the **FREE plan** alongside Craigslist, giving free users access to two marketplace platforms.

## What Was Implemented

### 1. eBay Scraper (`scrapers/ebay.py`)
- Full-featured scraper following the same pattern as other scrapers
- Uses BeautifulSoup for HTML parsing (no Selenium required)
- Supports all user settings: keywords, price range, location, refresh interval
- Extracts: title, price, link, and image URLs
- Thread-safe with proper error handling and retry logic
- Automatic deduplication (tracks seen listings for 24 hours)
- Persistent storage of seen listings in `ebay_seen.json`

### 2. Subscription Tier Updates (`subscriptions.py`)
- **Free Tier**: Now includes `['craigslist', 'ebay']` - 2 platforms
- **Standard Tier**: Updated to include all 4 platforms: `['craigslist', 'facebook', 'ksl', 'ebay']`
- **Pro Tier**: Updated to include all 4 platforms: `['craigslist', 'facebook', 'ksl', 'ebay']`

### 3. Thread Management (`scraper_thread.py`)
- Added `start_ebay()`, `stop_ebay()`, and `is_ebay_running()` functions
- Integrated eBay into `stop_all_scrapers()` and `get_scraper_status()`
- Updated `list_sites()` to include eBay
- Added eBay to generic `start_scraper()`, `stop_scraper()`, and `running()` helper functions

### 4. Flask App Integration (`app.py`)
- Imported eBay scraper functions
- Updated status endpoints to include eBay
- Added eBay to start/stop route handlers
- Updated validation lists to accept 'ebay' as a valid marketplace

### 5. UI Updates
- **templates/selling.html**: Added eBay checkbox option for marketplace selection
- **templates/subscription_plans.html**: Updated all plan descriptions to reflect eBay inclusion
  - Free: "2 platforms (Craigslist & eBay)"
  - Standard: "All platforms (Craigslist, Facebook, KSL, eBay)"
  - Pro: "All platforms (Craigslist, Facebook, KSL, eBay)"
- **templates/index.html**: Automatically displays eBay in scraper controls (uses dynamic status dict)

## Features

### eBay Search Capabilities
- **Keyword Search**: Searches for all configured keywords
- **Price Filtering**: Respects min/max price settings
- **Sort by Newly Listed**: Automatically sorts results by newest listings first
- **Condition Filter**: Set to used items (configurable in code)
- **Items per Page**: Fetches 50 items per request for better coverage

### Error Handling
- Exponential backoff retry logic (3 attempts)
- Network error handling with timeout protection
- Validation of all listing data before saving
- Graceful degradation if eBay is unavailable

### Data Extraction
The scraper extracts:
- **Title**: Item title from search results
- **Price**: Parsed from price elements (handles various formats)
- **Link**: Direct link to listing (tracking parameters removed)
- **Image URL**: High-quality product images (filters out icons/placeholders)
- **Source**: Always tagged as "ebay" in the database

## Usage

### For Free Users
1. Log in to your account
2. Go to the main dashboard
3. eBay will appear in the scraper controls alongside Craigslist
4. Click "Start" next to eBay to begin scraping
5. New eBay listings matching your keywords and price range will appear in the Recent Listings table

### For Paid Users
- Standard and Pro tier users have access to all platforms including eBay
- Use eBay alongside Craigslist, Facebook, and KSL simultaneously

### Configuration
eBay uses the same global settings as other scrapers:
- **Keywords**: Configured in Settings (Free: 2 keywords, Standard: 10, Pro: unlimited)
- **Price Range**: Set min/max price in Settings
- **Refresh Interval**: How often to check for new listings (Free: 10 min, Standard: 5 min, Pro: 1 min)
- **Location**: Currently uses search term location (can be enhanced for zip code searches)

## Technical Details

### API Endpoint
eBay scraper uses the public eBay search URL:
```
https://www.ebay.com/sch/i.html
```

### Query Parameters
- `_nkw`: Search keywords
- `_udlo`: Minimum price
- `_udhi`: Maximum price
- `_sop`: Sort order (10 = newly listed)
- `LH_ItemCondition`: Condition filter (3000 = used)
- `_ipg`: Items per page (50)

### Performance
- No Selenium required (faster and more lightweight than Facebook scraper)
- Minimal resource usage
- Faster response times compared to browser-based scrapers

## Files Modified

1. `scrapers/ebay.py` - NEW FILE (381 lines)
2. `subscriptions.py` - Updated tier definitions
3. `scraper_thread.py` - Added eBay thread management
4. `app.py` - Integrated eBay into routes and status checks
5. `templates/selling.html` - Added eBay checkbox
6. `templates/subscription_plans.html` - Updated plan descriptions

## Testing

To test the eBay scraper:

```bash
# Start the application
python app.py

# In the web interface:
# 1. Log in
# 2. Go to Settings and configure keywords (e.g., "iPhone", "PlayStation")
# 3. Set price range (e.g., $100 - $1000)
# 4. Go to Dashboard
# 5. Click "Start" for eBay
# 6. Wait for listings to appear in the Recent Listings table
```

## Notes

- eBay's HTML structure may change over time; the scraper includes multiple fallback extraction methods for robustness
- The scraper respects eBay's rate limits with human-like delays between requests
- Listings are deduplicated based on normalized URLs (removes query parameters)
- Seen listings expire after 24 hours, allowing items to be re-notified if still available

## Future Enhancements

Potential improvements:
- Zip code-based location search
- Category filtering
- Condition filtering (new, used, refurbished)
- Seller rating filters
- Buy It Now vs Auction filtering
- Shipping cost consideration
- International shipping filters

## Support

If you encounter any issues with the eBay scraper:
1. Check the logs in `logs/superbot.log`
2. Ensure your internet connection is stable
3. Verify your keywords and price range settings are correct
4. Check the `ebay_seen.json` file for proper operation

---

**Integration Complete**: eBay is now fully integrated and included in the free plan! 🎉

