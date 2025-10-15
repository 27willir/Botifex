# Super-Bot Architecture

Technical overview of Super-Bot's system architecture and design.

## 🏗️ System Overview

Super-Bot is a Flask-based web application that scrapes multiple marketplaces, manages subscriptions, and provides analytics.

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     User Interface                       │
│           (HTML Templates + JavaScript)                  │
└──────────────┬──────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────┐
│                    Flask Application                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐ │
│  │  Routes  │  │   Auth   │  │   API    │  │  Admin  │ │
│  └──────────┘  └──────────┘  └──────────┘  └─────────┘ │
└──────┬────────────┬─────────────┬─────────────┬─────────┘
       │            │             │             │
   ┌───▼───┐   ┌───▼───┐    ┌────▼────┐   ┌───▼────┐
   │  DB   │   │Stripe │    │Scrapers │   │ Cache  │
   │Module │   │Manager│    │ Thread  │   │Manager │
   └───────┘   └───────┘    └────┬────┘   └────────┘
                                  │
                    ┌─────────────┴──────────────┐
                    │                            │
            ┌───────▼────────┐      ┌───────────▼────────┐
            │  Web Scrapers  │      │  External APIs     │
            │  - Facebook    │      │  - Stripe API      │
            │  - Craigslist  │      │  - Twilio API      │
            │  - KSL         │      │  - Email Service   │
            │  - eBay        │      └────────────────────┘
            └────────────────┘
```

---

## 📦 Core Components

### 1. Flask Application (`app.py`)

**Responsibilities:**
- HTTP request handling
- Route management
- Session management
- Authentication
- Template rendering

**Key Features:**
- Flask-Login for authentication
- Flask-WTF for CSRF protection
- Flask-SocketIO for real-time updates
- Swagger documentation

### 2. Database Module (`db_enhanced.py`)

**Responsibilities:**
- Database operations
- Connection pooling
- Data access layer
- Query optimization

**Technologies:**
- SQLite (development)
- PostgreSQL (production)
- Connection pooling
- Parameterized queries

**Key Tables:**
```sql
users            -- User accounts
settings         -- User preferences
listings         -- Scraped listings
favorites        -- User favorites
saved_searches   -- Saved search queries
price_alerts     -- Price alert rules
subscriptions    -- Subscription data
user_activity    -- Activity logging
```

### 3. Scraper System (`scraper_thread.py`)

**Responsibilities:**
- Manage scraper threads
- Coordinate scraping operations
- Handle start/stop commands
- Resource cleanup

**Architecture:**
```
ScraperThread (Main)
├── FacebookScraper (Thread)
├── CraigslistScraper (Thread)
├── KSLScraper (Thread)
└── eBayScraper (Thread)
```

**Features:**
- Thread-safe operations
- Graceful shutdown
- Error recovery
- Resource management

### 4. Individual Scrapers

**Facebook Scraper** (`scrapers/facebook.py`)
- Selenium-based (requires Chrome)
- Handles dynamic content
- Image extraction
- Price parsing

**Craigslist Scraper** (`scrapers/craigslist.py`)
- Requests + BeautifulSoup
- Fast and efficient
- Multiple XPath fallbacks
- Retry logic

**KSL Scraper** (`scrapers/ksl.py`)
- Requests + lxml
- Regional focus
- Image support
- Error handling

**eBay Scraper** (`scrapers/ebay.py`)
- Requests + BeautifulSoup
- Auction support
- Buy It Now support
- Price range filtering

### 5. Subscription System (`subscriptions.py`)

**Responsibilities:**
- Tier management
- Feature enforcement
- Stripe integration
- Webhook handling

**Tier Configuration:**
```python
SUBSCRIPTION_TIERS = {
    'free': {...},
    'standard': {...},
    'pro': {...}
}
```

**Features:**
- Stripe Checkout
- Customer Portal
- Webhook processing
- Subscription lifecycle

### 6. Security Module (`security.py`)

**Responsibilities:**
- Password hashing
- Input validation
- Session security
- CSRF protection

**Features:**
- PBKDF2-SHA256 hashing
- Input sanitization
- Email validation
- Username validation
- Security headers

### 7. Error Handling (`error_handling.py`, `error_recovery.py`)

**Responsibilities:**
- Exception handling
- Error logging
- Automatic recovery
- Health monitoring

**Features:**
- Custom error classes
- @log_errors decorator
- Database error handling
- Network error handling
- Automatic scraper restart

---

## 🔄 Data Flow

### User Registration Flow

```
1. User submits form → 2. Validate input → 3. Hash password
                ↓
