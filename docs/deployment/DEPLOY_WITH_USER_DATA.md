# Deploying While Keeping User Logins

## Quick Start

Your application is now configured to use PostgreSQL for persistent storage. Follow these steps to deploy without losing user data:

### Step 1: Create PostgreSQL Database on Render

1. Go to Render dashboard → "New +" → "PostgreSQL"
2. Name: `superbot-db`
3. Database: `superbot`
4. Plan: **Free** ($0) or **Starter** ($7/month) - recommended
5. Click "Create Database"
6. Wait 1-2 minutes for creation

### Step 2: Deploy Your Application

The `render.yaml` is already configured to automatically connect PostgreSQL to your web service.

**If using render.yaml:**
- Just push to Git - Render will automatically:
  - Create the PostgreSQL database
  - Connect it to your web service
  - Set `DATABASE_URL` environment variable

**If NOT using render.yaml:**
1. In your web service, go to "Environment"
2. Add `DATABASE_URL` from PostgreSQL service dashboard

### Step 3: Migrate Existing Data (If You Have Users)

If you have existing users in SQLite that you want to preserve:

1. **Before deploying**, backup your SQLite database:
   ```bash
   python scripts/backup_database.py
   ```

2. **After PostgreSQL is set up**, migrate your data:
   ```bash
   # Set DATABASE_URL in your environment
   export DATABASE_URL="postgresql://user:pass@host:port/db"
   
   # Run migration script
   python scripts/migrate_sqlite_to_postgres.py
   ```

   Or on Render:
   ```bash
   # Use Render Shell
   python scripts/migrate_sqlite_to_postgres.py
   ```

### Step 4: Verify

1. Check application logs - should show "Using PostgreSQL database"
2. Test user login - existing users should work
3. Test user registration - new users should work
4. Redeploy - data should persist ✅

## What Gets Migrated

The migration script preserves:
- ✅ User accounts (username, email, password)
- ✅ User settings (keywords, prices, location)
- ✅ User subscriptions (tier, status, Stripe info)
- ✅ User verification status
- ✅ Login counts and last login times

## Troubleshooting

### "DATABASE_URL not set"
- Check Render environment variables
- Verify PostgreSQL service is connected to web service

### "psycopg2 not installed"
- Already in `requirements.txt` - should install automatically
- If not, manually add to requirements

### "Migration failed"
- Check PostgreSQL connection string
- Verify PostgreSQL service is running
- Check logs for specific errors

### "Users can't log in after migration"
- Verify passwords were migrated (check database)
- Users may need to reset passwords if password hashing changed
- Check application logs for login errors

## Current Status

✅ PostgreSQL support implemented
✅ Migration script available
✅ Auto-detection of database type
✅ Backward compatible with SQLite

## Next Deployments

After initial setup:
1. **No migration needed** - just deploy normally
2. **User data persists** automatically ✅
3. **No data loss** on deployments ✅

---

**Important**: Without PostgreSQL, user data will be lost on every deployment. Make sure PostgreSQL is set up before deploying with users!

