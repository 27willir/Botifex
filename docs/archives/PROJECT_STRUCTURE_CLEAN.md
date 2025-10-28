# 📁 Super-Bot - Clean Project Structure

**Last Updated:** December 2024  
**Status:** ✅ Clean and Organized

---

## 🎯 Project Overview

Super-Bot is an intelligent marketplace scraper that searches multiple platforms (Facebook Marketplace, Craigslist, KSL, eBay, Mercari, Poshmark) for items you want to buy.

---

## 📂 Directory Structure

```
super-bot/
│
├── 📄 Core Application Files
│   ├── app.py                          # Main Flask application
│   ├── db_enhanced.py                  # Enhanced database module
│   ├── db.py                           # Legacy database module
│   ├── utils.py                        # Utility functions
│   ├── security.py                     # Security utilities
│   ├── cache_manager.py                # Caching system
│   ├── rate_limiter.py                 # Rate limiting
│   ├── error_handling.py               # Error handling
│   ├── error_recovery.py               # Error recovery
│   ├── location_utils.py               # Location utilities
│   └── websocket_manager.py            # WebSocket manager
│
├── 🔐 Authentication & Security
│   ├── email_verification.py           # Email verification
│   ├── notifications.py                # Notification system
│   └── subscription_middleware.py      # Subscription middleware
│
├── 💳 Payment & Subscriptions
│   ├── subscriptions.py                # Subscription management
│   └── activate_subscription.py        # Subscription activation
│
├── 🤖 Scrapers
│   └── scrapers/
│       ├── facebook.py                 # Facebook Marketplace scraper
│       ├── craigslist.py               # Craigslist scraper
│       ├── ksl.py                      # KSL Classifieds scraper
│       ├── ebay.py                     # eBay scraper
│       ├── mercari.py                  # Mercari scraper
│       └── poshmark.py                 # Poshmark scraper
│
├── 🔧 Scripts
│   └── scripts/
│       ├── init_db.py                  # Initialize database
│       ├── create_admin.py             # Create admin user
│       ├── create_user.py              # Create regular user
│       ├── migrate_to_enhanced_db.py   # Database migration
│       ├── backup_database.py          # Database backup
│       ├── schedule_backups.py         # Schedule backups
│       ├── price_alert_worker.py       # Price alert worker
│       ├── saved_search_worker.py      # Saved search worker
│       ├── scheduler.py                # Task scheduler
│       └── verify_admin.py             # Verify admin
│
├── 🎨 Frontend
│   ├── templates/                      # HTML templates
│   │   ├── base.html                   # Base template
│   │   ├── index.html                  # Dashboard
│   │   ├── landing.html                # Landing page
│   │   ├── login.html                  # Login page
│   │   ├── register.html               # Registration page
│   │   ├── profile.html                # User profile
│   │   ├── settings.html               # Settings
│   │   ├── alerts.html                 # Price alerts
│   │   ├── favorites.html              # Favorites
│   │   ├── analytics.html              # Analytics
│   │   ├── selling.html                # Selling page
│   │   ├── subscription.html           # Subscription page
│   │   ├── subscription_plans.html     # Subscription plans
│   │   ├── terms.html                  # Terms of service
│   │   ├── forgot_password.html        # Password recovery
│   │   └── reset_password.html         # Reset password
│   │   └── admin/                      # Admin templates
│   │       ├── dashboard.html
│   │       ├── users.html
│   │       ├── listings.html
│   │       ├── settings.html
│   │       └── analytics.html
│   │
│   └── static/                         # Static files
│       ├── images/                     # Images
│       └── js/                         # JavaScript files
│
├── 📚 Documentation
│   └── docs/
│       ├── README.md                   # Documentation index
│       ├── PROJECT_STRUCTURE.md        # Project structure
│       ├── API_DOCUMENTATION.md        # API reference
│       │
│       ├── user/                       # User documentation
│       │   ├── features.md
│       │   └── getting-started.md
│       │
│       ├── guides/                     # Setup guides
│       │   ├── QUICK_START.md
│       │   ├── SCALABILITY_GUIDE.md
│       │   └── SETUP_INSTRUCTIONS.md
│       │
│       ├── features/                   # Feature docs
│       │   ├── SUBSCRIPTION_IMPLEMENTATION.md
│       │   ├── NOTIFICATION_FEATURE.md
│       │   ├── ANALYTICS_FEATURES.md
│       │   ├── PRICE_ALERTS_GUIDE.md
│       │   ├── WEBSOCKET_INTEGRATION.md
│       │   ├── BACKUP_USAGE.md
│       │   ├── SELLING_FEATURE.md
│       │   ├── TERMS_OF_SERVICE.md
│       │   ├── LANDING_PAGE.md
│       │   ├── FEATURES_IMPLEMENTED.md
│       │   ├── EBAY_INTEGRATION.md
│       │   ├── FACEBOOK_DYNAMIC_RADIUS.md
│       │   ├── ADMIN_SUBSCRIPTION_BYPASS.md
│       │   ├── SUBSCRIPTION_SETUP.md
│       │   ├── SUBSCRIPTION_QUICKSTART.md
│       │   └── NOTIFICATION_SETUP.md
│       │
│       ├── deployment/                 # Deployment guides
│       │   ├── README.md
│       │   └── stripe-setup.md
│       │
│       └── development/                # Developer docs
│           ├── architecture.md
│           ├── ERROR_HANDLING_IMPROVEMENTS.md
│           ├── SCRAPER_THREADING_FIXES.md
│           └── SECURITY_IMPROVEMENTS.md
│
├── 🧪 Tests
│   └── tests/
│       ├── test_db_integration.py
│       ├── test_password.py
│       ├── test_scraper_fixes.py
│       └── test_scraper_stability.py
│
├── ⚙️ Configuration
│   ├── requirements.txt                # Python dependencies
│   ├── runtime.txt                     # Python runtime version
│   ├── Procfile                        # Heroku Procfile
│   ├── gunicorn_config.py              # Gunicorn config
│   ├── swagger_config.py               # Swagger/OpenAPI config
│   ├── env.production.template         # Production env template
│   ├── setup_env.py                    # Environment setup
│   ├── .env                            # Environment variables (gitignored)
│   ├── .gitignore                      # Git ignore rules
│   └── .cursorignore                   # Cursor ignore rules
│
├── 📊 Admin
│   ├── admin_panel.py                  # Admin panel
│   └── scraper_thread.py               # Scraper thread manager
│
├── 📝 Documentation
│   ├── README.md                       # Main README
│   ├── CLEANUP_SUMMARY.md              # Cleanup summary
│   └── PROJECT_STRUCTURE_CLEAN.md      # This file
│
└── 🗄️ Data
    └── superbot.db                     # SQLite database (gitignored)
```

