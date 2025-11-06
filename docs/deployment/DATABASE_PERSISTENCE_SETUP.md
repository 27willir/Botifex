# Database Persistence Setup Guide

## ⚠️ CRITICAL: User Data Loss Prevention

**Your application currently uses SQLite, which stores data in the filesystem. On Render (and most cloud platforms), the filesystem is EPHEMERAL - meaning it gets wiped on every deployment, restart, or when the service spins down.**

**This means ALL user data, logins, and information will be DELETED on each deployment unless you use a persistent database like PostgreSQL.**

## ✅ Solution: Use PostgreSQL

We've configured your application to automatically use PostgreSQL when `DATABASE_URL` is available. Here's how to set it up:

### Step 1: Create PostgreSQL Database on Render

1. Go to your Render dashboard
2. Click "New +" → "PostgreSQL"
3. Configure:
   - **Name**: `superbot-db`
   - **Database Name**: `superbot`
   - **User**: `superbot`
   - **Plan**: 
     - **Free** ($0/month) - Good for testing, 90 days retention
     - **Starter** ($7/month) - Recommended for production
     - **Standard** ($25/month) - For high traffic
4. Click "Create Database"
5. Wait for database to be created (takes 1-2 minutes)

### Step 2: Connect Database to Web Service

The `render.yaml` file is already configured to automatically connect the PostgreSQL database to your web service. The `DATABASE_URL` environment variable will be automatically set.

**If you're not using `render.yaml`**, manually add the connection string:

1. In your Render web service, go to "Environment"
2. Add environment variable:
   - **Key**: `DATABASE_URL`
   - **Value**: Copy from PostgreSQL service dashboard (under "Connection String")

### Step 3: Verify Database Connection

After deployment, your application will automatically:
- Detect PostgreSQL via `DATABASE_URL`
- Use PostgreSQL instead of SQLite
- Preserve all user data across deployments

### Step 4: Initialize Database Schema

On first deployment with PostgreSQL, the database schema will be automatically created. You can also manually initialize:

```bash
# SSH into Render instance or use Render Shell
python scripts/init_db.py
```

## 🔄 Migration from SQLite to PostgreSQL

If you have existing SQLite data you want to migrate:

### Option 1: Fresh Start (Recommended for new deployments)
- Just deploy with PostgreSQL - the schema will be created automatically
- Users can register new accounts

### Option 2: Export/Import Data (If you have existing users)

1. **Export SQLite data** (before deploying):
   ```bash
   # Create backup
   python scripts/backup_database.py
   ```

2. **Deploy with PostgreSQL** - schema will be created automatically

3. **Import data** (requires custom script):
   - Contact support for migration assistance
   - Or manually recreate users if manageable

## 📊 Database Plans Comparison

| Plan | Cost | Storage | Best For |
|------|------|---------|----------|
| Free | $0 | 256MB | Testing, development |
| Starter | $7 | 1GB | Small production apps |
| Standard | $25 | 10GB | Production apps |
| Pro | $85 | 40GB | High traffic apps |

## ✅ Verification Checklist

After setup, verify:

- [ ] PostgreSQL database created in Render
- [ ] `DATABASE_URL` environment variable is set (check in Render dashboard)
- [ ] Application starts without errors
- [ ] Database schema is created (check logs)
- [ ] User registration works
- [ ] User login works
- [ ] Data persists after redeployment

## 🚨 Troubleshooting

### "psycopg2 not installed"
- **Solution**: The dependency is in `requirements.txt`. Make sure you've pushed the latest code and Render rebuilds.

### "Database connection failed"
- **Solution**: Check that `DATABASE_URL` is set correctly in environment variables
- Verify PostgreSQL service is running in Render dashboard

### "No data after deployment"
- **Solution**: Make sure you're using PostgreSQL, not SQLite. Check logs for database type detection.

### "Schema errors"
- **Solution**: Run `python scripts/init_db.py` manually to create tables

## 📝 Current Status

✅ PostgreSQL support added to codebase
✅ `render.yaml` configured for PostgreSQL
✅ Auto-detection of database type
✅ Backward compatible with SQLite (for local development)

## 🔐 Security Notes

- PostgreSQL connection strings are automatically encrypted by Render
- Database credentials are stored securely in Render environment variables
- Never commit `DATABASE_URL` to Git
- Use Render's built-in database connection management

## 💡 Local Development

For local development, continue using SQLite (no `DATABASE_URL` needed):

```bash
# Local development - uses SQLite by default
python app.py
```

For testing PostgreSQL locally:

```bash
# Set DATABASE_URL to local PostgreSQL
export DATABASE_URL="postgresql://user:password@localhost:5432/superbot"
python app.py
```

## 🎯 Summary

**Before**: SQLite → Data lost on every deployment ❌
**After**: PostgreSQL → Data persists across deployments ✅

Your user login information and all user data will now be preserved when you deploy!

---

**Need Help?**
- Check Render logs: Dashboard → Your Service → Logs
- Verify environment variables: Dashboard → Your Service → Environment
- Test database connection: Render Shell → `python scripts/init_db.py`

