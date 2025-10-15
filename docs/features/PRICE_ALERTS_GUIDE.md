# 🚨 Price Alerts Feature - Complete Guide

## Overview

The Price Alerts feature allows users to set automatic notifications when marketplace listings match specific price criteria. This powerful monitoring system runs continuously in the background, checking new listings every 5 minutes and notifying users through multiple channels.

---

## ✨ Key Features

- **Keyword Monitoring:** Track specific search terms across all platforms
- **Price Thresholds:** Set alerts for prices above or below a target value
- **Multiple Alert Types:** 
  - "Under" - Notify when price drops below threshold
  - "Over" - Notify when price exceeds threshold
- **Active/Pause Toggle:** Temporarily disable alerts without deleting them
- **Rate Limiting:** Prevents spam by limiting triggers to once per hour per alert
- **Multi-Channel Notifications:**
  - Email notifications (HTML formatted)
  - SMS notifications (via Twilio)
  - Real-time WebSocket notifications
- **Full Management UI:** Create, view, pause, and delete alerts from web interface

---

## 🎯 How It Works

### 1. User Creates Alert
- Navigate to **Price Alerts** page from sidebar
- Enter keywords (e.g., "Corvette", "iPhone 15")
- Set price threshold (e.g., $20,000)
- Choose alert type ("under" or "over")
- Click "Create Alert"

### 2. Background Monitoring
- The scheduler runs a price alert checker every 5 minutes
- Checker retrieves all active alerts from database
- Fetches recent listings (last 100)
- For each alert:
  - Matches keywords in listing titles
  - Compares price against threshold
  - Triggers notifications if conditions met

### 3. Notification Delivery
When an alert triggers:
- **Email:** HTML-formatted email with listing details and direct link
- **SMS:** Concise text message with price and URL (if Twilio configured)
- **WebSocket:** Real-time browser notification (no page refresh needed)
- **Database:** Updates `last_triggered` timestamp

### 4. Rate Limiting
- Each alert can only trigger once per hour
- Prevents notification spam
- User can still receive alerts for different listings/alerts

---

## 🚀 Quick Start

### Step 1: Access Price Alerts
1. Login to your Super-Bot account
2. Click "Price Alerts" (🔔 icon) in the sidebar
3. You'll see the Price Alerts page with:
   - Info box explaining how alerts work
   - Create alert form
   - List of your existing alerts

### Step 2: Create Your First Alert

**Example 1: Alert for Cheap Corvettes**
```
Keywords: Corvette
Price Threshold: 20000
Alert Type: Under (Below)
```
This will notify you when Corvette listings appear UNDER $20,000.

**Example 2: Alert for Expensive iPhones**
```
Keywords: iPhone 15
Price Threshold: 1000
Alert Type: Over (Above)
```
This will notify you when iPhone 15 listings appear OVER $1,000.

### Step 3: Manage Your Alerts
- **Pause:** Temporarily disable without deleting
- **Activate:** Re-enable a paused alert
- **Delete:** Permanently remove an alert
- **View Status:** See when alert was last triggered

---

## 📋 User Interface Components

### Create Alert Form
- **Keywords Field:** Enter search terms (comma-separated for multiple)
- **Price Threshold:** Dollar amount (positive integer)
- **Alert Type Dropdown:** "Under (Below)" or "Over (Above)"
- **Create Button:** Submit new alert

### Alert Cards
Each alert displays:
- **Status Badge:** Green "Active" or Red "Paused"
- **Keywords:** What's being monitored
- **Price Threshold:** With colored type badge
- **Created Date:** When alert was set up
- **Last Triggered:** Timestamp or "Never triggered yet"
- **Action Buttons:** Pause/Activate and Delete

### Visual Feedback
- **Success Messages:** Green notifications for successful actions
- **Error Messages:** Red notifications for failures
- **Loading States:** Spinner while fetching data
- **Empty State:** Helpful message when no alerts exist
- **Hover Effects:** Cards glow blue on hover
- **Animations:** Smooth transitions for all interactions

---

## 🔧 Technical Details

