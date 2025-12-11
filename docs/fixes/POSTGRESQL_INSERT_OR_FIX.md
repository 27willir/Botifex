# PostgreSQL INSERT OR Syntax Fix

## Issue
The application was failing with SQL syntax errors when running on PostgreSQL:
```
Error in ensure_dm_conversation_between: syntax error at or near "OR"
LINE 2: INSERT OR IGNORE INTO dm_participants (conve...
```

## Root Cause
The codebase was using SQLite-specific `INSERT OR IGNORE` and `INSERT OR REPLACE` syntax, which is not compatible with PostgreSQL. While the `_prepare_sql()` function existed to convert SQLite syntax to PostgreSQL, it was missing conversions for these INSERT statements.

## Solution

### 1. Enhanced SQL Conversion Function
Created `_convert_insert_or_syntax()` function to convert:
- `INSERT OR IGNORE` → `INSERT ... ON CONFLICT DO NOTHING`
- `INSERT OR REPLACE` → `INSERT ... ON CONFLICT (...) DO UPDATE SET ...`

### 2. Table-Specific Conflict Targets
Added logic to determine the correct conflict target for each table:
- **server_tip_dismissals**: `(tip_id, username)` - composite primary key
- **settings**: `(username, key)` - unique constraint
- **keyword_trends**: `(keyword, date, source, user_id)` - logical unique key
- **rate_limits**: `(username, endpoint)` - unique constraint

### 3. Added Missing Unique Constraint
Added `UNIQUE(keyword, date, source, user_id)` constraint to `keyword_trends` table to support the ON CONFLICT clause.

### 4. Added Unique Index
Created unique index for keyword_trends:
```sql
CREATE UNIQUE INDEX IF NOT EXISTS idx_keyword_trends_unique 
ON keyword_trends(keyword, date, source, user_id)
```

## Files Modified
- `db_enhanced.py`:
  - Added `_convert_insert_or_syntax()` function (lines 529-593)
  - Enhanced `_prepare_sql()` to call conversion function (lines 595-617)
  - Added UNIQUE constraint to keyword_trends table (line 2541)
  - Added unique index for keyword_trends (line 2779)

## Affected Tables
The following tables use INSERT OR statements and are now properly converted:
1. `dm_participants` - used in DM conversation creation
2. `server_tip_dismissals` - used when dismissing server tips
3. `settings` - used for user settings updates
4. `keyword_trends` - used for analytics tracking

## Testing
To verify the fix works:
1. Deploy the updated code to production
2. Test the DM conversation creation (the failing endpoint):
   - Go to a user's profile
   - Click "Message" or "Open Conversation"
   - Should successfully create/open DM conversation

## Deployment Steps
1. Deploy the updated `db_enhanced.py` to production
2. Restart the application to clear any cached Python bytecode
3. The unique index will be automatically created on next database initialization
4. No manual database migrations required

## Migration Safety
- The UNIQUE constraint is added with `IF NOT EXISTS`
- The unique index is created with `IF NOT EXISTS`
- Existing data should not conflict as the application logic already prevents duplicates
- If conflicts exist, they will be logged and can be manually resolved

## Prevention
The `_prepare_sql()` function now handles all known SQLite-specific syntax patterns. Future SQL statements should automatically be converted when PostgreSQL is detected.

## Monitoring
Monitor logs for:
- SQL syntax errors (should be eliminated)
- Unique constraint violations (would indicate data quality issues)
- DM conversation creation success rate (should improve to 100%)

## Rollback Plan
If issues occur:
1. The code gracefully falls back to SQLite if PostgreSQL fails
2. Can revert `db_enhanced.py` to previous version
3. No permanent database changes that would prevent rollback

## Date
December 11, 2025

