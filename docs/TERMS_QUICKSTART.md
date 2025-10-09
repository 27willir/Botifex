# Terms of Service - Quick Start Guide

## What Was Added

Users must now agree to comprehensive Terms of Service when creating an account.

---

## User Experience

### Registration Flow

1. Navigate to registration page
2. Enter username, email, and password
3. **NEW:** Check "I agree to Terms of Service" checkbox
4. Click Register

If checkbox is not checked:
- ❌ Error message: "You must agree to the Terms of Service to create an account"
- Red highlighting around checkbox area

### Viewing Terms

Users can view full Terms of Service:
- **From registration page:** Click "Terms of Service" link in checkbox text or footer
- **From login page:** Click "Terms of Service" link in footer
- **Direct URL:** Navigate to `/terms`

---

## What's Covered in the Terms

The Terms of Service include:

1. **Data Disclaimer** - Your provided text about third-party data
2. **No Warranties** - "As is" service provision
3. **User Responsibilities** - Must comply with third-party ToS
4. **Liability Limitations** - Developer protections
5. **Subscription Terms** - Billing and cancellation policies
6. **Privacy** - Data handling policies
7. **Termination** - Account suspension/deletion conditions
8. **Legal** - Governing law, arbitration, jurisdiction

### Key Disclaimers

✅ No guarantee of data accuracy or availability  
✅ Users responsible for complying with third-party ToS  
✅ Developers not liable for misuse or violations  
✅ All data "as is" without warranties  

---

## For Administrators

### Database Changes

New columns automatically added to `users` table:
- `tos_agreed` - Boolean flag (1 = agreed, 0 = not agreed)
- `tos_agreed_at` - Timestamp of agreement

### Checking User Agreement

```python
# Get ToS agreement status for a user
from db_enhanced import get_tos_agreement

result = get_tos_agreement('username')
if result and result['agreed']:
    print(f"User agreed on: {result['agreed_at']}")
```

### Database Query

```sql
-- View all users and their ToS agreement status
SELECT username, tos_agreed, tos_agreed_at, created_at 
FROM users 
ORDER BY created_at DESC;
```

### Audit Trail

All ToS agreements are logged:
```
INFO: ToS agreement recorded for user: username
```

Check logs at: `logs/superbot.log`

---

## Testing the Feature

### Test 1: Registration Without Agreement

```
1. Go to http://localhost:5000/register
2. Fill in username, email, password
3. DO NOT check the ToS checkbox
4. Click Register
5. Expected: Error message displayed
```

### Test 2: Registration With Agreement

```
1. Go to http://localhost:5000/register
2. Fill in username, email, password  
3. CHECK the ToS checkbox
4. Click Register
5. Expected: Success, redirect to login
```

### Test 3: View Terms

```
1. Go to http://localhost:5000/terms
2. Expected: Full terms page displays
3. Verify all sections are readable
4. Test "Back to Registration" link
```

### Test 4: Database Verification

```bash
# Connect to database
sqlite3 superbot.db

# Check ToS agreement was recorded
SELECT username, tos_agreed, tos_agreed_at 
FROM users 
WHERE username = 'your_test_user';

# Expected: tos_agreed = 1, tos_agreed_at = recent timestamp
```

---

## Updating the Terms

When you need to update the Terms of Service:

1. **Edit the file:**
   ```bash
   # Open templates/terms.html
   # Modify any sections as needed
   ```

2. **Update the date:**
   ```html
   <div class="last-updated">Last Updated: [NEW DATE]</div>
   ```

3. **Restart the app:**
   ```bash
   # The changes take effect immediately
   # No database migration needed for content changes
   ```

4. **Notify users (recommended):**
   - Send email to all users about updated terms
   - Consider requiring re-acceptance for major changes

---

## Customization

### Shortening the Terms

If you want shorter terms, edit `templates/terms.html`:
- Remove entire sections: Delete `<div class="section">...</div>`
- Shorten content: Edit paragraph text
- Keep core sections: Description, Disclaimer, User Responsibilities, Liability

### Styling Changes

Modify the `<style>` section in `templates/terms.html`:
```css
/* Change colors */
h1, h2 { color: #YOUR_COLOR; }

/* Change width */
.container { max-width: YOUR_WIDTH; }

/* Change background */
body { background: YOUR_GRADIENT; }
```

### Adding New Sections

Add at the end before "Contact Information":
```html
<div class="section">
    <h2>X. Your New Section</h2>
    <p>Your content here...</p>
</div>
```

---

## Troubleshooting

### Issue: Checkbox doesn't show

**Solution:** Clear browser cache and refresh page

### Issue: Error even when checkbox is checked

**Solution:**
1. Check browser console for JavaScript errors
2. Verify CSRF token is being sent
3. Check Flask logs for backend errors

### Issue: Database error on registration

**Solution:**
```bash
# Run database initialization to add columns
python scripts/init_db.py
```

### Issue: Terms page shows 404

**Solution:**
1. Verify `app.py` includes the `/terms` route
2. Restart Flask application
3. Check Flask logs for routing errors

---

## Security Notes

✅ **CSRF Protection** - All forms include CSRF tokens  
✅ **Rate Limiting** - Registration limited to 3 attempts per hour  
✅ **SQL Injection Protected** - Parameterized queries used  
✅ **XSS Protected** - Template escaping enabled  
✅ **Audit Logging** - All agreements logged with timestamps  

---

## Migration Notes

### Existing Users

Existing users (created before ToS implementation) will have:
- `tos_agreed = 0` (not agreed)
- `tos_agreed_at = NULL`

**Options:**
1. **Grandfather existing users** - Assume they agreed, update database:
   ```sql
   UPDATE users 
   SET tos_agreed = 1, tos_agreed_at = CURRENT_TIMESTAMP 
   WHERE tos_agreed = 0;
   ```

2. **Require re-acceptance** - Prompt on next login:
   ```python
   # Add check in login route
   if not user.tos_agreed:
       redirect to terms acceptance page
   ```

3. **Optional re-acceptance** - Show banner suggesting review

---

## Production Checklist

Before deploying to production:

- [ ] Review all terms for accuracy
- [ ] Update "Last Updated" date to deployment date
- [ ] Add contact information in Contact section
- [ ] Specify correct jurisdiction in Dispute Resolution
- [ ] Test registration flow on staging
- [ ] Verify database columns created
- [ ] Test ToS page on mobile devices
- [ ] Check all links work correctly
- [ ] Enable audit logging
- [ ] Plan for existing user migration
- [ ] Prepare user notification email
- [ ] Document terms in company records
- [ ] Consider legal review (recommended)

---

## Quick Commands

```bash
# View recent registrations and ToS agreements
sqlite3 superbot.db "SELECT username, tos_agreed, tos_agreed_at FROM users ORDER BY created_at DESC LIMIT 10;"

# Count users who agreed to ToS
sqlite3 superbot.db "SELECT COUNT(*) FROM users WHERE tos_agreed = 1;"

# Find users who haven't agreed (existing users)
sqlite3 superbot.db "SELECT username FROM users WHERE tos_agreed = 0;"

# View ToS agreement logs
tail -f logs/superbot.log | grep "ToS agreement"
```

---

## Summary

✨ **Complete** - Full ToS implementation ready  
✨ **Enforced** - Checkbox required for registration  
✨ **Tracked** - Database records all agreements  
✨ **Accessible** - Terms viewable anytime  
✨ **Professional** - Comprehensive legal protection  

Users will now be properly informed and agree to terms before using the service.

---

**Last Updated:** October 9, 2025

