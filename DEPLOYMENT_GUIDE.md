# 🚀 Super Bot Deployment Guide

Complete guide to deploy your Super Bot application to production on the world wide web.

---

## Table of Contents
1. [Pre-Deployment Checklist](#pre-deployment-checklist)
2. [Deployment Options](#deployment-options)
3. [Option 1: Render (Recommended - FREE)](#option-1-render-recommended)
4. [Option 2: Railway (Easy & Fast)](#option-2-railway)
5. [Option 3: Heroku (Classic)](#option-3-heroku)
6. [Option 4: DigitalOcean/AWS (Advanced)](#option-4-digitalocean-aws)
7. [Post-Deployment Steps](#post-deployment-steps)
8. [Troubleshooting](#troubleshooting)

---

## Pre-Deployment Checklist

Before deploying, make sure you have:

### ✅ Required:
- [x] GitHub account (to push your code)
- [x] Hosting platform account (Render/Railway/Heroku)
- [x] All environment variables ready (see `env.production.template`)
- [x] Tested application locally

### ⚙️ Optional but Recommended:
- [ ] Stripe account (for subscription payments)
- [ ] Twilio account (for SMS notifications)
- [ ] Gmail/SMTP account (for email notifications)
- [ ] Custom domain name

---

## Deployment Options

| Platform | Cost | Difficulty | Database | Best For |
|----------|------|------------|----------|----------|
| **Render** | FREE tier | Easy ⭐⭐ | Included | Best free option |
| **Railway** | $5/month | Very Easy ⭐ | Included | Quick deployment |
| **Heroku** | $7/month | Easy ⭐⭐ | Add-on | Traditional choice |
| **DigitalOcean** | $6/month | Advanced ⭐⭐⭐⭐ | Self-managed | Full control |

---

## Option 1: Render (Recommended - FREE)

Render offers a generous free tier that's perfect for getting started!

### Step 1: Push Code to GitHub

```bash
# Initialize git (if not already done)
git init
git add .
git commit -m "Prepare for deployment"

# Create a new repository on GitHub, then:
git remote add origin https://github.com/YOUR-USERNAME/super-bot.git
git branch -M main
git push -u origin main
```

### Step 2: Create Render Account

1. Go to [render.com](https://render.com)
2. Sign up (free account)
3. Connect your GitHub account

### Step 3: Deploy Web Service

1. Click **"New +"** → **"Web Service"**
2. Connect your `super-bot` repository
3. Configure:
   - **Name**: `super-bot` (or your choice)
   - **Region**: Choose closest to your users
   - **Branch**: `main`
   - **Root Directory**: Leave blank
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:$PORT app:app`
   - **Instance Type**: `Free`

### Step 4: Add Environment Variables

In Render dashboard, go to **Environment** tab and add:

```
SECRET_KEY=your-super-secret-key-change-this
FLASK_ENV=production
FLASK_DEBUG=False
SESSION_COOKIE_SECURE=True
SESSION_COOKIE_HTTPONLY=True

# Add other variables from env.production.template
```

**Important**: Generate a secure SECRET_KEY:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### Step 5: Deploy!

1. Click **"Create Web Service"**
2. Wait 5-10 minutes for deployment
3. Your app will be live at `https://your-app-name.onrender.com`

### Step 6: Initialize Database

Once deployed, run these commands in Render Shell:

```bash
# Access Render Shell (in dashboard)
python scripts/init_db.py
python scripts/create_admin.py admin admin@example.com YourSecurePassword123!
```

---

## Option 2: Railway

Railway is super fast and easy, with $5 free credit monthly.

### Step 1: Push to GitHub (same as above)

### Step 2: Deploy on Railway

1. Go to [railway.app](https://railway.app)
2. Click **"Start a New Project"**
3. Select **"Deploy from GitHub repo"**
4. Select your `super-bot` repository
5. Railway will auto-detect Python and deploy!

### Step 3: Configure Environment Variables

In Railway dashboard:
1. Click on your service
2. Go to **"Variables"** tab
3. Add all variables from `env.production.template`

### Step 4: Access Your App

Railway will give you a URL like: `https://super-bot-production.up.railway.app`

---

## Option 3: Heroku

Heroku is a classic platform with excellent documentation.

### Step 1: Install Heroku CLI

```bash
# Download from: https://devcenter.heroku.com/articles/heroku-cli
# Or on Mac:
brew install heroku/brew/heroku
```

### Step 2: Create Heroku App

```bash
# Login
heroku login

# Create app
heroku create your-superbot-app

# Add Python buildpack
heroku buildpacks:set heroku/python
```

### Step 3: Configure Environment Variables

```bash
# Set environment variables
heroku config:set SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
heroku config:set FLASK_ENV=production
heroku config:set FLASK_DEBUG=False
heroku config:set SESSION_COOKIE_SECURE=True

# Add other variables
heroku config:set STRIPE_SECRET_KEY=your-stripe-key
heroku config:set SMTP_HOST=smtp.gmail.com
# ... etc
```

### Step 4: Deploy

```bash
git push heroku main

# Initialize database
heroku run python scripts/init_db.py
heroku run python scripts/create_admin.py admin admin@example.com Password123!
```

### Step 5: Open Your App

```bash
heroku open
```

---

## Option 4: DigitalOcean / AWS (Advanced)

For full control and scalability.

### Quick Start with DigitalOcean

1. **Create Droplet**
   - Ubuntu 22.04 LTS
   - $6/month plan (1GB RAM)
   - Add SSH key

2. **Connect via SSH**
   ```bash
   ssh root@your-droplet-ip
   ```

3. **Install Dependencies**
   ```bash
   # Update system
   apt update && apt upgrade -y
   
   # Install Python and required packages
   apt install python3 python3-pip nginx supervisor -y
   
   # Install Chrome for Selenium
   wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
   apt install ./google-chrome-stable_current_amd64.deb -y
   ```

4. **Clone and Setup Application**
   ```bash
   cd /var/www
   git clone https://github.com/YOUR-USERNAME/super-bot.git
   cd super-bot
   
   # Create virtual environment
   python3 -m venv venv
   source venv/bin/activate
   
   # Install requirements
   pip install -r requirements.txt
   
   # Create .env file
   cp env.production.template .env
   nano .env  # Edit with your values
   
   # Initialize database
   python scripts/init_db.py
   python scripts/create_admin.py admin admin@example.com Password123!
   ```

5. **Configure Gunicorn Service**
   
   Create `/etc/supervisor/conf.d/superbot.conf`:
   ```ini
   [program:superbot]
   directory=/var/www/super-bot
   command=/var/www/super-bot/venv/bin/gunicorn --worker-class eventlet -w 4 --bind 127.0.0.1:8000 app:app
   user=www-data
   autostart=true
   autorestart=true
   stderr_logfile=/var/log/superbot.err.log
   stdout_logfile=/var/log/superbot.out.log
   ```

6. **Configure Nginx**
   
   Create `/etc/nginx/sites-available/superbot`:
   ```nginx
   server {
       listen 80;
       server_name your-domain.com;

       location / {
           proxy_pass http://127.0.0.1:8000;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
           
           # WebSocket support
           proxy_http_version 1.1;
           proxy_set_header Upgrade $http_upgrade;
           proxy_set_header Connection "upgrade";
       }
       
       location /static {
           alias /var/www/super-bot/static;
       }
   }
   ```

7. **Enable and Start Services**
   ```bash
   # Enable Nginx site
   ln -s /etc/nginx/sites-available/superbot /etc/nginx/sites-enabled/
   nginx -t
   systemctl restart nginx
   
   # Start Supervisor
   supervisorctl reread
   supervisorctl update
   supervisorctl start superbot
   ```

8. **Setup SSL with Let's Encrypt**
   ```bash
   apt install certbot python3-certbot-nginx -y
   certbot --nginx -d your-domain.com
   ```

---

## Post-Deployment Steps

### 1. Test Your Deployment

Visit your app URL and verify:
- ✅ Homepage loads
- ✅ Can register new user
- ✅ Can login
- ✅ Admin dashboard works
- ✅ Scrapers can start/stop

### 2. Setup Stripe Webhooks

1. Go to [Stripe Dashboard](https://dashboard.stripe.com/webhooks)
2. Click **"Add endpoint"**
3. Enter URL: `https://your-app-url.com/webhook/stripe`
4. Select events:
   - `checkout.session.completed`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
5. Copy webhook secret to your environment variables

### 3. Configure Email Notifications

For Gmail:
1. Enable 2-Factor Authentication
2. Generate App Password: https://myaccount.google.com/apppasswords
3. Use App Password in `SMTP_PASSWORD` environment variable

### 4. Setup Monitoring

**Free Options:**
- **UptimeRobot**: Monitor uptime (free for 50 monitors)
- **Sentry**: Error tracking (free tier available)
- **Google Analytics**: User analytics

### 5. Backup Strategy

Run automated backups:
```bash
# Add to cron (on server)
0 2 * * * cd /var/www/super-bot && python scripts/backup_database.py
```

On Render/Railway/Heroku, use their built-in backup features.

---

## Environment Variables Reference

Must be set for production:

```env
# Core (Required)
SECRET_KEY=generate-a-long-random-string
FLASK_ENV=production
FLASK_DEBUG=False

# Security (Required)
SESSION_COOKIE_SECURE=True
SESSION_COOKIE_HTTPONLY=True

# Stripe (Required for payments)
STRIPE_SECRET_KEY=sk_live_...
STRIPE_PUBLISHABLE_KEY=pk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_STANDARD_PRICE_ID=price_...
STRIPE_PRO_PRICE_ID=price_...

# Email (Optional but recommended)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your-email@gmail.com
SMTP_PASSWORD=your-app-password

# SMS (Optional)
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_FROM_NUMBER=+1...
```

---

## Troubleshooting

### Issue: Application won't start

**Check:**
```bash
# View logs on Render/Railway/Heroku
render logs
railway logs
heroku logs --tail

# Check if all environment variables are set
# Check if database is initialized
# Check Python version compatibility
```

### Issue: Database errors

**Solution:**
```bash
# Reinitialize database
python scripts/init_db.py
python scripts/create_admin.py admin admin@example.com NewPassword123!
```

### Issue: Scrapers not working

**Note:** Most free hosting platforms (Render Free, Railway) don't support Selenium/Chrome.

**Solutions:**
1. Upgrade to paid plan with more resources
2. Use DigitalOcean/AWS for full control
3. Use scraping APIs like ScrapingBee or Apify

### Issue: WebSocket not connecting

**Check:**
- Ensure `eventlet` worker is used in Gunicorn
- Verify proxy configuration supports WebSocket upgrade
- Check firewall rules

### Issue: Slow performance

**Solutions:**
1. Enable caching (already configured)
2. Increase worker count: `WEB_CONCURRENCY=4`
3. Upgrade to higher tier hosting
4. Add Redis for better caching
5. Use CDN for static files

### Issue: SSL/HTTPS not working

**Solutions:**
- On Render/Railway/Heroku: Automatic HTTPS
- On DigitalOcean/AWS: Use Let's Encrypt (see above)
- Verify `SESSION_COOKIE_SECURE=True` only after HTTPS is working

---

## Performance Tips

### 1. Database Optimization
```bash
# Already configured in code:
- WAL mode enabled
- Connection pooling (10 connections)
- 15+ optimized indexes
```

### 2. Caching
```python
# Already implemented:
- User data cached for 5 minutes
- Settings cached for 5 minutes
- Listings cached for 2 minutes
```

### 3. Rate Limiting
```python
# Already configured:
- API: 60 requests/minute
- Scraper: 10 operations/minute
- Login: 5 attempts per 5 minutes
```

---

## Scaling Considerations

### For 100-500 Users:
- ✅ Default configuration works perfectly
- ✅ Free tier on Render is sufficient

### For 500-1,000 Users:
- Upgrade to paid tier ($7-20/month)
- Increase `POOL_SIZE=15`
- Increase `WEB_CONCURRENCY=4`

### For 1,000+ Users:
- Use DigitalOcean/AWS ($50+/month)
- Consider PostgreSQL instead of SQLite
- Add Redis for caching
- Use load balancer
- See `docs/guides/SCALABILITY_GUIDE.md`

---

## Security Checklist

Before going live:

- [ ] Change `SECRET_KEY` to secure random string
- [ ] Set `FLASK_DEBUG=False`
- [ ] Enable `SESSION_COOKIE_SECURE=True` (requires HTTPS)
- [ ] Use strong admin password
- [ ] Enable rate limiting (already configured)
- [ ] Configure CORS if needed
- [ ] Setup SSL/HTTPS certificate
- [ ] Review and update Terms of Service
- [ ] Setup error monitoring (Sentry)
- [ ] Configure automated backups
- [ ] Test all features in production

---

## Domain Setup (Optional)

### Connect Custom Domain:

**On Render:**
1. Go to Settings → Custom Domain
2. Add your domain
3. Update DNS records with Render's instructions

**On Railway:**
1. Go to Settings → Domains
2. Add custom domain
3. Update DNS records

**On Heroku:**
```bash
heroku domains:add www.yourdomain.com
# Follow DNS instructions
```

---

## Maintenance

### Regular Tasks:

**Daily:**
- Check error logs
- Monitor uptime

**Weekly:**
- Review user activity
- Check disk space
- Review security logs

**Monthly:**
- Update dependencies
- Database backup verification
- Performance review
- Security updates

### Update Application:

```bash
# On local machine
git add .
git commit -m "Update application"
git push origin main

# Render/Railway will auto-deploy
# Heroku requires:
git push heroku main
```

---

## Cost Estimates

### Monthly Costs by Platform:

| Platform | Hosting | Database | Total |
|----------|---------|----------|-------|
| Render Free | $0 | $0 | **$0** |
| Railway | $5 | Included | **$5** |
| Heroku Basic | $7 | Included | **$7** |
| DigitalOcean | $6 | Included | **$6** |

### Additional Services (Optional):

- Custom Domain: $10-15/year
- Stripe fees: 2.9% + $0.30 per transaction
- Twilio SMS: $0.0079 per message
- Email Service: Free (Gmail) or $0.0001 per email

---

## Next Steps

1. ✅ Choose a hosting platform
2. ✅ Set up environment variables
3. ✅ Deploy the application
4. ✅ Initialize database and create admin
5. ✅ Test all features
6. ✅ Configure Stripe webhooks
7. ✅ Setup monitoring
8. ✅ Configure backups
9. ✅ Connect custom domain (optional)
10. ✅ Launch! 🚀

---

## Support Resources

- **Render Docs**: https://render.com/docs
- **Railway Docs**: https://docs.railway.app
- **Heroku Docs**: https://devcenter.heroku.com
- **Flask Deployment**: https://flask.palletsprojects.com/deployment/
- **Gunicorn**: https://docs.gunicorn.org

---

## Success Checklist

After deployment, verify:

- [ ] Application is accessible via HTTPS
- [ ] Users can register and login
- [ ] Admin dashboard is accessible
- [ ] Scrapers can start/stop (if supported)
- [ ] Subscription checkout works
- [ ] Webhooks are receiving events
- [ ] Email notifications work
- [ ] WebSocket real-time updates work
- [ ] All pages load correctly
- [ ] API endpoints respond
- [ ] Static files (CSS/JS) load
- [ ] Monitoring is active
- [ ] Backups are configured

---

## 🎉 Congratulations!

Your Super Bot is now live on the world wide web!

**Share your deployment:** `https://your-app.onrender.com`

Need help? Check the logs, review the troubleshooting section, or refer to the platform-specific documentation.

---

**Built with ❤️ and ready for the world!**

