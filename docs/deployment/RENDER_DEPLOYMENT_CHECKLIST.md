# Render.com Deployment Checklist

## Pre-Deployment Checklist

### 1. Code Preparation
- [x] Procfile configured correctly
- [x] requirements.txt has all dependencies
- [x] runtime.txt specifies Python version
- [x] gunicorn_config.py is configured
- [ ] Code is pushed to GitHub/GitLab/Bitbucket
- [ ] .gitignore excludes sensitive files (.env, *.db, etc.)

### 2. Environment Variables to Set in Render

#### Required (Minimum):
```bash
SECRET_KEY=generate-a-random-32-char-string
FLASK_ENV=production
FLASK_DEBUG=False
PORT=5000
```

#### Recommended (For Full Features):
```bash
# Database
DB_FILE=superbot.db

# Session Security
SESSION_COOKIE_SECURE=True
SESSION_COOKIE_HTTPONLY=True
SESSION_COOKIE_SAMESITE=Lax
PERMANENT_SESSION_LIFETIME=3600

# Email (if using notifications)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your-email@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_FROM_EMAIL=your-email@gmail.com

# Stripe (if using payments)
STRIPE_SECRET_KEY=sk_live_...
STRIPE_PUBLISHABLE_KEY=pk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_STANDARD_PRICE_ID=price_...
STRIPE_PRO_PRICE_ID=price_...

# Twilio (if using SMS)
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_FROM_NUMBER=+1234567890
```

### 3. Generate SECRET_KEY

Run this command to generate a secure SECRET_KEY:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Copy the output and use it as your SECRET_KEY in Render.

## Deployment Steps

### Step 1: Push to GitHub
```bash
git add .
git commit -m "Ready for Render deployment"
git push origin main
```

### Step 2: Create Render Account
1. Go to https://render.com
2. Sign up with GitHub (recommended)
3. Verify your email

### Step 3: Create Web Service
1. Click "New +" → "Web Service"
2. Connect your repository
3. Configure settings:
   - Name: `super-bot`
   - Region: Choose closest to users
   - Branch: `main`
   - Runtime: `Python 3`
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn --config gunicorn_config.py app:socketio`

### Step 4: Add Environment Variables
1. Click "Advanced"
2. Add all required environment variables
3. Click "Create Web Service"

### Step 5: Wait for Deployment
- First deployment takes 5-10 minutes
- Watch build logs for any errors
- Once deployed, you'll get a URL like: `https://super-bot.onrender.com`

### Step 6: Post-Deployment
1. Test the application at your Render URL
2. Create admin user via web interface
3. Test all features
4. Configure Stripe webhooks (if using payments)

## Important Notes

### ⚠️ Database Persistence Warning
Render's free tier has **ephemeral storage**. Your SQLite database will be deleted when:
- Service restarts
- You redeploy
- Service spins down (free tier)

**Solutions:**
1. **Use Render PostgreSQL** (recommended)
   - Free tier available
   - Persistent storage
   - Add `psycopg2-binary==2.9.9` to requirements.txt

2. **Use External Database**
   - Supabase (free tier)
   - ElephantSQL (free tier)
   - Railway (free tier)

3. **Automated Backups**
   - Use `scripts/backup_database.py`
   - Backup to Google Drive/S3/Dropbox

### 💡 Tips
- Free tier spins down after 15 minutes of inactivity
- First request after spin-down takes ~30 seconds
- Consider upgrading to Starter ($7/month) for always-on service
- Monitor logs regularly in Render dashboard

## Troubleshooting

### Build Fails
- Check build logs
- Verify all dependencies in requirements.txt
- Ensure Python version is correct

### App Crashes
- Check logs for errors
- Verify environment variables
- Test locally with same config

### Database Issues
- Verify file permissions
- Consider using PostgreSQL
- Check backup scripts

## Cost Options

| Tier | Price | RAM | Always On | Best For |
|------|-------|-----|-----------|----------|
| Free | $0 | 512MB | No | Testing |
| Starter | $7 | 512MB | Yes | Small projects |
| Standard | $25 | 2GB | Yes | Production |
| Pro | $85 | 4GB | Yes | High traffic |

## Quick Commands

### Generate Secret Key
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### Test Locally with Production Settings
```bash
export FLASK_ENV=production
export FLASK_DEBUG=False
export SECRET_KEY=your-secret-key
python app.py
```

### View Logs
- In Render dashboard → Your Service → Logs tab

### Redeploy
```bash
git add .
git commit -m "Update message"
git push
# Render auto-deploys on push
```

## Security Checklist

- [ ] Changed SECRET_KEY from default
- [ ] Set FLASK_DEBUG=False
- [ ] Enabled SESSION_COOKIE_SECURE
- [ ] Using HTTPS (automatic on Render)
- [ ] Environment variables set in Render (not in code)
- [ ] .env file not committed to Git
- [ ] Strong admin passwords
- [ ] Rate limiting enabled
- [ ] CORS configured (if using API)

## Support Resources

- **Render Docs**: https://render.com/docs
- **Render Community**: https://community.render.com
- **Your Deployment Guide**: `docs/deployment/RENDER_DEPLOYMENT_GUIDE.md`

---

**Ready to Deploy?** Follow the steps above and your app will be live in minutes! 🚀

