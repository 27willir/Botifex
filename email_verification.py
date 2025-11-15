"""
Email Verification System for Super-Bot
Handles email verification tokens and verification process
"""

import html
import secrets
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from dotenv import load_dotenv

from email_utils import (
    EmailConfigurationError,
    SMTP_FROM_EMAIL,
    SMTP_FROM_NAME,
    SMTP_HOST,
    SMTP_PORT,
    SMTP_PASSWORD,
    SMTP_USERNAME,
    is_email_configured,
    smtp_connection,
)
from error_handling import log_errors
from utils import logger

load_dotenv()

# Token expiration (24 hours)
TOKEN_EXPIRATION_HOURS = 24


def generate_verification_token():
    """Generate a secure verification token"""
    return secrets.token_urlsafe(32)


def generate_password_reset_token():
    """Generate a secure password reset token"""
    return secrets.token_urlsafe(32)


@log_errors()
def send_verification_email(to_email, username, token, base_url):
    """
    Send email verification link to user
    
    Args:
        to_email: User's email address
        username: Username
        token: Verification token
        base_url: Base URL of the application
    
    Returns:
        bool: True if email sent successfully
    """
    if not is_email_configured():
        logger.warning("Email credentials not configured. Verification email not sent.")
        return False
    
    try:
        verification_link = f"{base_url}/verify-email?token={token}"
        safe_verification_link = html.escape(verification_link, quote=True)
        
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = 'Verify Your Super-Bot Account'
        msg['From'] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
        msg['To'] = to_email
        
        # Plain text version
        text_content = f"""
Welcome to Super-Bot, {username}!

Please verify your email address by clicking the link below:

{verification_link}

This link will expire in {TOKEN_EXPIRATION_HOURS} hours.

If you didn't create an account, please ignore this email.

Best regards,
The Super-Bot Team
        """.strip()
        
        # HTML version
        html_content = f"""
        <html>
            <head>
                <style>
                    body {{ 
                        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
                        line-height: 1.6; 
                        color: #333;
                        max-width: 600px;
                        margin: 0 auto;
                    }}
                    .container {{ 
                        background-color: #f9f9f9; 
                        padding: 40px 30px; 
                        border-radius: 10px;
                        margin: 20px 0;
                    }}
                    .header {{ 
                        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                        color: white; 
                        padding: 30px; 
                        text-align: center; 
                        border-radius: 10px 10px 0 0;
                        margin: -40px -30px 30px -30px;
                    }}
                    .header h1 {{
                        margin: 0;
                        font-size: 28px;
                    }}
                    .content {{ 
                        background-color: white; 
                        padding: 30px; 
                        border-radius: 8px;
                        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                    }}
                    .button {{ 
                        display: inline-block; 
                        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                        color: white !important; 
                        padding: 16px 32px; 
                        text-decoration: none; 
                        border-radius: 8px; 
                        margin: 25px 0;
                        font-weight: 600;
                        font-size: 16px;
                        box-shadow: 0 4px 6px rgba(102, 126, 234, 0.3);
                        transition: all 0.3s ease;
                    }}
                    .button:hover {{
                        transform: translateY(-2px);
                        box-shadow: 0 6px 12px rgba(102, 126, 234, 0.4);
                    }}
                    .welcome {{
                        font-size: 18px;
                        color: #555;
                        margin-bottom: 20px;
                    }}
                    .info-box {{
                        background-color: #f0f4ff;
                        border-left: 4px solid #667eea;
                        padding: 15px;
                        margin: 20px 0;
                        border-radius: 4px;
                    }}
                    .footer {{ 
                        text-align: center; 
                        color: #888; 
                        font-size: 14px; 
                        padding: 20px 0;
                        margin-top: 30px;
                        border-top: 1px solid #e0e0e0;
                    }}
                    .footer a {{
                        color: #667eea;
                        text-decoration: none;
                    }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>🚀 Welcome to Super-Bot!</h1>
                    </div>
                    <div class="content">
                        <p class="welcome">Hi <strong>{username}</strong>,</p>
                        
                        <p>Thanks for signing up! We're excited to have you on board.</p>
                        
                        <p>To get started, please verify your email address by clicking the button below:</p>
                        
                        <div style="text-align: center;">
                            <a href="{safe_verification_link}" class="button">✓ Verify Email Address</a>
                        </div>
                        
                        <div class="info-box">
                            <strong>⏱️ Important:</strong> This verification link will expire in {TOKEN_EXPIRATION_HOURS} hours.
                        </div>
                        
                        <p>Once verified, you'll have full access to:</p>
                        <ul style="line-height: 2;">
                            <li>✅ Real-time marketplace monitoring</li>
                            <li>✅ Custom search alerts</li>
                            <li>✅ Advanced analytics</li>
                            <li>✅ Multi-platform scraping</li>
                        </ul>
                        
                        <p style="margin-top: 30px; color: #666; font-size: 14px;">
                            If you didn't create this account, you can safely ignore this email.
                        </p>
                    </div>
                    <div class="footer">
                        <p>Need help? <a href="mailto:Botifex2025@gmail.com">Contact Support</a></p>
                        <p>📧 Botifex2025@gmail.com | 📞 (208) 681-6169</p>
                        <p>© 2025 Botifex LLC. All rights reserved.</p>
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
        with smtp_connection() as server:
            server.send_message(msg)
        
        logger.info(f"✅ Verification email sent to {to_email}")
        return True
        
    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"❌ Email authentication failed: {e}")
        return False
    except (smtplib.SMTPException, EmailConfigurationError) as e:
        logger.error(f"❌ SMTP error sending verification email: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Failed to send verification email: {e}")
        return False


@log_errors()
def send_password_reset_email(to_email, username, token, base_url):
    """
    Send password reset link to user
    
    Args:
        to_email: User's email address
        username: Username
        token: Password reset token
        base_url: Base URL of the application
    
    Returns:
        bool: True if email sent successfully
    """
    if not is_email_configured():
        logger.warning("Email credentials not configured. Password reset email not sent.")
        return False
    
    try:
        reset_link = f"{base_url}/reset-password?token={token}"
        safe_reset_link = html.escape(reset_link, quote=True)
        
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = 'Reset Your Super-Bot Password'
        msg['From'] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
        msg['To'] = to_email
        
        # Plain text version
        text_content = f"""
