# Email and SMS Notifications Feature

## Overview
Super-Bot now supports **instant email and SMS notifications** when new listings matching your search criteria are found! Get alerted immediately so you never miss a great deal.

## Features

### ✉️ Email Notifications
- **Instant alerts** when new listings are discovered
- **Beautiful HTML emails** with listing details
- **Configurable per user** - enable/disable at any time
- **Automatic delivery** using your configured SMTP server

### 📱 SMS Notifications
- **Text message alerts** for mobile convenience
- **Concise messages** optimized for mobile devices
- **Powered by Twilio** for reliable delivery
- **Optional feature** - works independently of email

## Quick Setup

### For Users

1. **Navigate to Settings**
   - Log into Super-Bot
   - Click on "Settings" in the sidebar
   - Scroll down to "Notification Preferences"

2. **Configure Email Notifications**
   - Check "Email Notifications" to enable
   - Email alerts will be sent to your registered email address
   - No additional setup required!

3. **Configure SMS Notifications** (Optional)
   - Check "SMS Notifications" to enable
   - Enter your phone number in E.164 format (e.g., `+1234567890`)
   - Format: `+[country code][phone number]`
   - Examples:
     - US: `+12345678901`
     - UK: `+447890123456`
     - Australia: `+61412345678`

4. **Save Your Preferences**
   - Click "Save Notification Settings"
   - You'll receive a confirmation message

## Administrator Setup

### Email Configuration (Required for Email Notifications)

1. **Copy the environment file**
   ```bash
   copy env_example.txt .env
   ```

2. **Configure SMTP settings in `.env`**

   For Gmail:
   ```env
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USERNAME=your-email@gmail.com
   SMTP_PASSWORD=your-app-password
   SMTP_FROM_EMAIL=your-email@gmail.com
   SMTP_FROM_NAME=Super-Bot Alerts
   ```

   **Important for Gmail users:**
   - You must use an **App Password**, not your regular password
   - Generate one at: https://support.google.com/accounts/answer/185833
   - Enable 2-factor authentication first if required

   For other email providers:
   - Outlook: `smtp.office365.com` (port 587)
   - Yahoo: `smtp.mail.yahoo.com` (port 587)
   - Custom SMTP: Use your provider's settings

3. **Test email configuration**
   ```bash
   python -c "from notifications import test_email_configuration; print(test_email_configuration())"
   ```

### SMS Configuration (Optional)

1. **Sign up for Twilio**
   - Create account at: https://www.twilio.com/try-twilio
   - Get a phone number (free trial available)
   - Find your credentials in the Twilio Console

2. **Configure Twilio settings in `.env`**
   ```env
   TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   TWILIO_AUTH_TOKEN=your_auth_token_here
   TWILIO_FROM_NUMBER=+1234567890
   ```

3. **Install Twilio dependency**
   ```bash
   pip install twilio
   ```
   (Already included in requirements.txt)

4. **Test SMS configuration**
   ```bash
   python -c "from notifications import test_sms_configuration; print(test_sms_configuration())"
   ```

## How It Works

### Notification Flow

1. **Scraper finds new listing**
   - Scrapers (Facebook, Craigslist, KSL) run continuously
   - When a new listing matching your criteria is found
   - It's saved to the database

2. **Notification triggered**
   - System checks for users with notifications enabled
   - Creates personalized notification for each user
   - Sends via configured channels (email and/or SMS)

3. **User receives alert**
   - Email arrives with full listing details
   - SMS arrives with concise listing summary
   - Both include direct link to the listing

### Database Schema

New columns added to `users` table:
```sql
phone_number TEXT                -- User's phone number (E.164 format)
email_notifications BOOLEAN      -- Email notifications enabled (default: 1)
sms_notifications BOOLEAN        -- SMS notifications enabled (default: 0)
```

### API Functions

