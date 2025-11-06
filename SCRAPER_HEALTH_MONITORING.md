# Scraper Health Monitoring Feature

## Overview

Added comprehensive scraper health monitoring to the admin panel, allowing administrators to monitor the performance, reliability, and activity of all scrapers in real-time.

## ✨ Features Added

### 1. Admin Dashboard Routes

**New Routes:**
- `GET /admin/scrapers` - Main scraper health monitoring page
- `GET /admin/api/scraper-health` - JSON API for all scraper health data
- `GET /admin/api/scraper-details/<scraper_name>` - Detailed metrics for specific scraper

### 2. Visual Scraper Health Dashboard

**Features:**
- **Real-time Status Indicators**: Color-coded status badges for each scraper
  - 🟢 **Excellent** - Success rate ≥ 95%
  - 🔵 **Good** - Success rate ≥ 80%
  - 🟠 **Degraded** - Success rate ≥ 50%
  - 🔴 **Poor** - Success rate < 50%
  - ⚪ **Unknown** - No data available

- **Overall Statistics (24h)**:
  - Total active scrapers
  - Total scraping runs
  - Total listings found
  - Average success rate across all scrapers

- **Per-Scraper Metrics (24h)**:
  - Success rate percentage
  - Total runs executed
  - Total listings found
  - Average scraping duration
  - Successful vs. failed runs
  - Last run timestamp

### 3. Integration with Metrics System

The feature integrates seamlessly with the existing `scrapers/metrics.py` module:
- Uses `get_metrics_summary()` for performance data
- Uses `get_performance_status()` for health status
- Uses `get_recent_runs()` for historical data
- Automatic fallback if metrics module unavailable

### 4. Auto-Refresh Capability

- **Manual Refresh**: Button to refresh data on demand
- **Auto-Refresh**: Automatically refreshes every 30 seconds
- **Real-time Updates**: Always shows current scraper status

### 5. WebDriver & Anti-Bot Diagnostics *(2025-11 update)*

- **Chrome Readiness Snapshot**: `/api/scraper-health` and `/admin/api/scraper-health` now embed a `webdriver` payload detailing detected Chrome/Chromium binaries, chromedriver availability, and the active environment overrides. Failing checks are surfaced as `status: "warning"` so operators can preemptively fix missing binaries.
- **Rate-Limit Resilience**: Shared request helper consolidates session resets, randomized fingerprints, and exponential backoff for 403/429 responses. Mercari and KSL scrapers automatically rotate cookies and fingerprints after bot-detection events.
- **Selector Fallbacks**: Craigslist and eBay scrapers parse JSON-LD search payloads whenever legacy HTML selectors fail, greatly reducing “no posts/items found” false-positives after UI updates.

## 📊 Metrics Tracked

### Performance Metrics
1. **Success Rate** - Percentage of successful scraping attempts
2. **Total Runs** - Number of scraping cycles executed
3. **Listings Found** - Total listings discovered
4. **Average Duration** - Average time per scraping cycle
5. **Successful/Failed Runs** - Breakdown of run outcomes

### Time Periods
- **Last 24 hours** - Primary view
- **Last 1 hour** - Available via API
- **Recent runs** - Last 20 runs per scraper (via API)

## 🎨 User Interface

### Card-Based Layout
Each scraper has a visually distinct card showing:
- Scraper name with icon
- Color-coded status badge
- Key metrics in a grid layout
- Success rate with color coding
- Last run timestamp

