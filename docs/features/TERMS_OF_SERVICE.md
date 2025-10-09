# Terms of Service Implementation

## Overview

This document describes the Terms of Service (ToS) implementation for Botifex, which ensures all users explicitly agree to the terms before creating an account.

## Implementation Date

**October 9, 2025**

---

## Features Implemented

### 1. Comprehensive Terms of Service Page

**File:** `templates/terms.html`

A detailed, professionally-written Terms of Service document covering:

- **Acceptance of Terms** - User agreement requirements
- **Description of Service** - What Botifex does and provides
- **Third-Party Data Disclaimer** - Clear disclaimers about data from external sources
- **User Responsibilities** - User obligations including compliance with third-party ToS
- **Limitation of Liability** - Protection for developers and operators
- **Subscription and Payments** - Billing and cancellation policies
- **Intellectual Property** - Copyright and trademark protections
- **Privacy and Data Protection** - Data handling policies
- **Termination** - Account termination conditions
- **Modifications to Terms** - Rights to update terms
- **Dispute Resolution** - Legal jurisdiction and arbitration
- **Miscellaneous** - Additional legal provisions
- **Contact Information** - Support contact details

The page features:
- Professional, modern UI matching the app's design
- Easy-to-read formatting with clear sections
- Important notices highlighted
- Navigation back to registration or home

### 2. Registration Form Update

**File:** `templates/register.html`

Enhanced registration form with:
- **Mandatory ToS Checkbox** - Users must check the box to proceed
- **Link to Full Terms** - Opens in new tab for easy review
- **Visual Error Highlighting** - Checkbox area highlights red if terms not agreed
- **Clear Labeling** - "I have read and agree to the Terms of Service"
- **Additional Footer Link** - Quick access to view full terms

Styling includes:
- Checkbox positioned for easy interaction
- Professional label styling
- Error state visual feedback
- Links styled consistently with app theme

### 3. Backend Validation

**File:** `app.py`

Registration route (`/register`) now includes:
- **Pre-submission Validation** - Checks if `agree_terms` checkbox is checked
- **Error Handling** - Returns user-friendly error message if not agreed
- **ToS Recording** - Records agreement in database upon successful registration
- **Logging** - Logs ToS agreement events for audit trail

New route added:
```python
@app.route("/terms")
def terms_of_service():
    """Display Terms of Service page"""
```

### 4. Database Schema Updates

**File:** `db_enhanced.py`

New columns added to `users` table:
- `tos_agreed` (BOOLEAN) - Whether user agreed to terms (default: 0)
- `tos_agreed_at` (DATETIME) - Timestamp of when user agreed

New database functions:

#### `record_tos_agreement(username)`
Records that a user has agreed to the Terms of Service.
- Updates `tos_agreed` to 1
- Sets `tos_agreed_at` to current timestamp
- Returns True on success, False on failure
- Logs agreement for audit purposes

#### `get_tos_agreement(username)`
Retrieves ToS agreement status for a user.
- Returns dict with `agreed` (bool) and `agreed_at` (datetime)
- Returns None if user not found
- Useful for verification and auditing

### 5. Automatic Database Migration

The implementation includes automatic migration support:
- Database schema updates run on app startup
- Existing users automatically get new columns (default: not agreed)
- No manual database migration required
- Gracefully handles existing databases

---

## User Flow

### Registration Process

1. **User visits registration page** (`/register`)
2. **Fills in username, email, password**
3. **Must check "I agree to Terms of Service"**
   - Can click link to view full terms in new tab
4. **Clicks "Register" button**
5. **Backend validation:**
   - If checkbox not checked → Error: "You must agree to the Terms of Service to create an account"
   - If all valid → User created, ToS agreement recorded
6. **Successful registration:**
   - ToS agreement timestamp saved to database
   - User redirected to login page
   - Email verification sent (if configured)

### Viewing Terms

Users can view Terms of Service at any time:
- From registration page footer
- From login page footer
- Direct URL: `/terms`
- When viewing from registration, back button returns to registration

---

## Legal Protections

### Third-Party Data Disclaimer

The ToS explicitly states:

> "This tool accesses and displays information from third-party websites solely for the convenience of its users. The operators of this application make no claim of ownership over such data and provide no guarantee of availability or accuracy."

### User Responsibilities

Users explicitly agree to:
- Comply with third-party website terms of service
- Not misuse the service
- Verify information before making decisions
- Maintain account security

### Liability Limitations

The ToS includes:
- "As is" and "as available" disclaimers
- No warranties on data accuracy
- Maximum liability caps
- Indemnification clauses
- Force majeure protections

### Enforceability