4. Create DB record → 5. Send verification email → 6. Redirect to login
```

### Listing Scraping Flow

```
1. Scraper starts → 2. Load user settings → 3. Build search URL
            ↓
4. Fetch page → 5. Parse HTML → 6. Extract listings
            ↓
7. Filter by price → 8. Check if new → 9. Save to database
            ↓
10. Send notifications → 11. Update cache → 12. Wait for interval
```

### Subscription Flow

```
1. User clicks upgrade → 2. Create Stripe session → 3. Redirect to Stripe
                ↓
4. User pays → 5. Stripe webhook → 6. Verify signature
                ↓
7. Update subscription → 8. Log event → 9. Show confirmation
```

---

## 🗄️ Database Schema

### Core Tables

**users**
```sql
CREATE TABLE users (
    username TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    verified INTEGER DEFAULT 0,
    role TEXT DEFAULT 'user',
    active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP,
    login_count INTEGER DEFAULT 0
);
```

**listings**
```sql
CREATE TABLE listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    price INTEGER,
    link TEXT UNIQUE NOT NULL,
    image_url TEXT,
    source TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    user_id TEXT,
    FOREIGN KEY (user_id) REFERENCES users(username)
);
```

**subscriptions**
```sql
CREATE TABLE subscriptions (
    username TEXT PRIMARY KEY,
    tier TEXT DEFAULT 'free',
    status TEXT DEFAULT 'active',
    stripe_customer_id TEXT,
    stripe_subscription_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (username) REFERENCES users(username)
);
```

### Indexes

```sql
CREATE INDEX idx_listings_user ON listings(user_id);
CREATE INDEX idx_listings_source ON listings(source);
CREATE INDEX idx_listings_created ON listings(created_at);
CREATE INDEX idx_favorites_user ON favorites(username);
CREATE INDEX idx_activity_user ON user_activity(username);
```

---

## 🔐 Security Architecture

### Authentication Flow

```
1. User enters credentials
2. Hash password with PBKDF2-SHA256
3. Compare with stored hash
4. Create secure session
5. Set HTTPOnly cookies
6. Log activity
```

### Authorization Layers

**Route Protection:**
```python
@login_required  # Flask-Login
@require_subscription_tier('pro')  # Custom
@require_feature('analytics')  # Custom
```

**Database Protection:**
- All queries use parameters
- Whitelisted dynamic SQL
- Connection pooling
- Prepared statements

**API Protection:**
- CSRF tokens
- Rate limiting
- Input validation
- Session verification

---

## ⚡ Performance Optimizations

### Caching Strategy

**What We Cache:**
- User objects (5 min)
- Settings (5 min)
- Listings (2 min)
- Subscription data (10 min)

**Cache Implementation:**
```python
# Simple in-memory cache
cache = {}

def cache_get(key):
    if key in cache:
        value, expiry = cache[key]
        if time.time() < expiry:
            return value
    return None
```

### Database Optimization

**Connection Pooling:**
```python
pool = Queue(maxsize=10)
# Reuse connections
# Reduce overhead
```

**Query Optimization:**
- Indexed columns
- Limit result sets
- Pagination support
- Batch operations

### Thread Management

**Daemon Threads:**
- Don't block shutdown
- Auto-cleanup on exit
- Graceful termination

**Resource Cleanup:**
```python
try:
    # Scraping logic
finally:
    driver.quit()  # Always cleanup
