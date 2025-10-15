# Render.com Deployment Guide

This guide will walk you through deploying your Super-Bot application to Render.com.

## Prerequisites

- A Render.com account (sign up at https://render.com)
- Your code pushed to a Git repository (GitHub, GitLab, or Bitbucket)
- Stripe account for payments (if using subscription features)
- Twilio account for SMS notifications (optional)

## Step 1: Prepare Your Repository

### 1.1 Push Your Code to GitHub

If you haven't already, push your code to a Git repository:

```bash
# Initialize git if not already done
git init

# Add all files
git add .

# Commit your changes
git commit -m "Initial commit - Ready for Render deployment"

# Add your GitHub repository as remote
git remote add origin https://github.com/YOUR_USERNAME/super-bot.git

# Push to GitHub
git push -u origin main
```

### 1.2 Verify Important Files

Make sure these files are in your repository:
- ✅ `Procfile` - Web server configuration
- ✅ `requirements.txt` - Python dependencies
- ✅ `runtime.txt` - Python version
- ✅ `gunicorn_config.py` - Gunicorn configuration
- ✅ `app.py` - Main application file

## Step 2: Create Render Account & Project

### 2.1 Sign Up for Render

1. Go to https://render.com
2. Click "Get Started for Free"
3. Sign up with your GitHub account (recommended) or email

### 2.2 Create a New Web Service

1. Click "New +" in the dashboard
2. Select "Web Service"
3. Connect your GitHub account if you haven't already
4. Select your repository (super-bot)
5. Click "Connect"

## Step 3: Configure Your Web Service

### 3.1 Basic Settings

Configure the following settings:

- **Name**: `super-bot` (or your preferred name)
- **Region**: Choose closest to your users (e.g., Oregon for US West)
- **Branch**: `main` (or your default branch)
- **Root Directory**: Leave empty (root of repo)
- **Runtime**: `Python 3`
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `gunicorn --config gunicorn_config.py app:socketio`

### 3.2 Instance Type

Choose based on your needs:
- **Free Tier**: Good for testing (spins down after inactivity)
- **Starter ($7/month)**: 512MB RAM, good for small projects
- **Standard ($25/month)**: 2GB RAM, recommended for production
- **Pro ($85/month)**: 4GB RAM, for high traffic

### 3.3 Environment Variables

Click "Advanced" and add the following environment variables:

#### Required Variables:

```bash
# Flask Configuration
SECRET_KEY=your-very-long-random-secret-key-here-minimum-32-characters
FLASK_ENV=production
FLASK_DEBUG=False

# Session Security
SESSION_COOKIE_SECURE=True
SESSION_COOKIE_HTTPONLY=True
SESSION_COOKIE_SAMESITE=Lax
PERMANENT_SESSION_LIFETIME=3600

# Database (SQLite file will be created automatically)
DB_FILE=superbot.db

# Port (Render sets this automatically)
PORT=5000

# Worker Configuration
WEB_CONCURRENCY=2
```

#### Optional Variables (if using features):

```bash
# Email Notifications
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your-email@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_FROM_EMAIL=your-email@gmail.com
SMTP_FROM_NAME=Super-Bot Alerts

# SMS Notifications (Twilio)
TWILIO_ACCOUNT_SID=your-twilio-sid
TWILIO_AUTH_TOKEN=your-twilio-token
TWILIO_FROM_NUMBER=+1234567890

# Stripe Payments
STRIPE_SECRET_KEY=sk_live_your-key
STRIPE_PUBLISHABLE_KEY=pk_live_your-key
STRIPE_WEBHOOK_SECRET=whsec_your-secret
STRIPE_STANDARD_PRICE_ID=price_your-id
STRIPE_PRO_PRICE_ID=price_your-id
```

### 3.4 Advanced Settings

- **Auto-Deploy**: Yes (automatically deploy on git push)
- **Health Check Path**: Leave empty or set to `/`
- **Docker**: No

## Step 4: Deploy Your Application

### 4.1 Create the Service

1. Click "Create Web Service"
2. Render will start building your application
3. Watch the build logs in real-time
4. First deployment may take 5-10 minutes

### 4.2 Verify Deployment

Once deployed, you'll get a URL like:
```
https://super-bot.onrender.com
```

Visit this URL to test your application.

## Step 5: Post-Deployment Setup

### 5.1 Create Admin User

SSH into your Render instance or use the Render Shell:

1. In Render dashboard, click on your service
2. Go to "Shell" tab
3. Run the admin creation script:

```bash
python scripts/create_admin.py
```

Or manually create via the web interface at: `https://your-app.onrender.com/register`

### 5.2 Initialize Database

If using a fresh database, run:

```bash
python scripts/init_db.py
```

### 5.3 Configure Stripe Webhooks

1. Go to your Stripe Dashboard → Webhooks
2. Click "Add endpoint"
3. URL: `https://your-app.onrender.com/webhook/stripe`
4. Select events:
   - `customer.subscription.created`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
   - `invoice.payment_succeeded`
   - `invoice.payment_failed`
5. Copy the webhook secret and add to Render environment variables

## Step 6: Database Persistence (Important!)

### 6.1 The Problem

Render's free tier has **ephemeral storage**. Your SQLite database will be **deleted** when:
- The service restarts
- You redeploy
- The service spins down (free tier)

### 6.2 Solutions

#### Option A: Render PostgreSQL (Recommended)

1. In Render dashboard, click "New +" → "PostgreSQL"
2. Choose your plan (Free tier available)
3. Copy the connection string
4. Update your `app.py` to use PostgreSQL instead of SQLite
5. Add `psycopg2-binary==2.9.9` to `requirements.txt`

#### Option B: External Database

Use external database services:
- **Supabase** (Free tier available)
- **ElephantSQL** (Free tier available)
- **Railway** (Free tier available)

#### Option C: Automated Backups

Keep using SQLite but set up automated backups to external storage:
- Google Drive
- AWS S3
- Dropbox

See `scripts/backup_database.py` for backup functionality.

## Step 7: Monitoring & Maintenance

### 7.1 View Logs

1. In Render dashboard, click on your service
2. Go to "Logs" tab
3. View real-time application logs

### 7.2 Monitor Performance

- Check "Metrics" tab for CPU, memory, and request metrics
- Set up alerts for errors
- Monitor response times

### 7.3 Update Your Application

Simply push to your Git repository:

```bash
git add .
git commit -m "Your update message"
git push
```

Render will automatically detect changes and redeploy.

## Troubleshooting

### Build Fails

**Issue**: Build command fails

**Solution**: 
- Check build logs for specific errors
- Verify all dependencies in `requirements.txt`
- Ensure Python version in `runtime.txt` is supported

### Application Crashes

**Issue**: App starts but crashes immediately

**Solution**:
- Check logs for error messages
- Verify all environment variables are set
- Test locally with same environment variables

### Database Errors

**Issue**: Database connection errors

**Solution**:
- Verify database file path is writable
- Check file permissions
- Consider using PostgreSQL for persistence

### Slow Performance

**Issue**: Application is slow

**Solution**:
- Upgrade to higher tier (more RAM)
- Optimize database queries
- Enable caching
- Use CDN for static files

### Port Already in Use

**Issue**: "Address already in use" error

**Solution**:
- Render sets PORT automatically, don't hardcode it
- Use `os.getenv('PORT', '5000')` in your code
- Already configured in your `gunicorn_config.py` ✓

## Cost Estimation

### Free Tier
- $0/month
- 512MB RAM
- Spins down after 15 minutes of inactivity
- Good for testing

### Starter
- $7/month
- 512MB RAM
- Always on
- Good for small projects

### Standard
- $25/month
- 2GB RAM
- Always on
- Recommended for production

### Pro
- $85/month
- 4GB RAM
- Always on
- High traffic applications

## Security Checklist

- [ ] Change `SECRET_KEY` to a random long string
- [ ] Set `FLASK_DEBUG=False` in production
- [ ] Enable `SESSION_COOKIE_SECURE=True`
- [ ] Use HTTPS (automatic on Render)
- [ ] Store sensitive data in environment variables
- [ ] Don't commit `.env` files to Git
- [ ] Set up proper CORS if using API
- [ ] Enable rate limiting
- [ ] Keep dependencies updated
- [ ] Use strong passwords for admin accounts

## Next Steps

1. ✅ Deploy to Render
2. ✅ Set up environment variables
3. ✅ Configure database persistence
4. ✅ Create admin user
5. ✅ Test all features
6. ✅ Set up monitoring
7. ✅ Configure custom domain (optional)
8. ✅ Set up SSL certificate (automatic on Render)

## Need Help?

- Render Docs: https://render.com/docs
- Render Community: https://community.render.com
- Your App Logs: Check Render dashboard

## Quick Reference

| Item | Value |
|------|-------|
| Build Command | `pip install -r requirements.txt` |
| Start Command | `gunicorn --config gunicorn_config.py app:socketio` |
| Python Version | 3.11.9 |
| Port | Set by Render (use env var) |
| Database | SQLite (or PostgreSQL for persistence) |

---

**Congratulations!** Your Super-Bot application is now deployed on Render.com! 🚀

