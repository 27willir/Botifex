# PostgreSQL INSERT OR Syntax Fix - Deployment Guide

## Issue Fixed
Fixed SQL syntax error occurring on PostgreSQL when creating DM conversations:
```
Error in ensure_dm_conversation_between: syntax error at or near "OR"
LINE 2: INSERT OR IGNORE INTO dm_participants (conve...
```

## Changes Made
1. ✅ Added `_convert_insert_or_syntax()` function to convert SQLite INSERT OR statements to PostgreSQL
2. ✅ Enhanced `_prepare_sql()` to handle INSERT OR IGNORE and INSERT OR REPLACE
3. ✅ Added UNIQUE constraint to `keyword_trends` table
4. ✅ Added unique index for `keyword_trends`

## Quick Deployment (Recommended)

### Option 1: Git Push (Auto-Deploy on Render)
```powershell
# Stage and commit the changes
git add db_enhanced.py docs/fixes/POSTGRESQL_INSERT_OR_FIX.md

# Commit with descriptive message
git commit -m "Fix PostgreSQL INSERT OR syntax errors

- Convert INSERT OR IGNORE to ON CONFLICT DO NOTHING
- Convert INSERT OR REPLACE to ON CONFLICT DO UPDATE
- Add unique constraint to keyword_trends table
- Fixes DM conversation creation errors on PostgreSQL"

# Push to trigger Render auto-deployment
git push origin main
```

### Option 2: Use Deployment Script
```powershell
.\DEPLOY_NOW.ps1
```

## Verification Steps

### 1. Check Render Dashboard
- Go to https://dashboard.render.com
- Check deployment status
- Wait for "Deploy succeeded" message
- Check logs for any errors

### 2. Test DM Conversation Creation
1. Log in to https://botifex.com
2. Go to any user's profile (e.g., /profiles/27willir)
3. Click "Message" or "Open Conversation" button
4. Should successfully create/open conversation without 500 error
5. Verify you can send messages

### 3. Monitor Logs
```bash
# On Render dashboard, check logs for:
# ✅ No SQL syntax errors
# ✅ Successful DM conversation creation
# ✅ No constraint violation errors
```

### 4. Test Other Affected Features
- **User Settings**: Update any setting to verify INSERT OR REPLACE works
- **Server Tips**: Dismiss a server tip to test server_tip_dismissals
- **Analytics**: Check that keyword trends are updating correctly

## Expected Behavior After Fix

### Before Fix ❌
```
POST /api/profile/connections/27willir HTTP/1.1" 500 41
Error in ensure_dm_conversation_between: syntax error at or near "OR"
```

### After Fix ✅
```
POST /api/profile/connections/27willir HTTP/1.1" 200 1058
Conversation ready. Redirecting...
```

## Rollback Plan

If issues occur after deployment:

### Quick Rollback
```powershell
# Revert to previous commit
git revert HEAD
git push origin main
```

### Manual Fix
1. Go to Render dashboard
2. Navigate to your service
3. Click "Manual Deploy"
4. Select previous successful deployment
5. Click "Deploy"

## Database Migration

The fix includes automatic database migration:
- ✅ Unique constraint added with `IF NOT EXISTS`
- ✅ Unique index created with `IF NOT EXISTS`
- ✅ No manual SQL execution required
- ✅ Safe to run on existing data

### If Migration Issues Occur

Check for duplicate data in keyword_trends:
```sql
-- Run on PostgreSQL console in Render dashboard
SELECT keyword, date, source, user_id, COUNT(*)
FROM keyword_trends
GROUP BY keyword, date, source, user_id
HAVING COUNT(*) > 1;
```

If duplicates exist, clean them before the unique constraint is applied:
```sql
-- Remove duplicates, keeping the newest
DELETE FROM keyword_trends
WHERE id NOT IN (
    SELECT MAX(id)
    FROM keyword_trends
    GROUP BY keyword, date, source, user_id
);
```

## Monitoring After Deployment

### Key Metrics to Watch
1. **Error Rate**: Should drop to near 0 for DM-related endpoints
2. **DM Creation Success**: Should be 100%
3. **Response Time**: Should remain similar (no performance impact)
4. **Database Connection**: Should remain stable

### Check These Logs
```bash
# Look for these in Render logs:
[INFO] PostgreSQL detected - using PostgreSQL database
[INFO] Initialized PostgreSQL connection pool

# Should NOT see:
[ERROR] Error in ensure_dm_conversation_between
[ERROR] syntax error at or near "OR"
```

## Testing Checklist

- [ ] Deployment succeeded on Render
- [ ] No errors in deployment logs
- [ ] Can create new DM conversations
- [ ] Can open existing DM conversations
- [ ] Can send messages in DMs
- [ ] User settings save correctly
- [ ] Server tips can be dismissed
- [ ] No SQL syntax errors in logs
- [ ] Database connections are stable

## Support

If you encounter issues:
1. Check the Render deployment logs
2. Verify PostgreSQL connection is active
3. Check for constraint violation errors
4. Review docs/fixes/POSTGRESQL_INSERT_OR_FIX.md for details
5. Rollback if critical issues occur

## Next Steps After Successful Deployment

1. Monitor logs for 24 hours
2. Check error rates dashboard
3. Verify user reports decrease
4. Document any additional issues
5. Consider adding automated tests for PostgreSQL compatibility

## Technical Details

For more information, see:
- **Fix Documentation**: `docs/fixes/POSTGRESQL_INSERT_OR_FIX.md`
- **Modified File**: `db_enhanced.py`
- **Lines Changed**: ~85 lines added/modified
- **Breaking Changes**: None
- **Database Changes**: 1 unique constraint + 1 unique index

---

**Date**: December 11, 2025  
**Priority**: HIGH - Fixes production errors  
**Risk Level**: LOW - Backward compatible, safe rollback

