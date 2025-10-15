# Python 3.13 Compatibility Fix

## Problem

Your deployment failed with this error:
```
AttributeError: module 'eventlet.green.thread' has no attribute 'start_joinable_thread'
```

**Root Cause:** 
- Render was using Python 3.13.4
- `eventlet` version 0.35.2 is not compatible with Python 3.13
- Your app requires Python 3.11 for compatibility

## Solution Applied

I've fixed the issue with multiple approaches:

### 1. ✅ Force Python 3.11
- Created `.python-version` file with `3.11.9`
- Updated `runtime.txt` to specify `python-3.11.9`
- Created `Dockerfile` that uses Python 3.11 base image

### 2. ✅ Switch to Gevent Worker
- Updated `gunicorn_config.py` to use `gevent` worker (Python 3.13 compatible)
- Added `gevent==24.2.1` to `requirements.txt`
- Made worker class configurable via `GUNICORN_WORKER_CLASS` environment variable
- Updated `render.yaml` with gevent configuration

### 3. ✅ Updated Configuration Files
- `Procfile` - Updated to use gunicorn_config.py
- `requirements.txt` - Added gevent
- `render.yaml` - Added worker class environment variable

## Files Modified

### New Files:
- `.python-version` - Forces Python 3.11
- `Dockerfile` - Docker configuration with Python 3.11
- `docs/deployment/RENDER_TROUBLESHOOTING.md` - Troubleshooting guide

### Modified Files:
- `gunicorn_config.py` - Changed worker class to gevent
- `requirements.txt` - Added gevent==24.2.1
- `Procfile` - Updated to use gunicorn_config.py
- `render.yaml` - Added GUNICORN_WORKER_CLASS environment variable

## What to Do Next

### Step 1: Commit and Push Changes

```bash
git add .
git commit -m "Fix Python 3.13 compatibility - switch to gevent worker"
git push
```

### Step 2: Update Render Configuration

**Option A: Let Render Auto-Detect (Recommended)**
- The `.python-version` file will force Python 3.11
- Render will automatically use the correct Python version

**Option B: Manual Configuration**
1. Go to Render dashboard → Your Service → Settings
2. Add environment variable:
   ```
   GUNICORN_WORKER_CLASS=gevent
   ```
3. Save and redeploy

### Step 3: Redeploy

Render will automatically redeploy when you push to GitHub. Or manually trigger a deploy:
1. Go to Render dashboard → Your Service
2. Click "Manual Deploy" → "Deploy latest commit"

### Step 4: Verify Deployment

1. Check build logs - should show Python 3.11
2. Check runtime logs - should start with gevent worker
3. Test your application at your Render URL

## Expected Build Log

You should see:
```
==> Installing Python version 3.11.9...
==> Using Python version 3.11.9 (default)
```

And in runtime logs:
```
[INFO] Starting gunicorn with gevent workers
```

## Alternative Solutions

If you still have issues, try these alternatives:

### Option 1: Use Sync Workers (Simple)
Add to Render environment variables:
```
GUNICORN_WORKER_CLASS=sync
```

### Option 2: Use Dockerfile
The Dockerfile is already created and configured. Render will use it automatically if:
- You have a Dockerfile in your repo (✓ already created)
- It's specified in render.yaml (✓ already configured)

### Option 3: Upgrade Eventlet (Future)
Wait for eventlet to support Python 3.13, then:
1. Update eventlet in requirements.txt
2. Change worker class back to eventlet
3. Remove gevent if not needed

## Testing Locally

Test with production settings:

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

## Troubleshooting

### Still seeing the error?

1. **Clear Render cache:**
   - Delete and recreate the service
   - Or contact Render support

2. **Force Python version:**
   - Check `.python-version` file exists
   - Verify `runtime.txt` has `python-3.11.9`

3. **Check worker class:**
   - Verify `GUNICORN_WORKER_CLASS=gevent` in environment variables
   - Or check gunicorn_config.py default

4. **Use Dockerfile:**
   - Render should automatically detect and use Dockerfile
   - Verify Dockerfile exists in root directory

### Need More Help?

- Check `docs/deployment/RENDER_TROUBLESHOOTING.md`
- Visit Render docs: https://render.com/docs
- Check Render community: https://community.render.com

## Summary

✅ **Problem:** eventlet incompatible with Python 3.13  
✅ **Solution:** Switched to gevent worker + forced Python 3.11  
✅ **Status:** Ready to deploy  
✅ **Next Step:** Commit, push, and redeploy

---

**Your app is now ready to deploy successfully!** 🚀

