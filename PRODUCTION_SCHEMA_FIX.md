# Production Database Schema Fix

## Issue Summary

The production database is experiencing schema-related errors:

1. **Missing `phone_number` column in users table** - causing `Error in get_notification_preferences: no such column: phone_number`
2. **Missing `settings` table** - causing `Error in get_settings: no such table: settings`

These errors are preventing users from accessing their profile and settings pages.

## Root Cause

The production database initialization script (`scripts/init_production_db.py`) was missing:
- The `phone_number` column in the users table
- The `settings` table entirely
- Proper schema migration logic for existing databases

## Solution

### Files Created/Modified

1. **`scripts/fix_production_schema.py`** - New script to fix existing production databases
2. **`scripts/deploy_schema_fix.py`** - Deployment script to run the fix
3. **`scripts/init_production_db.py`** - Updated to include missing schema elements
4. **`PRODUCTION_SCHEMA_FIX.md`** - This deployment guide

### What the Fix Does

1. **Adds missing `phone_number` column** to users table
2. **Adds missing notification columns** (`email_notifications`, `sms_notifications`) to users table
3. **Creates the missing `settings` table** with proper indexes
4. **Adds schema migration logic** to handle existing databases
5. **Verifies the fix** by testing database operations

## Deployment Instructions

### Option 1: Quick Fix (Recommended)

Run the automated fix script:

```bash
cd /path/to/super-bot
python scripts/deploy_schema_fix.py
```

This will:
- Fix the database schema
- Verify the fix worked
- Report success/failure

### Option 2: Manual Fix

If you prefer to run the fix manually:

```bash
cd /path/to/super-bot
python scripts/fix_production_schema.py
```

### Option 3: Reinitialize Database

If you want to start fresh (⚠️ **WARNING: This will delete all data**):

```bash
cd /path/to/super-bot
rm superbot.db  # ⚠️ DELETES ALL DATA
python scripts/init_production_db.py
```

## Verification

After running the fix, verify it worked by:

1. **Check the logs** - No more "no such column: phone_number" or "no such table: settings" errors
2. **Test user profile page** - Should load without errors
3. **Test settings page** - Should load without errors
4. **Check database schema**:

```bash
sqlite3 superbot.db ".schema users"
sqlite3 superbot.db ".schema settings"
```

## Expected Results

After the fix:

✅ **Users table** will have:
- `phone_number TEXT`
- `email_notifications BOOLEAN DEFAULT 1`
- `sms_notifications BOOLEAN DEFAULT 0`

✅ **Settings table** will exist with:
- `id`, `username`, `key`, `value`, `updated_at` columns
- Proper indexes on `username` and `key`
- Foreign key constraint to users table

✅ **Application errors** will be resolved:
- Profile page loads without errors
- Settings page loads without errors
- Notification preferences work correctly

## Rollback Plan

If the fix causes issues, you can:

1. **Restore from backup** (if you have one)
2. **Revert the database** to a previous state
3. **Contact support** with the error logs

## Prevention

To prevent this in the future:

1. **Always test schema changes** in development first
2. **Use the updated `init_production_db.py`** for new deployments
3. **Include schema migration logic** in all database changes
4. **Verify all required tables and columns** exist before deployment

## Files Modified

- `scripts/init_production_db.py` - Added missing schema elements
- `scripts/fix_production_schema.py` - New fix script
- `scripts/deploy_schema_fix.py` - New deployment script
- `PRODUCTION_SCHEMA_FIX.md` - This documentation

## Support

If you encounter issues:

1. Check the application logs for specific error messages
2. Verify the database file exists and is accessible
3. Ensure you have proper permissions to modify the database
4. Contact the development team with error logs

---

**Status**: Ready for deployment
**Risk Level**: Low (additive changes only)
**Estimated Time**: 2-5 minutes
**Rollback**: Available