- Binding arbitration clause
- Governing law specification
- Severability provisions
- Right to modify terms with notice

---

## Technical Details

### Database Schema

```sql
ALTER TABLE users ADD COLUMN tos_agreed BOOLEAN DEFAULT 0;
ALTER TABLE users ADD COLUMN tos_agreed_at DATETIME;
```

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/terms` | GET | Display Terms of Service page |
| `/register` | POST | Validates ToS agreement on registration |

### Form Validation

Server-side validation ensures:
- Checkbox must be checked (HTML5 `required` attribute)
- Backend double-checks before user creation
- Clear error messages if validation fails
- Error field highlighting for UX

### Security Considerations

- CSRF token protection on registration form
- Rate limiting on registration endpoint (3 requests/60 minutes)
- SQL injection protection via parameterized queries
- XSS protection via template escaping
- Audit trail via logging

---

## Compliance Features

### Audit Trail

Every ToS agreement is logged with:
- Username
- Agreement timestamp
- IP address (via Flask request logging)
- Action type (info level logging)

### Data Retention

ToS agreement data stored includes:
- Boolean flag (agreed/not agreed)
- Exact timestamp of agreement
- Persistent storage in SQLite database
- Survives app restarts

### Future Updates

When terms are updated:
1. Update `templates/terms.html` with new content
2. Update "Last Updated" date at top of terms page
3. Optionally: Implement re-acceptance requirement
4. Notify users via email/in-app notification

---

## Testing Recommendations

### Manual Testing

1. **Test Registration Without Agreement**
   - Go to `/register`
   - Fill in username, email, password
   - Leave checkbox unchecked
   - Click Register
   - Verify error message appears

2. **Test Registration With Agreement**
   - Go to `/register`
   - Fill in all fields
   - Check ToS checkbox
   - Click Register
   - Verify successful registration

3. **Test Terms Page**
   - Visit `/terms` directly
   - Verify full terms display correctly
   - Test navigation links
   - Test responsive design

4. **Test Database Recording**
   - Register new user
   - Check database: `SELECT tos_agreed, tos_agreed_at FROM users WHERE username='testuser'`
   - Verify `tos_agreed = 1` and timestamp is set

### Automated Testing

Consider adding tests for:
```python
def test_registration_without_tos():
    """Test that registration fails without ToS agreement"""
    # POST to /register without agree_terms
    # Assert error message returned
    # Assert user not created

def test_registration_with_tos():
    """Test successful registration with ToS agreement"""
    # POST to /register with agree_terms=on
    # Assert success message
    # Assert user created in database
    # Assert tos_agreed=1 and tos_agreed_at is set

def test_tos_page_loads():
    """Test that ToS page loads successfully"""
    # GET /terms
    # Assert 200 status
    # Assert page contains key terms
```

---

## Maintenance

### Updating Terms

To update the Terms of Service:

1. **Edit the terms page:**
   ```bash
   # Edit templates/terms.html
   # Update content in each section as needed
   # Update "Last Updated" date
   ```

2. **Consider re-acceptance:**
   - For major changes, may require existing users to re-accept
   - Implement check: `if user.tos_agreed_at < TERMS_UPDATE_DATE`
   - Prompt user to review and re-accept updated terms

3. **Notify users:**
   - Send email to all active users
   - Show in-app notification
   - Log terms update event

### Adding New Sections

To add new sections to the ToS:

1. Add new `<div class="section">` in `templates/terms.html`
2. Follow existing formatting structure
3. Use `<h2>` for main sections, `<h3>` for subsections
4. Test responsive display
5. Update "Last Updated" date

---

## Files Modified

### New Files
- `templates/terms.html` - Terms of Service page

### Modified Files
- `templates/register.html` - Added ToS checkbox
- `templates/login.html` - Added ToS link in footer
- `app.py` - Added validation and `/terms` route
- `db_enhanced.py` - Added database columns and functions

---

## Summary

The Terms of Service implementation provides:

✅ **Legal Protection** - Comprehensive terms covering all service aspects  
✅ **User Agreement** - Mandatory checkbox on registration  
✅ **Database Tracking** - Records who agreed and when  
✅ **Professional UI** - Modern, readable terms page  
✅ **Easy Access** - Links throughout the app  
✅ **Audit Trail** - Logging of all agreements  
✅ **Compliance Ready** - Meets standard legal requirements  
✅ **Future-Proof** - Easy to update as needed  

The implementation is production-ready and provides strong legal foundation for operating the service.

---

## Contact

For questions about ToS implementation or to suggest improvements, please refer to the project documentation or contact the development team.

**Last Updated:** October 9, 2025

