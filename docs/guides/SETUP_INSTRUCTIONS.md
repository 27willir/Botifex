# Setup Instructions for Enhanced Super Bot
## Quick Start Guide for 1,000+ Users

---

## 🚀 Quick Setup (5 Minutes)

### Step 1: Backup & Migrate Database

```bash
# Run the migration script
python scripts/migrate_to_enhanced_db.py
```

This will:
- ✅ Backup your existing database
- ✅ Add new tables and columns
- ✅ Create performance indexes
- ✅ Enable WAL mode for concurrency

### Step 2: Switch to Enhanced Version

**Option A: Replace Current Version (Recommended)**
```bash
# Backup current files
mv app.py app_original.py
mv db.py db_original.py

# Use enhanced versions
cp app_enhanced.py app.py
cp db_enhanced.py db.py
```

**Option B: Test Enhanced Version First**
```bash
# Run on different terminal
python app_enhanced.py
```

### Step 3: Create Admin User

```bash
# Using Python directly
python -c "import db_enhanced; db_enhanced.init_db(); db_enhanced.update_user_role('your_username', 'admin')"
```

Or if you need to create a new admin user:
```bash
# First, register through the website
# Then promote to admin:
python scripts/create_admin.py your_username
```

### Step 4: Start the Application

```bash
python app.py
```

Visit: `http://localhost:5000`

---

## 📋 Features Overview

### For Regular Users:
- 🔐 Secure login with password requirements
- ⚙️ Personal settings (isolated from other users)
- 🤖 Control scrapers (Facebook, Craigslist, KSL)
- 📊 View analytics
- 🔒 Rate limiting protection

### For Admin Users:
- 👥 User management
- 📈 System monitoring
- 📊 Activity logs
- 💾 Cache management
- 🛡️ Rate limit controls
- 🔧 User role management

---

## 🔑 Creating Your First Admin

### Method 1: Using Migration Script
Create `scripts/create_admin.py`:
```python
#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db_enhanced
from security import SecurityConfig

def create_admin(username, email, password):
    # Hash password
    hashed = SecurityConfig.hash_password(password)
    # Create user with admin role
    success = db_enhanced.create_user_db(username, email, hashed, role='admin')
    if success:
        print(f"✅ Admin user '{username}' created successfully!")
        return True
    else:
        print(f"❌ Failed to create admin user")
        return False

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python create_admin.py <username> <email> <password>")
        print("Example: python create_admin.py admin admin@example.com SecurePass123!")
        sys.exit(1)
    
    username = sys.argv[1]
    email = sys.argv[2]
    password = sys.argv[3]
    
    create_admin(username, email, password)
```

Then run:
```bash
python scripts/create_admin.py admin admin@example.com YourSecurePassword123!
```

### Method 2: Promote Existing User
```python
python -c "import db_enhanced; db_enhanced.update_user_role('existing_user', 'admin')"
```

---

## 🔒 Security Configuration

### Create `.env` File

Create a file named `.env` in the root directory:

```env
# Secret Key (CHANGE THIS!)
SECRET_KEY=your-super-secret-key-change-this-to-random-string

# Session Security
SESSION_COOKIE_SECURE=False
SESSION_COOKIE_HTTPONLY=True
SESSION_COOKIE_SAMESITE=Lax
PERMANENT_SESSION_LIFETIME=3600

# Password Requirements
MIN_PASSWORD_LENGTH=8
REQUIRE_SPECIAL_CHARS=True
REQUIRE_NUMBERS=True
REQUIRE_UPPERCASE=True
```

**⚠️ IMPORTANT**: Change the `SECRET_KEY` to a random string!

Generate a secure key:
```python
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

---

## 📊 Admin Dashboard Access

### Access the Dashboard
1. Log in as an admin user
2. Navigate to: `http://localhost:5000/admin`

### Dashboard Features:

#### Main Dashboard (`/admin`)
- Total users count
- Active users count
- Total listings
- Admin users count
- Cache statistics
- Recent users list
- Recent activity log

#### User Management (`/admin/users`)
- View all users
- Search users
- View user details
- Update user roles
- Deactivate users
- Reset rate limits

#### User Details (`/admin/user/<username>`)
- User information
- User settings
- Activity history
- Admin actions (change role, deactivate, reset rate limits)

#### Activity Log (`/admin/activity`)
- System-wide activity
- User actions
- Login/logout events
- Settings changes
- Scraper operations

#### Cache Management (`/admin/cache`)
- Cache statistics
- Clear all cache
- Cleanup expired entries

---

## 🎯 Testing the Setup

### Test 1: User Registration & Login
```bash
# 1. Open browser: http://localhost:5000/register
# 2. Create a test user
# 3. Login with test user
# 4. Verify settings work
```

### Test 2: Admin Access
```bash
# 1. Login as admin user
# 2. Navigate to /admin
# 3. Check user management
# 4. View activity logs
```

### Test 3: Rate Limiting
```bash
# Try logging in with wrong password 6 times
# Should get rate limited after 5 attempts
```

### Test 4: Cache Performance
```python
# Check cache statistics
curl http://localhost:5000/admin/api/stats
```

---

## 🔧 Configuration Options

