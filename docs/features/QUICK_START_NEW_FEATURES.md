# 🚀 Quick Start - New Features
## Get Started in 5 Minutes!

---

## ✨ WHAT'S NEW

Your Super-Bot now has **5 powerful new features**:

1. ⭐ **Favorites** - Bookmark listings
2. 💾 **Saved Searches** - Save & reuse searches
3. 🚨 **Price Alerts** - Get notified when prices match
4. ✉️ **Email Verification** - Professional onboarding
5. 🔑 **Password Reset** - Self-service password recovery

---

## 🎯 STEP 1: Restart Your App

```bash
python app.py
```

**That's it!** Database tables auto-create on startup.

---

## 🎯 STEP 2: Configure Email (Optional)

Add to your `.env` file:

```bash
# Email Configuration (for verification & password reset)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your-email@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_FROM_EMAIL=your-email@gmail.com
SMTP_FROM_NAME=Super-Bot
```

**Gmail Setup:**
1. Enable 2FA: https://myaccount.google.com/security
2. Create App Password: https://myaccount.google.com/apppasswords
3. Use App Password as `SMTP_PASSWORD`

**Skip this if you don't want email features** - everything else works fine!

---

## 🎯 STEP 3: Try It Out!

### Test Favorites
```bash
curl -X POST http://localhost:5000/api/favorites/1 \
  -H "Content-Type: application/json" \
  -d '{"notes": "Great deal!"}'
```

### Test Saved Searches
```bash
curl -X POST http://localhost:5000/api/saved-searches \
  -H "Content-Type: application/json" \
  -d '{"name": "My Search", "keywords": "Corvette"}'
```

### Test Price Alerts
```bash
curl -X POST http://localhost:5000/api/price-alerts \
  -H "Content-Type: application/json" \
  -d '{"keywords": "Firebird", "threshold_price": 15000, "alert_type": "under"}'
```

### Test Password Reset
Visit: `http://localhost:5000/forgot-password`

---

## 📖 HOW TO USE

### ⭐ FAVORITES

**Add to Favorites:**
- API: `POST /api/favorites/<listing_id>`
- With notes: `{"notes": "Check this out!"}`

**View Favorites:**
- Page: http://localhost:5000/favorites
- API: `GET /api/favorites`

**Remove:**
- API: `DELETE /api/favorites/<listing_id>`

---

### 💾 SAVED SEARCHES

**Create:**
```json
POST /api/saved-searches
{
  "name": "Dream Cars",
  "keywords": "Corvette,Firebird",
  "min_price": 10000,
  "max_price": 30000,
  "notify_new": true
}
```

**Get All:**
```bash
GET /api/saved-searches
```

**Delete:**
```bash
DELETE /api/saved-searches/<id>
```

---

### 🚨 PRICE ALERTS

**Create Alert:**
```json
POST /api/price-alerts
{
  "keywords": "Corvette Z06",
  "threshold_price": 25000,
  "alert_type": "under"
}
```

**Toggle On/Off:**
```bash
POST /api/price-alerts/<id>/toggle
```

---

### ✉️ EMAIL VERIFICATION

**Automatic on Registration:**
- New users get verification email
- Click link to verify

**Resend:**
- Form on login page
- Or: `POST /resend-verification`

---

### 🔑 PASSWORD RESET

**User Flow:**
1. Visit: http://localhost:5000/forgot-password
2. Enter email
3. Click link in email
4. Enter new password

---

## 📊 FEATURES AT A GLANCE

| Feature | Endpoint | What It Does |
|---------|----------|--------------|
| Add Favorite | `POST /api/favorites/<id>` | Bookmark a listing |
| Get Favorites | `GET /api/favorites` | View all bookmarks |
| Save Search | `POST /api/saved-searches` | Save search criteria |
| Create Alert | `POST /api/price-alerts` | Monitor prices |
| Verify Email | `GET /verify-email?token=...` | Confirm email |
| Reset Password | `GET /reset-password?token=...` | New password |

---

## 🎨 FRONTEND INTEGRATION

### Add Favorite Button (JavaScript):
```javascript
async function toggleFavorite(listingId) {
    const response = await fetch(`/api/favorites/${listingId}/check`);
    const data = await response.json();
    
    if (data.favorited) {
        // Remove
        await fetch(`/api/favorites/${listingId}`, {method: 'DELETE'});
    } else {
        // Add
        await fetch(`/api/favorites/${listingId}`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({notes: ''})
        });
    }
}
```

### Save Search Button:
```javascript
async function saveSearch() {
    const data = {
        name: document.getElementById('search-name').value,
        keywords: document.getElementById('keywords').value,
        min_price: document.getElementById('min-price').value,
        max_price: document.getElementById('max-price').value,
        notify_new: true
    };
    
    await fetch('/api/saved-searches', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data)
    });
}
```

---

## 🐛 TROUBLESHOOTING

### Issue: Email not sending
**Solution:** Check SMTP configuration in `.env`

### Issue: "Table doesn't exist"
**Solution:** Restart app - tables auto-create

### Issue: 401 Unauthorized on API calls
**Solution:** Log in first, then make API calls

### Issue: CSRF token error
**Solution:** Use same session that logged in

---

## 📚 FULL DOCUMENTATION

- **Complete API Reference:** `API_DOCUMENTATION.md`
- **Implementation Details:** `FEATURES_IMPLEMENTED.md`
- **Bug Fixes Applied:** `BUGS_FIXED_SUMMARY.md`

---

## 🎉 YOU'RE READY!

Your Super-Bot now has **enterprise-level features**:
- ✅ User retention (favorites)
- ✅ Power user tools (saved searches)
- ✅ Automation (price alerts)
- ✅ Professional onboarding (email verification)
- ✅ Self-service (password reset)

**Start using them now!** 🚀

---

*Quick Start Guide - Super-Bot v2.0*  
*Need help? Check the full documentation!*

