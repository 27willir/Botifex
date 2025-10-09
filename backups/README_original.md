# Super Bot

A web scraping automation bot for monitoring listings across multiple platforms (Facebook Marketplace, Craigslist, KSL).

## Project Structure

```
super-bot/
├── app.py                  # Main Flask application
├── requirements.txt        # Python dependencies
├── .gitignore             # Git ignore rules
│
├── Core Modules
├── db.py                  # Database operations
├── security.py            # Security configuration
├── error_handling.py      # Error handling utilities
├── error_recovery.py      # Error recovery system
├── utils.py              # Utility functions
├── scraper_thread.py     # Scraper threading management
│
├── docs/                  # Documentation
│   ├── ANALYTICS_FEATURES.md
│   ├── ANALYTICS_PAGE_FIXES.md
│   ├── ERROR_HANDLING_IMPROVEMENTS.md
│   ├── SCRAPER_THREADING_FIXES.md
│   └── SECURITY_IMPROVEMENTS.md
│
├── scripts/               # Utility scripts
│   ├── init_db.py        # Initialize database
│   ├── create_user.py    # Create user accounts
│   └── scheduler.py      # Scraper scheduler
│
├── tests/                 # Test files
│   ├── test_db_integration.py
│   ├── test_password.py
│   ├── test_scraper_fixes.py
│   └── test_scraper_stability.py
│
├── scrapers/              # Scraper modules
│   ├── craigslist.py
│   ├── facebook.py
│   └── ksl.py
│
├── templates/             # HTML templates
│   ├── index.html
│   ├── login.html
│   ├── register.html
│   ├── settings.html
│   └── analytics.html
│
├── static/                # Static assets (CSS, JS, images)
├── logs/                  # Application logs
└── superbot.db           # SQLite database

```

## Setup

1. **Create virtual environment:**
   ```bash
   python -m venv venv
   ```

2. **Activate virtual environment:**
   - Windows: `venv\Scripts\activate`
   - Linux/Mac: `source venv/bin/activate`

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Initialize database:**
   ```bash
   python scripts/init_db.py
   ```

5. **Create a user:**
   ```bash
   python scripts/create_user.py <username> <password> <email>
   ```

## Running the Application

```bash
python app.py
```

The application will be available at `http://localhost:5000`

## Running Tests

```bash
# Test database integration
python tests/test_db_integration.py

# Test scraper functionality
python tests/test_scraper_fixes.py

# Test scraper stability
python tests/test_scraper_stability.py

# Test password hashing
python tests/test_password.py
```

## Features

- **Multi-platform scraping**: Facebook Marketplace, Craigslist, KSL
- **User authentication**: Secure login system with password hashing
- **Real-time monitoring**: Automated scraping with configurable intervals
- **Analytics dashboard**: Comprehensive analytics and insights
- **Error recovery**: Automatic error detection and recovery
- **Thread management**: Efficient multi-threaded scraper execution

## Security

- CSRF protection enabled
- Secure session management
- Password hashing with Werkzeug
- Environment variable support for sensitive data

## License

Private project - All rights reserved