---

## 📊 Statistics

- **Total Python Files:** ~30 core files
- **Total Documentation Files:** ~30 files
- **Total HTML Templates:** ~20 templates
- **Total Scrapers:** 6 marketplace scrapers
- **Total Scripts:** 10 utility scripts
- **Total Tests:** 4 test files

---

## 🎯 Key Features

### 🔍 Multi-Platform Search
- Facebook Marketplace
- Craigslist
- KSL Classifieds
- eBay
- Mercari
- Poshmark

### 💰 Subscription Tiers
- **Free:** 2 keywords, 10-min refresh
- **Standard ($9.99/mo):** 10 keywords, 5-min refresh
- **Pro ($39.99/mo):** Unlimited keywords, 60-sec refresh

### 🚀 Advanced Features
- Real-time notifications (Email & SMS)
- Price alerts
- Favorites/Bookmarks
- Saved searches
- Analytics dashboard
- User profiles
- Admin panel
- WebSocket support

---

## 🚀 Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Initialize database
python scripts/init_db.py

# Create admin user
python scripts/create_admin.py

# Run application
python app.py
```

Visit: `http://localhost:5000`

---

## 📖 Documentation

- **User Guide:** `docs/user/getting-started.md`
- **Quick Start:** `docs/guides/QUICK_START.md`
- **API Docs:** `docs/API_DOCUMENTATION.md`
- **Architecture:** `docs/development/architecture.md`

---

## 🔒 Security Features

- Password hashing (bcrypt)
- CSRF protection
- Rate limiting
- SQL injection prevention
- XSS protection
- Secure session management
- Email verification
- Password reset functionality

---

## 🎨 Technology Stack

- **Backend:** Python, Flask
- **Database:** SQLite (production-ready)
- **Frontend:** HTML, CSS, JavaScript
- **Scraping:** Selenium, BeautifulSoup
- **Payments:** Stripe
- **Notifications:** Email (SMTP), SMS (Twilio)
- **WebSockets:** Flask-SocketIO
- **API Docs:** Swagger/OpenAPI

---

## 📈 Performance

- **Connection Pooling:** 10 concurrent connections
- **Thread-Safe Operations:** All database operations
- **WAL Mode:** Zero-lock concurrency
- **Caching:** Redis-style caching
- **Rate Limiting:** Per-user and per-endpoint
- **Scalability:** 1,000+ concurrent users

---

## 🧪 Testing

```bash
# Run all tests
python -m pytest tests/

# Run specific test
python -m pytest tests/test_db_integration.py
```

---

## 📝 License

MIT License - See LICENSE file for details

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

---

## 📧 Support

- **Email:** support@example.com
- **Issues:** GitHub Issues
- **Documentation:** `docs/README.md`

---

**Built with ❤️ for finding the best deals!**