```

---

## 🔌 External Integrations

### Stripe

**Integration Points:**
- Checkout Sessions
- Customer Portal
- Webhooks
- Subscription Management

**Security:**
- Signature verification
- Idempotency keys
- Secure API keys
- Test/Live modes

### Email Service

**Supported Providers:**
- SMTP (any provider)
- SendGrid
- Mailgun
- AWS SES

**Use Cases:**
- Email verification
- Password reset
- Notifications
- Receipts

### SMS (Twilio)

**Features:**
- Price drop alerts
- New listing notifications
- Account alerts
- 2FA (future)

---

## 🧵 Threading Model

### Main Thread
- Flask application
- HTTP requests
- WebSocket connections

### Scraper Threads (Daemon)
- Facebook scraper
- Craigslist scraper
- KSL scraper
- eBay scraper

### Background Workers (Future)
- Email queue
- SMS queue
- Analytics processing
- Report generation

**Thread Safety:**
```python
_threads_lock = threading.Lock()
_seen_listings_lock = threading.Lock()

with _threads_lock:
    # Thread-safe operation
```

---

## 📊 Monitoring & Logging

### Logging Levels

```python
DEBUG - Detailed information
INFO - General information
WARNING - Warning messages
ERROR - Error messages
CRITICAL - Critical errors
```

### Log Locations

- `logs/superbot.log` - Application logs
- `logs/scraper.log` - Scraper logs
- `logs/stripe.log` - Payment logs

### Metrics to Monitor

- Requests per minute
- Error rate
- Scraper uptime
- Database connections
- Cache hit rate
- Response times

---

## 🚀 Scalability

### Current Capacity

- **Users**: 100-1000
- **Requests**: 1000/min
- **Listings**: 100K+
- **Scrapers**: 4 concurrent

### Scaling Strategies

**Vertical Scaling:**
- Increase server resources
- More CPU/RAM
- Faster disk I/O

**Horizontal Scaling:**
- Multiple app instances
- Load balancer
- Redis for shared cache
- PostgreSQL replication

**Database Scaling:**
- Read replicas
- Sharding by user
- Archival strategy
- Index optimization

---

## 🔧 Configuration

### Environment Variables

```bash
# Application
SECRET_KEY=...
FLASK_ENV=production
DEBUG=False

# Database
DATABASE_URL=postgresql://...

# Stripe
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...

# Features
FEATURE_ANALYTICS=True
FEATURE_SELLING=True
```

### Feature Flags

```python
if os.getenv('FEATURE_ANALYTICS') == 'True':
    enable_analytics()
```

---

## 📚 Technology Stack

### Backend
- **Framework**: Flask 3.1.2
- **Auth**: Flask-Login 0.6.3
- **CSRF**: Flask-WTF 1.2.1
- **WebSockets**: Flask-SocketIO 5.3.6
- **Database**: SQLite/PostgreSQL
- **ORM**: None (raw SQL)

### Scraping
- **Browser**: Selenium 4.35.0
- **Parser**: BeautifulSoup4, lxml
- **Requests**: requests 2.32.5
- **Driver**: ChromeDriver (auto)

### Payments
- **Gateway**: Stripe 11.1.1

### Production
- **Server**: Gunicorn 21.2.0
- **Workers**: Eventlet 0.35.2
- **Python**: 3.11+

---

## 🏗️ Design Patterns

### Used Patterns

**Singleton** - Database connection pool  
**Factory** - Scraper creation  
**Decorator** - @log_errors, @login_required  
**Strategy** - Different scraping strategies  
**Observer** - WebSocket notifications  

---

## 📖 API Design

RESTful endpoints:

```
GET /api/status - System status
GET /api/listings - Get listings
GET /api/favorites - Get favorites
POST /api/favorites/<id> - Add favorite
DELETE /api/favorites/<id> - Remove favorite
GET /api/analytics/* - Analytics data
```

See [API Reference](api-reference.md) for complete documentation.

---

## 🔮 Future Architecture

### Planned Improvements

**Microservices:**
- Separate scraper service
- Separate analytics service
- API gateway

**Message Queue:**
- RabbitMQ or Redis
- Async task processing
- Job scheduling

**Containerization:**
- Docker containers
- Kubernetes orchestration
- Auto-scaling

**CDN:**
- Static asset delivery
- Image optimization
- Global distribution

---

**Want to contribute?** See [Contributing Guide](contributing.md)

