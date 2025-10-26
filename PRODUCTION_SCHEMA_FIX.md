# Production Database Schema Fix

## Issues
The production database is missing several required columns, causing 500 errors when users try to access the dashboard and subscription features.

### Issue 1: Missing `user_id` column in `listings` table
**Error:**
```
sqlite3.OperationalError: no such column: user_id
```
**Affected:** Dashboard page (after login)

### Issue 2: Missing `cancel_at_period_end` column in `subscriptions` table
**Error:**
```
sqlite3.OperationalError: no such column: cancel_at_period_end
```
**Affected:** Subscription features

## Root Cause
The production database initialization script (`scripts/init_production_db.py`) was missing several columns that the application code (`db_enhanced.py`) expects to exist.

## Solution Applied

### 1. Updated Production Database Initialization Script
- **File:** `scripts/init_production_db.py`
- **Changes:** 
  - Added `user_id TEXT` with foreign key to listings table
  - Added `cancel_at_period_end BOOLEAN DEFAULT 0` to subscriptions table
  - Added migration logic to check for missing columns and add them if needed

### 2. Enhanced Production Schema Fix Script
- **File:** `scripts/fix_production_schema.py`
- **Changes:** Updated to fix both missing columns:
  - `listings.user_id`
  - `subscriptions.cancel_at_period_end`

## Files Modified

1. **scripts/init_production_db.py**
   - Added `user_id TEXT` to listings table with foreign key constraint
   - Added `cancel_at_period_end BOOLEAN DEFAULT 0` to subscriptions table
   - Added migration logic to handle existing databases

2. **scripts/fix_production_schema.py**
   - Updated to add missing `user_id` column to listings table
   - Enhanced to add missing `cancel_at_period_end` column to subscriptions table
   - Added verification for both columns

## Deployment Instructions

### For Immediate Fix (Production)
Run the production schema fix script on the production server:

```bash
cd /opt/render/project/src
python scripts/fix_production_schema.py
```

This will:
1. Check if `listings.user_id` column exists and add it if missing
2. Check if `subscriptions.cancel_at_period_end` column exists and add it if missing
3. Verify both columns were added successfully

### For Future Deployments
The updated `scripts/init_production_db.py` now includes all required columns and migration logic, so future deployments will automatically handle these issues.

## Verification

After running the fix, verify both columns exist:

```sql
-- Check listings table
PRAGMA table_info(listings);

-- Check subscriptions table  
PRAGMA table_info(subscriptions);
```

The output should include:
- `listings` table: row with `user_id` column
- `subscriptions` table: row with `cancel_at_period_end` column

## Testing

The fix has been tested locally and shows:
- ✅ Columns added successfully to listings table
- ✅ Columns added successfully to subscriptions table
- ✅ Scripts run without errors
- ✅ Migration logic works correctly

## Impact

This fix resolves:
- 500 errors on dashboard page after login
- "no such column: user_id" errors
- Subscription-related functionality errors
- Database schema inconsistencies between local and production

The fix is backward compatible and safe to run on existing databases. Existing listings will have `user_id` set to NULL (which is allowed), and existing subscriptions will have `cancel_at_period_end` set to 0 (false).
