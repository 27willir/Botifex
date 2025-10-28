# 🚀 Render.com Quick Start Guide

Deploy your Super-Bot application to Render.com in **5 simple steps**!

## Step 1: Generate Your SECRET_KEY

Run this command in your terminal:

```bash
python scripts/generate_secret_key.py
```

Copy the generated key - you'll need it in Step 3.

## Step 2: Push Your Code to GitHub

```bash
# If you haven't already initialized git
git init
git add .
git commit -m "Ready for Render deployment"

# Add your GitHub repository
git remote add origin https://github.com/YOUR_USERNAME/super-bot.git
git push -u origin main
```

## Step 3: Create Render Account & Deploy

1. **Go to https://render.com** and sign up (use GitHub for easy connection)

2. **Click "New +" → "Web Service"**

3. **Connect your repository:**
   - Select your GitHub account
   - Choose the `super-bot` repository
   - Click "Connect"

4. **Configure your service:**
   - **Name:** `super-bot`
   - **Region:** Choose closest to you (e.g., Oregon)
   - **Branch:** `main`
   - **Runtime:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn --config gunicorn_config.py app:socketio`
   - **Instance Type:** Free (for testing) or Starter ($7/month for always-on)

5. **Add Environment Variables** (click "Advanced"):
   
   **Required:**
   ```bash
   SECRET_KEY=paste-your-generated-key-here
   FLASK_ENV=production
   FLASK_DEBUG=False
   ```
   
   **Optional but Recommended:**
   ```bash
   SESSION_COOKIE_SECURE=True
   SESSION_COOKIE_HTTPONLY=True
   SESSION_COOKIE_SAMESITE=Lax
   DB_FILE=superbot.db
   WEB_CONCURRENCY=2
   ```

6. **Click "Create Web Service"** and wait 5-10 minutes for deployment!

## Step 4: Test Your Application

Once deployed, you'll get a URL like:
```
https://super-bot.onrender.com
```

Visit it and test:
- ✅ Homepage loads
- ✅ Registration works
- ✅ Login works
- ✅ Create a search
- ✅ View results

## Step 5: Create Admin User

1. Go to `https://your-app.onrender.com/register`
2. Register a new account
3. (Optional) Use the admin panel at `/admin` if you have admin access

---

## 🎉 Congratulations!

Your app is now live on Render.com!

---

## ⚠️ Important Notes

### Database Persistence
**Free tier has ephemeral storage** - your database will be deleted when:
- Service restarts
- You redeploy
- Service spins down (after 15 min inactivity)

**Solutions:**
1. **Use Render PostgreSQL** (recommended)
   - Free tier available
   - Go to "New +" → "PostgreSQL"
   - Add `psycopg2-binary==2.9.9` to requirements.txt

2. **Use External Database**
   - Supabase (free tier)
   - ElephantSQL (free tier)

3. **Automated Backups**
   - Use `scripts/backup_database.py`
   - Backup to Google Drive/S3

### Free Tier Limitations
- Spins down after 15 minutes of inactivity
- First request after spin-down takes ~30 seconds
- No persistent storage

### Upgrading
- **Starter ($7/month):** Always on, 512MB RAM
- **Standard ($25/month):** Always on, 2GB RAM (recommended for production)
- **Pro ($85/month):** Always on, 4GB RAM (high traffic)

---

## 📚 Full Documentation

For detailed information, see:
- **Complete Guide:** `docs/deployment/RENDER_DEPLOYMENT_GUIDE.md`
- **Checklist:** `RENDER_DEPLOYMENT_CHECKLIST.md`
- **Stripe Setup:** `docs/deployment/stripe-setup.md`

---

## 🔧 Troubleshooting

### Build Fails
- Check build logs in Render dashboard
- Verify all dependencies in `requirements.txt`
- Ensure Python version is correct (3.11.9)

### App Crashes
- Check logs for error messages
- Verify environment variables are set
- Test locally with same config

### Database Issues
- Free tier has ephemeral storage
- Use PostgreSQL for persistence
- Set up automated backups

---

## 📞 Need Help?

- **Render Docs:** https://render.com/docs
- **Render Community:** https://community.render.com
- **Your Logs:** Check Render dashboard → Your Service → Logs

---

## 🚀 Quick Commands

### View Logs
```bash
# In Render dashboard → Your Service → Logs tab
```

### Redeploy
```bash
git add .
git commit -m "Update message"
git push
# Render auto-deploys on push
```

### Generate New Secret Key
```bash
python scripts/generate_secret_key.py
```

---

**Ready to deploy? Follow the 5 steps above and you'll be live in minutes!** 🎉

