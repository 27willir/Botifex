# Render Deployment Troubleshooting Guide

## Common Issues and Solutions

### Issue 1: eventlet Compatibility Error with Python 3.13

**Error Message:**
```
AttributeError: module 'eventlet.green.thread' has no attribute 'start_joinable_thread'
```

**Cause:** 
`eventlet` version 0.35.2 is not compatible with Python 3.13. Render may use Python 3.13 by default, but your app requires Python 3.11.

**Solutions:**

#### Solution A: Force Python 3.11 (Recommended)

1. **Add `.python-version` file** (already created):
   ```
   3.11.9
   ```

2. **Update `runtime.txt`** (already updated):
   ```
   python-3.11.9
   ```

3. **Use Dockerfile** (already created):
   - Render will use the Dockerfile which specifies Python 3.11
   - The Dockerfile is already configured in `render.yaml`

4. **Redeploy:**
   ```bash
   git add .
   git commit -m "Fix Python version compatibility"
   git push
   ```

#### Solution B: Use Gevent Instead of Eventlet

1. **Updated `requirements.txt`** (already done):
   - Added `gevent==24.2.1`
   - Kept `eventlet==0.35.2` for compatibility

2. **Updated `gunicorn_config.py`** (already done):
   - Changed default worker class to `gevent`
   - Made it configurable via `GUNICORN_WORKER_CLASS` env var

3. **Add environment variable in Render:**
   ```
   GUNICORN_WORKER_CLASS=gevent
   ```

4. **Redeploy:**
   ```bash
   git add .
   git commit -m "Switch to gevent worker"
   git push
   ```

#### Solution C: Use Sync Workers (Simple but Less Performant)

1. **Add environment variable in Render:**
   ```
   GUNICORN_WORKER_CLASS=sync
   ```

2. **Redeploy**

### Issue 2: Build Fails

**Possible Causes:**
- Missing dependencies in `requirements.txt`
- Incompatible package versions
- Network issues during build

**Solutions:**
1. Check build logs in Render dashboard
2. Test locally: `pip install -r requirements.txt`
3. Update package versions if needed
4. Ensure all dependencies are listed

### Issue 3: App Crashes on Startup

**Possible Causes:**
- Missing environment variables
- Database connection issues
- Port configuration problems

**Solutions:**
1. Check logs in Render dashboard
2. Verify all required environment variables are set
3. Test locally with same configuration
4. Check database connection string

### Issue 4: Database Not Persisting (Free Tier)

**Issue:** 
SQLite database is deleted on restart/redeploy.

**Solutions:**
1. **Use Render PostgreSQL** (Recommended):
   - Create PostgreSQL database in Render
   - Update connection string in environment variables
   - Add `psycopg2-binary==2.9.9` to requirements.txt

2. **Use External Database:**
   - Supabase (free tier)
   - ElephantSQL (free tier)
   - Railway (free tier)

3. **Set up Automated Backups:**
   - Use `scripts/backup_database.py`
   - Backup to Google Drive/S3/Dropbox

### Issue 5: Slow Performance

**Possible Causes:**
- Insufficient resources (free tier)
- Inefficient database queries
- No caching enabled

**Solutions:**
1. Upgrade to paid tier (Starter $7/month or Standard $25/month)
2. Optimize database queries
3. Enable caching
4. Use CDN for static files

### Issue 6: WebSocket Not Working

**Possible Causes:**
- Wrong worker class
- Missing dependencies
- Configuration issues

**Solutions:**
1. Ensure using `gevent` or `eventlet` worker class
2. Verify `Flask-SocketIO` and `python-socketio` are installed
3. Check WebSocket configuration in `websocket_manager.py`
4. Test locally first

## Quick Fixes

### Force Python 3.11
```bash
# Create .python-version file
echo "3.11.9" > .python-version

# Commit and push
git add .python-version
git commit -m "Force Python 3.11"
git push
```

### Switch to Gevent Worker
```bash
# Add to Render environment variables
GUNICORN_WORKER_CLASS=gevent

# Or update gunicorn_config.py (already done)
```

### Use Dockerfile
```bash
# Ensure Dockerfile exists (already created)
# Update render.yaml to use Dockerfile (already done)
# Commit and push
git add .
git commit -m "Use Dockerfile for deployment"
git push
```

## Environment Variables Checklist

Ensure these are set in Render:

**Required:**
- `SECRET_KEY` - Random long string
- `FLASK_ENV=production`
- `FLASK_DEBUG=False`
- `PORT` - Set automatically by Render

**Recommended:**
- `SESSION_COOKIE_SECURE=True`
- `SESSION_COOKIE_HTTPONLY=True`
- `SESSION_COOKIE_SAMESITE=Lax`
- `DB_FILE=superbot.db`
- `WEB_CONCURRENCY=2`
- `GUNICORN_WORKER_CLASS=gevent`

**Optional (if using features):**
- Email settings (SMTP_*)
- Stripe settings (STRIPE_*)
- Twilio settings (TWILIO_*)

## Testing Locally

Before deploying, test locally with production settings:

```bash
# Set environment variables
export FLASK_ENV=production
export FLASK_DEBUG=False
export SECRET_KEY=your-secret-key
export PORT=5000
export GUNICORN_WORKER_CLASS=gevent

# Run with gunicorn
gunicorn --config gunicorn_config.py app:socketio
```

## Getting Help

1. **Check Render Logs:**
   - Dashboard → Your Service → Logs

2. **Check Build Logs:**
   - Dashboard → Your Service → Build Logs

3. **Render Documentation:**
   - https://render.com/docs

4. **Render Community:**
   - https://community.render.com

5. **Common Issues:**
   - https://render.com/docs/troubleshooting-deploys

## Deployment Checklist

Before deploying:
- [ ] All dependencies in `requirements.txt`
- [ ] Python version specified in `runtime.txt`
- [ ] `.python-version` file created
- [ ] Dockerfile created (optional)
- [ ] Environment variables documented
- [ ] Tested locally with production settings
- [ ] Database persistence solution chosen
- [ ] Monitoring set up

After deploying:
- [ ] Build succeeds
- [ ] App starts without errors
- [ ] Homepage loads
- [ ] Registration works
- [ ] Login works
- [ ] Database persists (if configured)
- [ ] WebSocket works (if using)
- [ ] All features tested

## Still Having Issues?

1. Check the error logs in Render dashboard
2. Verify all files are committed and pushed
3. Try deploying with Dockerfile
4. Contact Render support
5. Check this guide for your specific error

---

**Last Updated:** After fixing Python 3.13 compatibility issue