### Database Schema
```sql
CREATE TABLE price_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    keywords TEXT NOT NULL,
    threshold_price INTEGER NOT NULL,
    alert_type TEXT DEFAULT 'under',
    active BOOLEAN DEFAULT 1,
    last_triggered DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
)
```

### API Endpoints

#### GET /api/price-alerts
Get all alerts for logged-in user.

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
      "last_triggered": "2025-10-12T14:30:00",
      "created_at": "2025-10-12T10:00:00"
    }
  ],
  "count": 1
}
```

#### POST /api/price-alerts
Create a new price alert.

**Request:**
```json
{
  "keywords": "Firebird",
  "threshold_price": 15000,
  "alert_type": "under"
}
```

**Response:**
```json
{
  "message": "Price alert created",
  "alert_id": 2
}
```

#### DELETE /api/price-alerts/{id}
Delete a specific alert.

**Response:**
```json
{
  "message": "Alert deleted"
}
```

#### POST /api/price-alerts/{id}/toggle
Toggle alert between active and paused.

**Response:**
```json
{
  "message": "Alert toggled"
}
```

### Background Worker

The price alert checker runs as a daemon thread in the main scheduler:

**File:** `scripts/scheduler.py`
**Function:** `price_alert_checker()`
**Frequency:** Every 5 minutes (300 seconds)
**Logic:**
1. Get all active alerts
2. Get recent listings (last 100)
3. For each alert:
   - Parse keywords (comma-separated)
   - Match keywords in listing titles (case-insensitive)
   - Compare price against threshold
   - Check rate limit (last triggered > 1 hour ago)
   - Send notifications if triggered
   - Update last_triggered timestamp

### Notification System

**Email Notifications:**
- HTML-formatted with attractive styling
- Includes listing title, price, source, and direct link
- Requires SMTP configuration in `.env`

**SMS Notifications:**
- Concise format (under 160 characters)
- Requires Twilio credentials in `.env`
- Optional - works without SMS if not configured

**WebSocket Notifications:**
- Real-time browser alerts
- No configuration needed
- Works automatically if WebSocket connected

---

## ⚙️ Configuration

### Required Setup
1. **Database:** Price alerts table is auto-created on first run
2. **Scheduler:** Must be running for alerts to trigger
3. **Login:** User must be authenticated

### Optional Setup (For Notifications)

**Email Notifications (`.env`):**
```bash
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your-email@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_FROM_EMAIL=your-email@gmail.com
SMTP_FROM_NAME=Super-Bot Alerts
```

**SMS Notifications (`.env`):**
```bash
TWILIO_ACCOUNT_SID=your_account_sid
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_FROM_NUMBER=+1234567890
```

**Note:** Price alerts work without email/SMS - notifications will be limited to WebSocket only.

---

## 🎮 Usage Examples

### Example 1: Bargain Hunter
```
Alert 1: Keywords="Laptop", Price=$500, Type=Under
Alert 2: Keywords="MacBook Pro", Price=$800, Type=Under
Alert 3: Keywords="Gaming PC", Price=$600, Type=Under
```
Get notified of all cheap electronics!

### Example 2: Classic Car Collector
```
Alert 1: Keywords="Corvette", Price=$25000, Type=Under
Alert 2: Keywords="Mustang", Price=$20000, Type=Under
Alert 3: Keywords="Camaro", Price=$18000, Type=Under
```
Monitor muscle car deals.

### Example 3: Reseller Strategy
```
Alert 1: Keywords="iPhone 15", Price=$1200, Type=Over
Alert 2: Keywords="PS5", Price=$600, Type=Over
```
Find overpriced items to flip or price-match.

---

## 🔒 Security Features

- **User Isolation:** Users can only view/manage their own alerts
- **Input Sanitization:** Keywords are sanitized to prevent injection
- **Rate Limiting:** All API endpoints are rate-limited
- **Authentication Required:** All endpoints require login
- **Activity Logging:** All alert actions are logged for audit trail

---

## 🐛 Troubleshooting

### Problem: Alerts Not Triggering

**Solutions:**
1. Verify scheduler is running: `python scripts/scheduler.py`
2. Check alert is "Active" (not paused)
3. Verify keywords match actual listings
4. Check if triggered within last hour (rate limit)
5. Review logs: `logs/app.log`
6. Test with very broad criteria first

### Problem: No Notifications Received

**Solutions:**
1. Check notification preferences in Settings
2. Verify email/SMS credentials in `.env`
3. Test notification system:
   ```python
   from notifications import test_email_configuration
   print(test_email_configuration())
   ```
4. Check spam folder for emails
5. Verify phone number format (+1234567890)

### Problem: "Error Loading Alerts" on Page

**Solutions:**
1. Check browser console (F12)
2. Verify you're logged in
3. Test API directly: `curl http://localhost:5000/api/price-alerts -b cookies.txt`
4. Check Flask logs for errors
5. Verify database has `price_alerts` table

