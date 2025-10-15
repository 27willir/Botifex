# Super-Bot Deployment Guide

Complete guide to deploying Super-Bot to production.

## 🚀 Quick Deploy (5 Minutes)

### Prerequisites
- Heroku account (or other hosting provider)
- PostgreSQL database
- Stripe account (for payments)
- Git installed

### One-Command Deploy to Heroku

```bash
# 1. Login to Heroku
heroku login

# 2. Create app
heroku create your-app-name

# 3. Add PostgreSQL
heroku addons:create heroku-postgresql:mini

# 4. Set environment variables
heroku config:set SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
heroku config:set STRIPE_SECRET_KEY=your_stripe_key
heroku config:set STRIPE_WEBHOOK_SECRET=your_webhook_secret
heroku config:set STRIPE_STANDARD_PRICE_ID=your_standard_price_id
heroku config:set STRIPE_PRO_PRICE_ID=your_pro_price_id

# 5. Deploy
git push heroku main

# 6. Initialize database
heroku run python scripts/init_db.py

# 7. Create admin user
heroku run python scripts/create_admin.py

# Done! Your app is live at: https://your-app-name.herokuapp.com
```

---

## 📋 Table of Contents

1. [Environment Setup](#environment-setup)
2. [Configuration](#configuration)
3. [Database Setup](#database-setup)
4. [Stripe Integration](#stripe-integration)
5. [Deployment Options](#deployment-options)
6. [Post-Deployment](#post-deployment)
7. [Troubleshooting](#troubleshooting)

---

## 🔧 Environment Setup

### 1. Clone Repository

```bash
git clone <your-repo-url>
cd super-bot
```

### 2. Create Virtual Environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Mac/Linux
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Create Environment File

```bash
# Copy template
cp .env.example .env

# Edit with your values
nano .env  # or use your preferred editor
```

---

## ⚙️ Configuration

### Required Environment Variables

```bash
# Generate secure key
SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")

# Database (use PostgreSQL for production)
DATABASE_URL=postgresql://user:password@localhost:5432/superbot

# Stripe (get from https://dashboard.stripe.com)
STRIPE_SECRET_KEY=sk_live_...
STRIPE_PUBLISHABLE_KEY=pk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_STANDARD_PRICE_ID=price_...
STRIPE_PRO_PRICE_ID=price_...
```

### Security Settings (Production)

```bash
# Enable security features
FLASK_ENV=production
DEBUG=False
SESSION_COOKIE_SECURE=True
SESSION_COOKIE_HTTPONLY=True
```

### Optional: Email Configuration

```bash
# For notifications and verification emails
MAIL_SERVER=smtp.sendgrid.net
MAIL_PORT=587
MAIL_USE_TLS=True
MAIL_USERNAME=apikey
MAIL_PASSWORD=your_sendgrid_api_key
MAIL_DEFAULT_SENDER=noreply@yourdomain.com
```

### Optional: SMS Notifications

```bash
# Twilio for SMS alerts
TWILIO_ACCOUNT_SID=your_account_sid
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_PHONE_NUMBER=+1234567890
```

---

## 🗄️ Database Setup

### PostgreSQL (Recommended for Production)

```bash
# Install PostgreSQL
# Ubuntu/Debian
sudo apt-get install postgresql postgresql-contrib

# macOS
brew install postgresql

# Create database
createdb superbot

# Update DATABASE_URL in .env
DATABASE_URL=postgresql://localhost/superbot
```

### Initialize Database

```bash
# Run migration script
python scripts/init_db.py

# Verify tables created
psql superbot -c "\dt"
```

### Create Admin User

```bash
python scripts/create_admin.py
# Follow prompts to create admin account
```

---

## 💳 Stripe Integration

See [stripe-setup.md](stripe-setup.md) for detailed Stripe configuration.

### Quick Setup

1. **Create Stripe Account**: https://dashboard.stripe.com/register

2. **Get API Keys**: https://dashboard.stripe.com/apikeys
   - Copy Secret Key → `STRIPE_SECRET_KEY`
   - Copy Publishable Key → `STRIPE_PUBLISHABLE_KEY`

3. **Create Products**:
   - Standard Plan: $9.99/month
   - Pro Plan: $39.99/month
   - Copy Price IDs to environment variables

4. **Setup Webhooks**: https://dashboard.stripe.com/webhooks
   - Endpoint: `https://yourdomain.com/webhook/stripe`
   - Events: `checkout.session.completed`, `customer.subscription.*`, `invoice.*`
   - Copy Signing Secret → `STRIPE_WEBHOOK_SECRET`

---

## 🌐 Deployment Options

### Option 1: Heroku (Easiest)

```bash
# Install Heroku CLI
# https://devcenter.heroku.com/articles/heroku-cli

# Login
heroku login

# Create app
heroku create your-app-name

# Add PostgreSQL
heroku addons:create heroku-postgresql:mini

# Set environment variables
heroku config:set SECRET_KEY=your_secret_key
heroku config:set STRIPE_SECRET_KEY=your_stripe_key
# ... set all other variables

# Deploy
git push heroku main

# Initialize database
heroku run python scripts/init_db.py
heroku run python scripts/create_admin.py

# View logs
heroku logs --tail

# Open app
heroku open
```

**Heroku Configuration:**
- `Procfile` already configured
- `runtime.txt` specifies Python version
- `gunicorn_config.py` handles production server

### Option 2: DigitalOcean App Platform

```bash
# 1. Create account at digitalocean.com
# 2. Connect GitHub repository
# 3. Set environment variables in dashboard
# 4. Deploy automatically on push

# App Spec:
{
  "name": "super-bot",
  "services": [{
    "name": "web",
    "github": {
      "repo": "your-username/super-bot",
      "branch": "main"
    },
    "run_command": "gunicorn --config gunicorn_config.py app:app",
    "environment_slug": "python",
    "instance_count": 1,
    "instance_size_slug": "basic-xxs"
  }],
  "databases": [{
    "engine": "PG",
    "name": "superbot-db",
    "production": true
  }]
}
```

### Option 3: AWS Elastic Beanstalk

```bash
# Install EB CLI
pip install awsebcli

# Initialize
eb init -p python-3.11 super-bot

# Create environment
eb create super-bot-env

# Set environment variables
eb setenv SECRET_KEY=your_secret_key
eb setenv STRIPE_SECRET_KEY=your_stripe_key
# ... set all variables

# Deploy
eb deploy

# Open app
eb open

# View logs
eb logs
```

### Option 4: VPS (Ubuntu Server)

```bash
# SSH into server
ssh user@your-server-ip

# Update system
sudo apt update && sudo apt upgrade -y

# Install dependencies
sudo apt install python3-pip python3-venv nginx postgresql -y

# Clone repository
git clone <your-repo> /var/www/super-bot
cd /var/www/super-bot

# Setup virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Setup PostgreSQL
sudo -u postgres createdb superbot
sudo -u postgres createuser superbotuser
sudo -u postgres psql -c "ALTER USER superbotuser PASSWORD 'your_password';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE superbot TO superbotuser;"

# Configure environment
cp .env.example .env
nano .env  # Edit with your values

# Initialize database
python scripts/init_db.py
python scripts/create_admin.py

# Setup systemd service
sudo nano /etc/systemd/system/super-bot.service
```

**Systemd Service File:**
```ini
[Unit]
Description=Super-Bot Application
After=network.target

[Service]
User=www-data
WorkingDirectory=/var/www/super-bot
Environment="PATH=/var/www/super-bot/venv/bin"
ExecStart=/var/www/super-bot/venv/bin/gunicorn --config gunicorn_config.py app:app

[Install]
WantedBy=multi-user.target
```

```bash
# Start service
sudo systemctl start super-bot
sudo systemctl enable super-bot

# Configure Nginx
sudo nano /etc/nginx/sites-available/super-bot
```

**Nginx Configuration:**
```nginx
server {
    listen 80;
    server_name yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
# Enable site
sudo ln -s /etc/nginx/sites-available/super-bot /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx

# Setup SSL with Let's Encrypt
sudo apt install certbot python3-certbot-nginx -y
sudo certbot --nginx -d yourdomain.com
```

---

## 🔒 Post-Deployment

### 1. Verify Deployment

```bash
# Check app is running
curl https://yourdomain.com

# Test login page
curl https://yourdomain.com/login

# Check API status
curl https://yourdomain.com/api/status
```

### 2. Setup Monitoring

**Application Monitoring:**
```bash
# Install Sentry for error tracking
pip install sentry-sdk

# Add to app.py
import sentry_sdk
sentry_sdk.init(dsn="your-sentry-dsn")
```

**Uptime Monitoring:**
- UptimeRobot: https://uptimerobot.com
- Pingdom: https://www.pingdom.com

### 3. Configure Backups

```bash
# Add to crontab for daily backups
crontab -e

# Add this line (runs daily at 2 AM)
0 2 * * * cd /var/www/super-bot && /var/www/super-bot/venv/bin/python scripts/backup_database.py
```

### 4. Setup Logging

```bash
# Configure log rotation
sudo nano /etc/logrotate.d/super-bot
```

```
/var/www/super-bot/logs/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 www-data www-data
}
```

### 5. Security Checklist

- [ ] HTTPS enabled (SSL certificate)
- [ ] Secret keys are secure and random
- [ ] `DEBUG=False` in production
- [ ] Database credentials secured
- [ ] Firewall configured (ports 80, 443 only)
- [ ] Regular backups scheduled
- [ ] Error logging configured
- [ ] Rate limiting enabled
- [ ] CSRF protection enabled
- [ ] Security headers set

---

## 🐛 Troubleshooting

### App Won't Start

**Check logs:**
```bash
# Heroku
heroku logs --tail

# VPS
sudo journalctl -u super-bot -f

# Check process
ps aux | grep gunicorn
```

**Common Issues:**
1. **Missing environment variables**
   ```bash
   # Check all variables are set
   heroku config  # Heroku
   printenv | grep STRIPE  # VPS
   ```

2. **Database connection failed**
   ```bash
   # Test PostgreSQL connection
   psql $DATABASE_URL -c "SELECT 1;"
   ```

3. **Port already in use**
   ```bash
   # Find and kill process
   lsof -i :5000
   kill -9 <PID>
   ```

### Stripe Webhooks Not Working

1. **Check webhook URL is correct**
   ```
   https://yourdomain.com/webhook/stripe
   ```

2. **Verify webhook secret**
   ```bash
   echo $STRIPE_WEBHOOK_SECRET
   ```

3. **Test webhook locally**
   ```bash
   # Use Stripe CLI
   stripe listen --forward-to localhost:5000/webhook/stripe
   ```

4. **Check logs for signature verification errors**

### Scrapers Not Running

1. **Check Chrome is installed**
   ```bash
   google-chrome --version
   ```

2. **Install Chrome on server**
   ```bash
   wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
   sudo apt install ./google-chrome-stable_current_amd64.deb
   ```

3. **Check logs**
   ```bash
   tail -f logs/superbot.log | grep scraper
   ```

### Database Migration Issues

```bash
# Backup current database
python scripts/backup_database.py

# Reset database (WARNING: deletes data)
python scripts/init_db.py --reset

# Restore from backup if needed
psql superbot < backups/backup_YYYYMMDD.sql
```

### Performance Issues

1. **Check database queries**
   ```python
   # Enable query logging
   import logging
   logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)
   ```

2. **Monitor memory usage**
   ```bash
   # Check memory
   free -h
   
   # Check app memory
   ps aux | grep gunicorn
   ```

3. **Scale workers**
   ```bash
   # Update gunicorn_config.py
   workers = 4  # Increase workers
   ```

### SSL Certificate Issues

```bash
# Renew Let's Encrypt certificate
sudo certbot renew

# Test renewal
sudo certbot renew --dry-run
```

---

## 📚 Additional Resources

- **Heroku Documentation**: https://devcenter.heroku.com/categories/python-support
- **DigitalOcean Guides**: https://www.digitalocean.com/community/tutorials
- **Stripe Documentation**: https://stripe.com/docs/webhooks
- **Flask Deployment**: https://flask.palletsprojects.com/en/latest/deploying/
- **Gunicorn Documentation**: https://docs.gunicorn.org/

---

## 🆘 Getting Help

- **Documentation**: See [docs/](../)
- **Issues**: Create GitHub issue
- **Email**: support@example.com
- **Community**: Discord/Slack channel

---

## ✅ Deployment Checklist

### Pre-Deployment
- [ ] All tests passing
- [ ] Environment variables configured
- [ ] Database migrations ready
- [ ] Stripe products created
- [ ] Domain configured

### Deployment
- [ ] Code deployed
- [ ] Database initialized
- [ ] Admin user created
- [ ] Stripe webhooks configured
- [ ] SSL certificate installed

### Post-Deployment
- [ ] App accessible
- [ ] Login working
- [ ] Scrapers starting
- [ ] Payments working
- [ ] Monitoring configured
- [ ] Backups scheduled
- [ ] Logs rotating

---

**Your Super-Bot is now live!** 🎉

For ongoing maintenance, see [configuration.md](configuration.md) and [troubleshooting.md](troubleshooting.md).