### Database Connection Pool
Edit `db_enhanced.py`:
```python
POOL_SIZE = 10  # Increase for more concurrent users (default: 10)
CONNECTION_TIMEOUT = 30  # Timeout in seconds (default: 30)
```

### Rate Limits
Edit `rate_limiter.py`:
```python
RATE_LIMITS = {
    'api': 60,           # API requests per minute
    'scraper': 10,       # Scraper operations per minute
    'settings': 30,      # Settings updates per minute
    'login': 5,          # Login attempts per 5 minutes
    'register': 3,       # Registrations per hour
}
```

### Cache TTL
Edit `cache_manager.py`:
```python
self.default_ttl = 300  # Default cache lifetime in seconds (5 minutes)
```

---

## 📈 Monitoring & Maintenance

### Daily Tasks
```bash
# Check application logs
tail -f logs/superbot.log

# Check for errors
grep "ERROR" logs/superbot.log

# Check rate limit violations
grep "Rate limit exceeded" logs/superbot.log
```

### Weekly Tasks
```bash
# Backup database
cp superbot.db backups/superbot_$(date +%Y%m%d).db

# Clean up old logs (optional)
find logs/ -name "*.log" -mtime +30 -delete
```

### Monthly Tasks
```bash
# Review user activity
# Check for inactive users
# Review rate limit violations
# Check cache hit rate
```

---

## 🐛 Troubleshooting

### Issue: "Cannot import db_enhanced"
**Solution**: Make sure you renamed the file:
```bash
cp db_enhanced.py db.py
# or update imports in app.py
```

### Issue: "No module named 'admin_panel'"
**Solution**: Make sure `admin_panel.py` exists in the root directory.

### Issue: "Database is locked"
**Solution**: The enhanced version should prevent this. If it still happens:
1. Make sure WAL mode is enabled
2. Increase `POOL_SIZE` in `db_enhanced.py`
3. Check for long-running queries

### Issue: "Rate limit exceeded"
**Solution**: 
1. Admin can reset via dashboard: `/admin/user/<username>`
2. Or via Python: `db_enhanced.reset_rate_limit('username')`

### Issue: Admin dashboard not accessible
**Solution**:
1. Verify user is admin: `db_enhanced.get_user_by_username('your_user')`
2. Check role field (should be 'admin')
3. Promote user: `db_enhanced.update_user_role('your_user', 'admin')`

---

## 🚀 Performance Tips

### For 100-500 Users:
- Default settings work great
- No additional configuration needed

### For 500-1000 Users:
```python
# Increase connection pool
POOL_SIZE = 15

# Increase cache TTL for less frequently changing data
cache_set(key, value, ttl=600)  # 10 minutes

# Consider adding indexes for your specific queries
```

### For 1000+ Users:
```python
# Increase connection pool significantly
POOL_SIZE = 20

# Consider PostgreSQL instead of SQLite
# Add Redis for distributed caching
# Use load balancer for multiple app instances
```

---

## 📚 API Endpoints

### Public Endpoints
- `POST /register` - Register new user
- `POST /login` - User login
- `GET /logout` - User logout

### Authenticated Endpoints
- `GET /` - Main dashboard
- `GET /settings` - User settings
- `POST /update_settings` - Update settings
- `GET /start/<site>` - Start scraper
- `GET /stop/<site>` - Stop scraper
- `GET /analytics` - Analytics dashboard

### API Endpoints (JSON)
- `GET /api/status` - Scraper status
- `GET /api/listings` - Get listings
- `GET /api/system-status` - System status
- `GET /api/analytics/*` - Various analytics endpoints

### Admin Endpoints
- `GET /admin` - Admin dashboard
- `GET /admin/users` - User management
- `GET /admin/user/<username>` - User details
- `POST /admin/user/<username>/update-role` - Update user role
- `POST /admin/user/<username>/deactivate` - Deactivate user
- `POST /admin/user/<username>/reset-rate-limit` - Reset rate limits
- `GET /admin/activity` - Activity log
- `GET /admin/cache` - Cache management
- `POST /admin/cache/clear` - Clear cache
- `POST /admin/cache/cleanup` - Cleanup expired cache

---

## ✅ Post-Setup Checklist

- [ ] Database migrated successfully
- [ ] Enhanced version running
- [ ] Admin user created
- [ ] Admin dashboard accessible
- [ ] `.env` file created with secure SECRET_KEY
- [ ] Tested user registration
- [ ] Tested user login
- [ ] Tested rate limiting
- [ ] Tested admin features
- [ ] Database backups configured
- [ ] Logs monitored

---

## 🎉 You're All Set!

Your Super Bot is now configured to handle 1,000+ users securely and efficiently!

### Key Features Enabled:
✅ Database connection pooling
✅ Rate limiting
✅ Intelligent caching
✅ User roles (admin/user)
✅ Activity logging
✅ Admin dashboard
✅ Enhanced security

### Next Steps:
1. Read `SCALABILITY_GUIDE.md` for advanced configuration
2. Set up monitoring/alerting
3. Configure backups
4. Test with load (use tools like Apache Bench or Locust)

---

**Need Help?** Check the logs at `logs/superbot.log`
