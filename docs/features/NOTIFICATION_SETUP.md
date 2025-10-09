# 🔔 Notification System Setup Guide

## Quick Start (5 minutes)

### Step 1: Install Dependencies
```bash
pip install -r requirements.txt
```
This will install Twilio for SMS support.

### Step 2: Configure Email (Required for Email Notifications)

1. Create a `.env` file from the example:
   ```bash
   copy env_example.txt .env
   ```

2. Edit `.env` and add your email settings:
   ```env
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USERNAME=your-email@gmail.com
   SMTP_PASSWORD=your-app-password
   SMTP_FROM_EMAIL=your-email@gmail.com
   SMTP_FROM_NAME=Super-Bot Alerts
   ```

   **For Gmail users:**
   - Go to https://myaccount.google.com/apppasswords
   - Generate an App Password
   - Use that password (not your regular password)

### Step 3: Configure SMS (Optional)

1. Sign up at https://www.twilio.com/try-twilio (free trial available)
2. Get your Account SID, Auth Token, and a phone number
3. Add to `.env`:
   ```env
   TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   TWILIO_AUTH_TOKEN=your_auth_token_here
   TWILIO_FROM_NUMBER=+1234567890
   ```

### Step 4: Update Database Schema

The database will automatically update when you run the app:
```bash
python app.py
```

Or manually run:
```bash
python scripts/init_db.py
```

### Step 5: Configure Notifications in Settings

1. Open Super-Bot in your browser: http://localhost:5000
2. Log in with your account
3. Go to **Settings**
4. Scroll to **Notification Preferences**
5. Enable Email and/or SMS notifications
6. For SMS: Enter your phone number in format `+1234567890`
7. Click **Save Notification Settings**

### Step 6: Test It!

1. Start a scraper from the dashboard
2. Wait for a new listing to be found
3. You should receive notifications!

## Verification

### Test Email Configuration
```bash
python -c "from notifications import test_email_configuration; print(test_email_configuration())"
```

### Test SMS Configuration
```bash
python -c "from notifications import test_sms_configuration; print(test_sms_configuration())"
```

### Check Logs
```bash
tail -f logs/superbot.log | grep notification
```

## What Happens When a Listing is Found?

1. **Scraper finds new listing** → Saves to database
2. **Database triggers notifications** → Checks all users with notifications enabled
3. **Sends notifications** → Email and/or SMS based on user preferences
4. **User receives alert** → With listing details and link

## Phone Number Format

SMS notifications require E.164 format:
- **US**: `+12345678901`
- **UK**: `+447890123456`
- **Canada**: `+12345678901`
- **Australia**: `+61412345678`

Format: `+[country code][phone number]` (no spaces, dashes, or parentheses)

## Troubleshooting

### Email Not Sending?
- Verify `.env` has correct SMTP settings
- Gmail users: Make sure you're using App Password
- Check firewall isn't blocking port 587
- Look at logs: `tail -f logs/superbot.log`

### SMS Not Sending?
- Verify Twilio credentials in `.env`
- Check Twilio account has credits
- Verify phone number is in E.164 format
- Trial accounts can only text verified numbers

### Not Receiving Notifications?
- Check Settings → Notification Preferences are enabled
- Verify scrapers are running
- Check that listings match your search criteria
- Look at logs for errors

## Database Changes

The system automatically adds these columns to the `users` table:
- `phone_number` (TEXT) - Stores user's phone for SMS
- `email_notifications` (BOOLEAN) - Email notifications on/off (default: on)
- `sms_notifications` (BOOLEAN) - SMS notifications on/off (default: off)

## Cost Considerations

### Email
- **Free** with your existing email account
- Unlimited notifications (subject to your email provider's limits)

### SMS (Twilio)
- **Free trial**: $15 credit
- **Cost**: ~$0.0075 per SMS (varies by country)
- **Example**: 100 notifications/month = ~$0.75
- Monitor usage in Twilio console

## Security Notes

✅ **DO:**
- Keep `.env` file secure (never commit to Git)
- Use App Passwords for Gmail
- Set up billing alerts in Twilio
- Use strong passwords for your accounts

❌ **DON'T:**
- Share your `.env` file
- Commit credentials to version control
- Use your main email password

## Need Help?

1. Check the full documentation: `docs/NOTIFICATION_FEATURE.md`
2. Review logs: `logs/superbot.log`
3. Test configurations using the commands above
4. Ensure all dependencies are installed

---

## Summary of Files Added/Modified

### New Files:
- ✅ `notifications.py` - Email and SMS notification system
- ✅ `docs/NOTIFICATION_FEATURE.md` - Full documentation
- ✅ `NOTIFICATION_SETUP.md` - This quick start guide

### Modified Files:
- ✅ `db_enhanced.py` - Added notification preference functions
- ✅ `db.py` - Exported new functions
- ✅ `app.py` - Added notification settings route
- ✅ `templates/settings.html` - Added notification preferences UI
- ✅ `requirements.txt` - Added Twilio dependency
- ✅ `env_example.txt` - Added email/SMS configuration

Enjoy your new notification system! 🎉