### Color Scheme
- **Excellent**: Green gradient (#00ff88 → #00cc6a)
- **Good**: Blue gradient (#00bfff → #007bff)
- **Degraded**: Orange gradient (#ffaa00 → #ff8800)
- **Poor**: Red gradient (#ff4444 → #cc0000)
- **Unknown**: Gray with transparency

### Navigation
- Added to admin sidebar as "Scraper Health"
- Icon: Robot (fas fa-robot)
- Positioned prominently in admin section

## 🔧 Technical Implementation

### Backend (admin_panel.py)

```python
# Import metrics functions
from scrapers.metrics import get_metrics_summary, get_performance_status, get_recent_runs

# Main route
@admin_bp.route('/scrapers')
@login_required
@admin_required
def scrapers_health():
    # Get metrics for all scrapers
    # Returns health data for display
    
# API endpoint for JSON data
@admin_bp.route('/api/scraper-health')
@login_required
@admin_required
def api_scraper_health():
    # Returns JSON with all scraper health data
    
# API endpoint for detailed scraper info
@admin_bp.route('/api/scraper-details/<scraper_name>')
@login_required
@admin_required
def api_scraper_details(scraper_name):
    # Returns detailed metrics for specific scraper
```

### Frontend (scrapers.html)

- **Responsive Grid Layout**: Adapts to screen size
- **Modern Design**: Glassmorphism with gradient effects
- **Interactive Elements**: Hover effects and animations
- **JavaScript Features**: 
  - Auto-calculation of overall stats
  - Auto-refresh every 30 seconds
  - Manual refresh button

### Graceful Degradation

- Falls back gracefully if metrics module unavailable
- Shows "No data available" for scrapers without metrics
- Error handling for individual scraper failures
- Doesn't crash if one scraper has issues

## 📡 API Endpoints

### GET /admin/api/scraper-health

Returns health data for all scrapers:

```json
{
  "craigslist": {
    "status": "excellent",
    "total_runs": 142,
    "success_rate": 98.5,
    "total_listings": 234,
    "avg_duration": 3.42,
    "last_run": {
      "timestamp": "2025-11-02 14:23:15",
      "listings_found": 5,
      "success": true
    }
  },
  "ebay": { /* ... */ },
  // ... other scrapers
}
```

### GET /admin/api/scraper-details/craigslist

Returns detailed metrics for a specific scraper:

```json
{
  "scraper": "craigslist",
  "status": "excellent",
  "metrics_24h": {
    "total_runs": 142,
    "successful_runs": 140,
    "failed_runs": 2,
    "success_rate": 98.5,
    "total_listings": 234,
    "avg_listings_per_run": 1.65,
    "avg_duration": 3.42
  },
  "metrics_1h": {
    "total_runs": 6,
    "success_rate": 100.0,
    // ... 
  },
  "recent_runs": [
    {
      "timestamp": "2025-11-02 14:23:15",
      "duration": 3.2,
      "listings_found": 5,
      "success": true
    },
    // ... last 20 runs
  ]
}
```

## 🚀 Usage

### For Administrators

1. **Access the Dashboard**:
   ```
   Navigate to: /admin/scrapers
   ```

2. **Monitor Scraper Health**:
   - View overall statistics at the top
   - Check individual scraper cards for detailed metrics
   - Look for color-coded status badges

3. **Identify Issues**:
   - Red/Orange badges indicate problems
   - Low success rates need investigation
   - Failed runs show in the breakdown

4. **Use API for Automation**:
   ```bash
   # Get all scraper health
   curl -X GET https://your-domain.com/admin/api/scraper-health \
     -H "Cookie: session=your-session-cookie"
   
   # Get specific scraper details
   curl -X GET https://your-domain.com/admin/api/scraper-details/craigslist \
     -H "Cookie: session=your-session-cookie"
   ```

### For Monitoring Tools

The JSON API endpoints can be integrated with:
- **Monitoring Systems**: Datadog, New Relic, Prometheus
- **Alerting Tools**: PagerDuty, Opsgenie
- **Status Pages**: Statuspage.io, Atlassian Statuspage
- **Custom Dashboards**: Grafana, Kibana

## 🎯 Benefits

### Operational Visibility
- **Instant Overview**: See all scrapers at a glance
- **Trend Identification**: Spot degrading performance early
- **Proactive Monitoring**: Catch issues before they impact users

### Performance Tracking
- **Success Rates**: Track reliability over time
- **Volume Metrics**: Monitor listing discovery rates
- **Performance Metrics**: Identify slow scrapers

### Troubleshooting
- **Quick Diagnosis**: Identify failing scrapers instantly
- **Historical Data**: Review recent run history
- **Error Patterns**: Spot recurring issues

### Resource Planning
- **Load Distribution**: See which scrapers are busiest
- **Capacity Planning**: Identify when to scale
- **Cost Optimization**: Optimize scraping frequency

## 📈 Performance Metrics Integration

The feature uses the optimized metrics system from `scrapers/metrics.py`:

- **In-Memory Storage**: Fast access to recent data
- **Deque-based History**: Efficient FIFO for recent runs (max 100)
- **Thread-Safe**: Concurrent access protected with locks
- **Automatic Cleanup**: Old data automatically removed

### Metrics Collection

Each scraper run automatically records:
```python
with ScraperMetrics(SITE_NAME) as metrics:
    # Scraping logic here
    metrics.listings_found = len(results)
    metrics.success = True
```

This data is then available in the admin panel!

## 🔒 Security

- **Admin-Only Access**: Requires `@admin_required` decorator
- **Session Validation**: Checks user authentication
- **Role Verification**: Validates admin role from database
- **No Sensitive Data**: Only performance metrics exposed

## 🛠️ Maintenance

### Adding New Scrapers

To add a new scraper to the health monitor:

1. **Name must be added to the list** in `scrapers_health()`:
   ```python
   scrapers = ['craigslist', 'ebay', 'facebook', 'ksl', 'mercari', 'poshmark', 'new_scraper']
   ```

2. **Scraper must use metrics tracking**:
   ```python
   from scrapers.metrics import ScraperMetrics
   
   def check_new_scraper():
       with ScraperMetrics('new_scraper') as metrics:
           # ... scraping logic ...
           metrics.listings_found = len(results)
           metrics.success = True
   ```

That's it! The new scraper will automatically appear in the dashboard.

### Customizing Display

To customize the appearance:
- Edit `templates/admin/scrapers.html`
- Modify styles in the `{% block extra_styles %}` section
- Adjust grid layout in `.scrapers-grid` CSS class

## 📝 Future Enhancements

Potential improvements:

1. **Historical Charts**: Graph performance over time
2. **Alerting**: Email/SMS alerts for failing scrapers
3. **Detailed Logs**: Click-through to view scraper logs
4. **Manual Controls**: Start/stop scrapers from dashboard
5. **Performance Trends**: Show 7-day/30-day trends
6. **Export Data**: Download metrics as CSV/JSON
7. **Comparison View**: Compare scrapers side-by-side
8. **Mobile App**: Push notifications for health changes

## ✅ Testing

To test the feature:

1. **Start some scrapers** to generate metrics
2. **Navigate to** `/admin/scrapers`
3. **Verify** all scrapers appear with current data
4. **Test refresh** button functionality
5. **Check API endpoints** return valid JSON
6. **Test with no data** - ensure graceful handling

## 📚 Related Files

- `admin_panel.py` - Backend routes and API endpoints
- `templates/admin/scrapers.html` - Frontend template
- `templates/admin/_base_admin.html` - Navigation menu
- `scrapers/metrics.py` - Metrics collection system
- `scrapers/common.py` - Shared scraper utilities

## 🎉 Summary

The scraper health monitoring feature provides administrators with:
- ✅ Real-time visibility into scraper performance
- ✅ Beautiful, intuitive visual dashboard
- ✅ JSON API for external integrations
- ✅ Auto-refresh for up-to-date information
- ✅ Detailed metrics for troubleshooting
- ✅ Seamless integration with existing code

No additional dependencies required - uses only built-in Python modules and existing infrastructure!

