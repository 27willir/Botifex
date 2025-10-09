# 🔌 API Documentation
## Super-Bot - Complete API Reference

**Version:** 2.0  
**Base URL:** `http://localhost:5000`  
**Authentication:** Session-based (Flask-Login)

---

## 📑 TABLE OF CONTENTS

1. [Authentication](#authentication)
2. [Favorites API](#favorites-api)
3. [Saved Searches API](#saved-searches-api)
4. [Price Alerts API](#price-alerts-api)
5. [Listings API](#listings-api)
6. [Analytics API](#analytics-api)
7. [Seller Listings API](#seller-listings-api)
8. [Error Responses](#error-responses)

---

## 🔐 AUTHENTICATION

All API endpoints require authentication via session cookies.

### Login
```http
POST /login
Content-Type: application/x-www-form-urlencoded

username=user&password=pass
```

### Logout
```http
GET /logout
```

---

## ⭐ FAVORITES API

### Get All Favorites
```http
GET /api/favorites
GET /api/favorites?limit=50
```

**Response:**
```json
{
  "favorites": [
    {
      "id": 123,
      "title": "2002 Corvette Z06",
      "price": 28000,
      "link": "https://...",
      "image_url": "https://...",
      "source": "craigslist",
      "created_at": "2025-10-09T10:30:00",
      "notes": "Great condition!",
      "favorited_at": "2025-10-09T15:45:00"
    }
  ],
  "count": 1
}
```

### Add to Favorites
```http
POST /api/favorites/123
Content-Type: application/json

{
  "notes": "Check this out later"
}
```

**Response:**
```json
{
  "message": "Added to favorites",
  "favorited": true
}
```

### Remove from Favorites
```http
DELETE /api/favorites/123
```

**Response:**
```json
{
  "message": "Removed from favorites",
  "favorited": false
}
```

### Check if Favorited
```http
GET /api/favorites/123/check
```

**Response:**
```json
{
  "favorited": true
}
```

### Update Favorite Notes
```http
PUT /api/favorites/123/notes
Content-Type: application/json

{
  "notes": "Updated notes"
}
```

**Response:**
```json
{
  "message": "Notes updated"
}
```

---

## 💾 SAVED SEARCHES API

### Get All Saved Searches
```http
GET /api/saved-searches
```

**Response:**
```json
{
  "searches": [
    {
      "id": 1,
      "name": "Affordable Corvettes",
      "keywords": "Corvette",
      "min_price": 15000,
      "max_price": 30000,
      "sources": "craigslist,facebook",
      "location": "boise",
      "radius": 50,
      "notify_new": true,
      "created_at": "2025-10-09T10:00:00",
      "last_run": null
    }
  ],
  "count": 1
}
```

### Create Saved Search
```http
POST /api/saved-searches
Content-Type: application/json

{
  "name": "Cheap Firebirds",
  "keywords": "Firebird",
  "min_price": 5000,
  "max_price": 15000,
  "sources": "craigslist,ksl",
  "location": "salt lake city",
  "radius": 100,
  "notify_new": true
}
```

**Required Fields:** `name`  
**Optional Fields:** All search parameters

**Response:**
```json
{
  "message": "Search saved",
  "search_id": 2
}
```

### Delete Saved Search
```http
DELETE /api/saved-searches/1
```

**Response:**
```json
{
  "message": "Search deleted"
}
```

---

## 🚨 PRICE ALERTS API

### Get All Price Alerts
```http
GET /api/price-alerts
```

**Response:**
```json
{
  "alerts": [
    {
      "id": 1,
      "keywords": "Corvette",
      "threshold_price": 20000,
      "alert_type": "under",
      "active": true,
      "last_triggered": null,
      "created_at": "2025-10-09T12:00:00"
    }
  ],
  "count": 1
}
```

### Create Price Alert
```http
POST /api/price-alerts
Content-Type: application/json

{
  "keywords": "Firebird",
  "threshold_price": 12000,
  "alert_type": "under"
}
```

**Fields:**
- `keywords` (required): Search keywords
- `threshold_price` (required): Price threshold (integer)
- `alert_type` (optional): "under" or "over" (default: "under")

**Response:**
```json
{
  "message": "Price alert created",
  "alert_id": 2
}
```

### Delete Price Alert
```http
DELETE /api/price-alerts/1
```

**Response:**
```json
{
  "message": "Alert deleted"
}
```

### Toggle Price Alert
```http
POST /api/price-alerts/1/toggle
```

**Response:**
```json
{
  "message": "Alert toggled"
}
```

---

## 📝 LISTINGS API

### Get Listings
```http
GET /api/listings
```

**Response:**
```json
{
  "listings": [
    {
      "id": 123,
      "title": "2002 Corvette Z06",
      "price": 28000,
      "link": "https://...",
      "image_url": "https://...",
      "source": "craigslist",
      "created_at": "2025-10-09T10:30:00"
    }
  ]
}
```

### Get Scraper Status
```http
GET /api/status
```

**Response:**
```json
{
  "facebook": true,
  "craigslist": false,
  "ksl": true
}
```

---

## 📊 ANALYTICS API

### Market Insights
```http
GET /api/analytics/market-insights
GET /api/analytics/market-insights?days=30&keyword=Corvette
```

**Parameters:**
- `days` (optional): Number of days to analyze (1-365, default: 30)
- `keyword` (optional): Filter by keyword

### Keyword Trends
```http
GET /api/analytics/keyword-trends?days=30
```

### Price Analytics
```http
GET /api/analytics/price-analytics?days=30&source=craigslist
```

### Source Comparison
```http
GET /api/analytics/source-comparison?days=30
```

### Keyword Analysis
```http
GET /api/analytics/keyword-analysis?days=30&limit=20
```

### Hourly Activity
```http
GET /api/analytics/hourly-activity?days=7
```

### Price Distribution
```http
GET /api/analytics/price-distribution?days=30&bins=10
```

---

## 🏪 SELLER LISTINGS API

### Get Seller Listings
```http
GET /api/seller-listings
GET /api/seller-listings?status=active
```

### Create Seller Listing
```http
POST /api/seller-listings
Content-Type: application/json

{
  "title": "2002 Corvette Z06",
  "description": "Excellent condition...",
  "price": 28000,
  "category": "cars",
  "location": "Boise, ID",
  "images": "https://...",
  "marketplaces": ["craigslist", "facebook"]
}
```

### Update Seller Listing
```http
PUT /api/seller-listings/123
Content-Type: application/json

{
  "price": 27000,
  "status": "sold"
}
```

### Delete Seller Listing
```http
DELETE /api/seller-listings/123
```

---

## ❌ ERROR RESPONSES

### Standard Error Format
```json
{
  "error": "Error message here"
}
```

### HTTP Status Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 201 | Created |
| 400 | Bad Request |
| 401 | Unauthorized |
| 403 | Forbidden |
| 404 | Not Found |
| 429 | Rate Limit Exceeded |
| 500 | Internal Server Error |

### Rate Limit Response
```json
{
  "error": "Rate limit exceeded",
  "message": "Too many requests. Please try again in 1 minute(s).",
  "retry_after": 60
}
```

---

## 🔍 EXAMPLE WORKFLOWS

### Complete Favorites Workflow
```javascript
// 1. Check if listing is favorited
GET /api/favorites/123/check
→ {"favorited": false}

// 2. Add to favorites
POST /api/favorites/123
{"notes": "Great price!"}
→ {"message": "Added to favorites", "favorited": true}

// 3. Update notes
PUT /api/favorites/123/notes
{"notes": "Contact seller tomorrow"}
→ {"message": "Notes updated"}

// 4. Get all favorites
GET /api/favorites
→ {"favorites": [...], "count": 15}

// 5. Remove from favorites
DELETE /api/favorites/123
→ {"message": "Removed from favorites"}
```

### Complete Saved Search Workflow
```javascript
// 1. Create saved search
POST /api/saved-searches
{
  "name": "Dream Corvettes",
  "keywords": "Corvette Z06",
  "min_price": 25000,
  "max_price": 40000,
  "notify_new": true
}
→ {"search_id": 5}

// 2. Get all saved searches
GET /api/saved-searches
→ {"searches": [...], "count": 5}

// 3. Delete saved search
DELETE /api/saved-searches/5
→ {"message": "Search deleted"}
```

### Complete Price Alert Workflow
```javascript
// 1. Create price alert
POST /api/price-alerts
{
  "keywords": "Firebird Trans Am",
  "threshold_price": 18000,
  "alert_type": "under"
}
→ {"alert_id": 3}

// 2. Get all alerts
GET /api/price-alerts
→ {"alerts": [...], "count": 3}

// 3. Toggle alert (pause temporarily)
POST /api/price-alerts/3/toggle
→ {"message": "Alert toggled"}

// 4. Delete alert
DELETE /api/price-alerts/3
→ {"message": "Alert deleted"}
```

---

## 🧪 TESTING WITH cURL

### Test Favorites
```bash
# Login first
curl -c cookies.txt -X POST http://localhost:5000/login \
  -d "username=testuser&password=testpass"

# Add favorite (with cookies)
curl -b cookies.txt -X POST http://localhost:5000/api/favorites/1 \
  -H "Content-Type: application/json" \
  -d '{"notes": "Check this out!"}'

# Get favorites
curl -b cookies.txt http://localhost:5000/api/favorites
```

---

## 📚 RATE LIMITS

| Endpoint Type | Limit |
|---------------|-------|
| API (GET) | 60 requests/minute |
| API (POST/PUT/DELETE) | 30 requests/minute |
| Login | 5 requests/5 minutes |
| Registration | 3 requests/hour |
| Password Reset | 3 requests/hour |
| Email Verification | 10 requests/minute |

---

## 💡 BEST PRACTICES

1. **Always check for errors** in API responses
2. **Use rate limits wisely** - cache when possible
3. **Handle 429 responses** - implement exponential backoff
4. **Validate inputs** before sending to API
5. **Use HTTPS** in production
6. **Store session cookies securely**
7. **Implement CSRF tokens** for state-changing operations

---

*API Documentation - Super-Bot v2.0*  
*Last Updated: October 9, 2025*