Hi {username},

We received a request to reset your password for your Super-Bot account.

Click the link below to reset your password:

{reset_link}

This link will expire in 1 hour for security reasons.

If you didn't request a password reset, please ignore this email and your password will remain unchanged.

Best regards,
The Super-Bot Team
        """.strip()
        
        # HTML version
        html_content = f"""
        <html>
            <head>
                <style>
                    body {{ 
                        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
                        line-height: 1.6; 
                        color: #333;
                        max-width: 600px;
                        margin: 0 auto;
                    }}
                    .container {{ 
                        background-color: #f9f9f9; 
                        padding: 40px 30px; 
                        border-radius: 10px;
                        margin: 20px 0;
                    }}
                    .header {{ 
                        background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
                        color: white; 
                        padding: 30px; 
                        text-align: center; 
                        border-radius: 10px 10px 0 0;
                        margin: -40px -30px 30px -30px;
                    }}
                    .header h1 {{
                        margin: 0;
                        font-size: 28px;
                    }}
                    .content {{ 
                        background-color: white; 
                        padding: 30px; 
                        border-radius: 8px;
                        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                    }}
                    .button {{ 
                        display: inline-block; 
                        background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
                        color: white !important; 
                        padding: 16px 32px; 
                        text-decoration: none; 
                        border-radius: 8px; 
                        margin: 25px 0;
                        font-weight: 600;
                        font-size: 16px;
                        box-shadow: 0 4px 6px rgba(245, 87, 108, 0.3);
                    }}
                    .warning-box {{
                        background-color: #fff3cd;
                        border-left: 4px solid #ffc107;
                        padding: 15px;
                        margin: 20px 0;
                        border-radius: 4px;
                    }}
                    .security-box {{
                        background-color: #f0f4ff;
                        border-left: 4px solid #667eea;
                        padding: 15px;
                        margin: 20px 0;
                        border-radius: 4px;
                    }}
                    .footer {{ 
                        text-align: center; 
                        color: #888; 
                        font-size: 14px; 
                        padding: 20px 0;
                        margin-top: 30px;
                        border-top: 1px solid #e0e0e0;
                    }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>🔐 Password Reset Request</h1>
                    </div>
                    <div class="content">
                        <p>Hi <strong>{username}</strong>,</p>
                        
                        <p>We received a request to reset the password for your Super-Bot account.</p>
                        
                        <p>Click the button below to create a new password:</p>
                        
                        <div style="text-align: center;">
                            <a href="{safe_reset_link}" class="button">🔑 Reset Password</a>
                        </div>
                        
                        <div class="warning-box">
                            <strong>⏱️ Important:</strong> This link will expire in 1 hour for security reasons.
                        </div>
                        
                        <div class="security-box">
                            <strong>🛡️ Security Tip:</strong> If you didn't request this password reset, please ignore this email. Your password will remain unchanged, and your account is secure.
                        </div>
                        
                        <p style="margin-top: 30px; color: #666; font-size: 14px;">
                            For security reasons, we never ask for your password via email. Always create new passwords through our secure reset form.
                        </p>
                    </div>
                    <div class="footer">
                        <p>Questions? <a href="mailto:Botifex2025@gmail.com">Contact Support</a></p>
                        <p>📧 Botifex2025@gmail.com | 📞 (208) 681-6169</p>
                        <p>© 2025 Botifex LLC. All rights reserved.</p>
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
        with smtp_connection() as server:
            server.send_message(msg)
        
        logger.info(f"✅ Password reset email sent to {to_email}")
        return True
        
    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"❌ Email authentication failed: {e}")
        return False
    except (smtplib.SMTPException, EmailConfigurationError) as e:
        logger.error(f"❌ SMTP error sending password reset email: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Failed to send password reset email: {e}")
        return False


__all__ = [
    'generate_verification_token',
    'generate_password_reset_token',
    'send_verification_email',
    'send_password_reset_email',
    'is_email_configured',
    'TOKEN_EXPIRATION_HOURS',
    'SMTP_HOST',
    'SMTP_PORT',
    'SMTP_USERNAME',
    'SMTP_PASSWORD',
    'SMTP_FROM_EMAIL',
    'SMTP_FROM_NAME',
]