New functions in `db_enhanced.py`:
- `get_notification_preferences(username)` - Get user's notification settings
- `update_notification_preferences(username, ...)` - Update notification settings
- `get_users_with_notifications_enabled()` - Get all users with notifications on

New module `notifications.py`:
- `send_email_notification(...)` - Send email alert
- `send_sms_notification(...)` - Send SMS alert
- `notify_new_listing(...)` - Send notifications for a new listing

## Email Template

Users receive a beautifully formatted HTML email with:
- **Header**: "🔔 New Listing Found!"
- **Listing Details**: Title, price, source
- **Call to Action**: "View Listing" button
- **Footer**: Instructions to manage preferences

Plain text version is also included for compatibility.

## SMS Template

SMS messages are concise for mobile:
```
New CRAIGSLIST: 1969 Firebird - $15,000. https://...
```

## Troubleshooting

### Email not working?

1. **Check SMTP credentials**
   ```bash
   python -c "from notifications import test_email_configuration; print(test_email_configuration())"
   ```

2. **Common issues:**
   - Gmail: Make sure you're using an App Password, not your regular password
   - Gmail: Enable "Less secure app access" if using old method (not recommended)
   - Firewall: Ensure port 587 is not blocked
   - Credentials: Double-check username and password in `.env`

3. **Check logs**
   ```bash
   tail -f logs/superbot.log
   ```
   Look for lines containing "Email notification"

### SMS not working?

1. **Check Twilio configuration**
   ```bash
   python -c "from notifications import test_sms_configuration; print(test_sms_configuration())"
   ```

2. **Common issues:**
   - Twilio: Verify your account is active
   - Credits: Check if you have Twilio credits
   - Phone number: Ensure it's in E.164 format (+1234567890)
   - Trial account: Can only send to verified numbers

3. **Verify phone number format**
   - Must start with `+`
   - Include country code
   - No spaces, dashes, or parentheses
   - Example: `+12345678901` (not `(234) 567-8901`)

### Notifications not triggering?

1. **Check if notifications are enabled**
   - Go to Settings → Notification Preferences
   - Verify checkboxes are checked

2. **Test with a scraper**
   - Start a scraper from the dashboard
   - Wait for it to find a listing
   - Check if notification is sent

3. **Check logs**
   ```bash
   tail -f logs/superbot.log | grep -i notification
   ```

## Security Considerations

1. **Email credentials**
   - Never commit `.env` file to version control
   - Use App Passwords for Gmail (more secure)
   - Rotate credentials regularly

2. **SMS costs**
   - Twilio charges per SMS
   - Monitor usage to avoid unexpected bills
   - Set up billing alerts in Twilio console

3. **Phone number privacy**
   - Phone numbers are stored securely in database
   - Only visible to administrators
   - Encrypted connection recommended for production

## Feature Limitations

1. **Email**
   - Depends on SMTP server availability
   - May be delayed by email provider
   - Could end up in spam folder (configure SPF/DKIM)

2. **SMS**
   - Requires Twilio account (costs money)
   - Limited to 160 characters
   - Trial accounts have restrictions

3. **Rate Limiting**
   - One notification per new listing
   - No duplicate notifications for same listing
   - Settings updates are rate-limited

## Future Enhancements

Potential improvements for future versions:
- [ ] Notification history/log
- [ ] Custom notification templates
- [ ] Notification scheduling (quiet hours)
- [ ] Digest mode (batch notifications)
- [ ] Push notifications (mobile app)
- [ ] Webhook support
- [ ] Discord/Slack integration
- [ ] Keyword-specific notifications
- [ ] Price alert thresholds

## Support

For issues or questions:
1. Check logs: `logs/superbot.log`
2. Review this documentation
3. Check `.env` configuration
4. Test notification services
5. Contact system administrator

## Credits

- Email: Python `smtplib` (built-in)
- SMS: [Twilio API](https://www.twilio.com/)
- HTML Email Templates: Custom design