### Problem: Alert Triggering Too Often

**Solutions:**
1. Rate limiting should prevent this (once per hour)
2. Check if multiple similar alerts exist
3. Verify `last_triggered` is updating correctly
4. Consider pausing alerts temporarily

---

## 📊 Best Practices

### Creating Effective Alerts

1. **Be Specific:** Use precise keywords ("iPhone 15 Pro" vs "phone")
2. **Realistic Prices:** Set thresholds you'd actually act on
3. **Start Broad:** Test with lenient criteria first, then refine
4. **Use Multiple Alerts:** Different keywords/prices for different scenarios
5. **Pause When Away:** Disable alerts when traveling or unavailable

### Managing Alerts

1. **Review Regularly:** Delete outdated or inactive alerts
2. **Adjust Thresholds:** Market prices change - update accordingly
3. **Monitor Performance:** Check "Last Triggered" to see what's working
4. **Pause vs Delete:** Pause seasonal searches instead of deleting
5. **Organize by Priority:** Keep most important alerts active

### Notification Management

1. **Enable Email Only:** Less intrusive than SMS for non-urgent items
2. **SMS for High-Value:** Reserve SMS for your most important alerts
3. **WebSocket Always On:** Free and instant, no reason to disable
4. **Check Notifications:** Review triggered alerts even if you don't act

---

## 🚀 Advanced Usage

### API Integration

You can integrate price alerts into your own scripts:

```python
import requests

# Login first to get session cookie
session = requests.Session()
session.post('http://localhost:5000/login', data={
    'username': 'myuser',
    'password': 'mypass'
})

# Create alert via API
response = session.post('http://localhost:5000/api/price-alerts', json={
    'keywords': 'Corvette',
    'threshold_price': 20000,
    'alert_type': 'under'
})

print(response.json())

# Get all alerts
alerts = session.get('http://localhost:5000/api/price-alerts').json()
print(f"You have {alerts['count']} alerts")
```

### Batch Alert Creation

Create multiple alerts programmatically:

```python
items = [
    {'keywords': 'Laptop', 'price': 500, 'type': 'under'},
    {'keywords': 'MacBook', 'price': 800, 'type': 'under'},
    {'keywords': 'Gaming PC', 'price': 1000, 'type': 'under'}
]

for item in items:
    session.post('http://localhost:5000/api/price-alerts', json={
        'keywords': item['keywords'],
        'threshold_price': item['price'],
        'alert_type': item['type']
    })
```

---

## 📈 Future Enhancements

Potential improvements for future versions:

- [ ] Edit existing alerts without deleting
- [ ] Alert templates (save/reuse configurations)
- [ ] Location-based alerts (city/region filtering)
- [ ] Complex conditions (price ranges, percentage changes)
- [ ] Alert history and statistics
- [ ] Bulk operations (pause/delete multiple)
- [ ] Alert groups/categories
- [ ] Custom notification schedules (quiet hours)
- [ ] Alert expiration dates
- [ ] AND/OR keyword logic

---

## 📞 Support

Need help?

1. **Documentation:** Check other guides in `/docs/features/`
2. **API Reference:** `/docs/API_DOCUMENTATION.md`
3. **Logs:** Review `logs/app.log` for errors
4. **Testing:** Run `QUICK_TEST_GUIDE.md` test procedures

---

**Last Updated:** October 12, 2025
**Feature Status:** ✅ Fully Implemented and Tested

