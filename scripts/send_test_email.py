#!/usr/bin/env python3
"""
Send a test email to verify end-to-end functionality
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from notifications import send_email_notification
from email_verification import is_email_configured, SMTP_USERNAME

if not is_email_configured():
    print("\n❌ Email not configured. Please set SMTP credentials in .env file.\n")
    sys.exit(1)

print("\n" + "="*70)
print("  SEND TEST EMAIL")
print("="*70 + "\n")

print(f"📧 Sending test email from: {SMTP_USERNAME}\n")

# Send to the configured email address (yourself)
recipient = SMTP_USERNAME

print(f"Recipient: {recipient}")
print("Subject: 🧪 Super-Bot Email System Test")
print("\nSending...")

try:
    success = send_email_notification(
        to_email=recipient,
        subject="🧪 Super-Bot Email System Test",
        message_body="""
This is a test email to verify your Super-Bot email system is working correctly!

✅ SMTP Connection: Working
✅ Authentication: Successful  
✅ Email Delivery: Working

All email features are operational:
• Email verification for new users
• Password reset emails
• Listing notification emails

If you received this email, your system is ready to go!
        """.strip(),
        listing_url="https://github.com/yourusername/super-bot"
    )
    
    if success:
        print("\n✅ TEST EMAIL SENT SUCCESSFULLY!\n")
        print(f"📬 Check your inbox: {recipient}")
        print("   (Also check spam folder if you don't see it)\n")
        print("="*70 + "\n")
        sys.exit(0)
    else:
        print("\n❌ Failed to send test email. Check logs for details.\n")
        sys.exit(1)
        
except Exception as e:
    print(f"\n❌ Error: {e}\n")
    sys.exit(1)

