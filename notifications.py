# notifications.py - Email and SMS notification system
import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from utils import logger
from error_handling import log_errors
from dotenv import load_dotenv

load_dotenv()

# Email configuration from environment variables
SMTP_HOST = os.getenv('SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
SMTP_USERNAME = os.getenv('SMTP_USERNAME', '')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '')
SMTP_FROM_EMAIL = os.getenv('SMTP_FROM_EMAIL', SMTP_USERNAME)
SMTP_FROM_NAME = os.getenv('SMTP_FROM_NAME', 'Super-Bot Alerts')

# SMS configuration (Twilio)
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID', '')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN', '')
TWILIO_FROM_NUMBER = os.getenv('TWILIO_FROM_NUMBER', '')

# Try to import Twilio (optional dependency)
try:
    from twilio.rest import Client
    TWILIO_AVAILABLE = True
except ImportError:
    TWILIO_AVAILABLE = False
    logger.warning("Twilio not installed. SMS notifications will be disabled. Install with: pip install twilio")


@log_errors()
def send_email_notification(to_email, subject, message_body, listing_url=None):
    """
    Send email notification to user
    
    Args:
        to_email: Recipient email address
        subject: Email subject
        message_body: Email body (plain text)
        listing_url: Optional listing URL to include
    
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    if not SMTP_USERNAME or not SMTP_PASSWORD:
        logger.warning("Email credentials not configured. Skipping email notification.")
        return False
    
    try:
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
        msg['To'] = to_email
        
        # Create plain text version
        text_content = message_body
        if listing_url:
            text_content += f"\n\nView listing: {listing_url}"
        
        # Create HTML version (more attractive)
        html_content = f"""
        <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                    .header {{ background-color: #4CAF50; color: white; padding: 20px; text-align: center; border-radius: 5px 5px 0 0; }}
                    .content {{ background-color: #f9f9f9; padding: 20px; border: 1px solid #ddd; }}
                    .listing-details {{ background-color: white; padding: 15px; margin: 15px 0; border-left: 4px solid #4CAF50; }}
                    .button {{ display: inline-block; background-color: #4CAF50; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; margin: 15px 0; }}
                    .footer {{ text-align: center; color: #888; font-size: 12px; padding: 15px; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>🔔 New Listing Found!</h1>
                    </div>
                    <div class="content">
                        <div class="listing-details">
                            {message_body.replace(chr(10), '<br>')}
                        </div>
                        {f'<a href="{listing_url}" class="button">View Listing</a>' if listing_url else ''}
                    </div>
                    <div class="footer">
                        <p>You're receiving this because you enabled email notifications in Super-Bot.</p>
                        <p>To manage your notification preferences, log in to your Super-Bot dashboard.</p>
                    </div>
                </div>
            </body>
        </html>
        """
        
        # Attach both versions
        part1 = MIMEText(text_content, 'plain')
        part2 = MIMEText(html_content, 'html')
        msg.attach(part1)
        msg.attach(part2)
        
        # Send email
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
        
        logger.info(f"✅ Email notification sent to {to_email}")
        return True
        
    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"❌ Email authentication failed: {e}")
        return False
    except smtplib.SMTPException as e:
        logger.error(f"❌ SMTP error sending email to {to_email}: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Failed to send email notification to {to_email}: {e}")
        return False


@log_errors()
def send_sms_notification(to_phone, message):
    """
    Send SMS notification using Twilio
    
    Args:
        to_phone: Recipient phone number (E.164 format, e.g., +1234567890)
        message: SMS message content (max 160 chars recommended)
    
    Returns:
        bool: True if SMS sent successfully, False otherwise
    """
    if not TWILIO_AVAILABLE:
        logger.warning("Twilio library not available. Cannot send SMS notifications.")
        return False
    
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN or not TWILIO_FROM_NUMBER:
        logger.warning("Twilio credentials not configured. Skipping SMS notification.")
        return False
    
    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        
        # Truncate message if too long (SMS limit is typically 160 chars)
        if len(message) > 160:
            message = message[:157] + "..."
        
        # Send SMS
        sms = client.messages.create(
            body=message,
            from_=TWILIO_FROM_NUMBER,
            to=to_phone
        )
        
        logger.info(f"✅ SMS notification sent to {to_phone} (SID: {sms.sid})")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to send SMS notification to {to_phone}: {e}")
        return False


@log_errors()
def notify_new_listing(user_email, user_phone, email_enabled, sms_enabled, listing_title, listing_price, listing_url, listing_source):
    """
    Send notifications about a new listing to a user based on their preferences
    
    Args:
        user_email: User's email address
        user_phone: User's phone number (E.164 format)
        email_enabled: Whether user has email notifications enabled
        sms_enabled: Whether user has SMS notifications enabled
        listing_title: Title of the listing
        listing_price: Price of the listing
        listing_url: URL to the listing
        listing_source: Source of the listing (craigslist, facebook, ksl)
    
    Returns:
        dict: Status of notifications sent {'email': bool, 'sms': bool}
    """
    results = {'email': False, 'sms': False}
    
    # Format price
    price_str = f"${listing_price:,}" if listing_price else "Price not listed"
    
    # Send email notification if enabled
    if email_enabled and user_email:
        email_subject = f"🔔 New Listing: {listing_title}"
        email_body = f"""
A new listing matching your search criteria has been found!

Title: {listing_title}
Price: {price_str}
Source: {listing_source.upper()}

This listing was just posted and matches your saved preferences.
        """.strip()
        
        results['email'] = send_email_notification(
            to_email=user_email,
            subject=email_subject,
            message_body=email_body,
            listing_url=listing_url
        )
    
    # Send SMS notification if enabled
    if sms_enabled and user_phone:
        # Keep SMS short and concise
        sms_message = f"New {listing_source.upper()}: {listing_title} - {price_str}. {listing_url}"
        results['sms'] = send_sms_notification(
            to_phone=user_phone,
            message=sms_message
        )
    
    return results


def test_email_configuration():
    """
    Test if email configuration is properly set up
    
    Returns:
        tuple: (bool, str) - (is_configured, message)
    """
    if not SMTP_USERNAME or not SMTP_PASSWORD:
        return False, "Email credentials not configured. Please set SMTP_USERNAME and SMTP_PASSWORD in .env file."
    
    return True, "Email configuration looks good!"


def test_sms_configuration():
    """
    Test if SMS configuration is properly set up
    
    Returns:
        tuple: (bool, str) - (is_configured, message)
    """
    if not TWILIO_AVAILABLE:
        return False, "Twilio library not installed. Install with: pip install twilio"
    
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN or not TWILIO_FROM_NUMBER:
        return False, "Twilio credentials not configured. Please set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and TWILIO_FROM_NUMBER in .env file."
    
    return True, "SMS configuration looks good!"


# Export configuration check functions
__all__ = [
    'send_email_notification',
    'send_sms_notification',
    'notify_new_listing',
    'test_email_configuration',
    'test_sms_configuration',
]

