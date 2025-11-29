"""
Email Verification System for Super-Bot
Handles email verification tokens and verification process
"""

import html
import secrets
import smtplib
from datetime import datetime, timedelta
from typing import Optional, List, Dict
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


def _render_brand_email_html(
    *,
    title: str,
    username: str,
    intro_lines: List[str],
    action_button: Optional[Dict[str, str]] = None,
    code_block: Optional[Dict[str, str]] = None,
    bullet_points: Optional[List[str]] = None,
    notice_sections: Optional[List[Dict[str, str]]] = None,
    outro_lines: Optional[List[str]] = None,
    footer_lines: Optional[List[str]] = None,
) -> str:
    """
    Render a branded HTML email that matches the Botifex UI aesthetic.
    """
    bullet_list_html = ""
    if bullet_points:
        items = "".join(
            f"""
                <li>
                    <span class="bullet-icon">✓</span>
                    <span class="bullet-text">{html.escape(point)}</span>
                </li>
            """
            for point in bullet_points
        )
        bullet_list_html = f"""
            <ul class="feature-list">
                {items}
            </ul>
        """

    code_block_html = ""
    if code_block and code_block.get("value"):
        helper_text = code_block.get("helper", "")
        helper_html = f'<p class="code-helper">{helper_text}</p>' if helper_text else ""
        code_block_html = f"""
            <div class="code-card">
                <p class="code-label">{code_block.get("label", "Verification Code")}</p>
                <div class="code-value">{html.escape(code_block["value"])}</div>
                {helper_html}
            </div>
        """

    notice_html = ""
    if notice_sections:
        variant_styles = {
            "warning": ("warning-card", "warning-icon"),
            "info": ("info-card", "info-icon"),
            "security": ("security-card", "security-icon"),
        }
        cards = []
        for notice in notice_sections:
            variant = notice.get("variant", "info").lower()
            card_class, icon_class = variant_styles.get(variant, ("info-card", "info-icon"))
            icon = notice.get("icon", "ℹ️")
            title_text = notice.get("title", "")
            body_text = notice.get("body", "")
            cards.append(
                f"""
                <div class="notice-card {card_class}">
                    <div class="notice-icon {icon_class}">{icon}</div>
                    <div class="notice-body">
                        {'<p class="notice-title">' + html.escape(title_text) + '</p>' if title_text else ''}
                        <p class="notice-text">{body_text}</p>
                    </div>
                </div>
                """
            )
        notice_html = "".join(cards)

    action_html = ""
    if action_button and action_button.get("href"):
        action_html = f"""
            <div class="cta-wrap">
                <a href="{action_button['href']}" class="cta-button">{html.escape(action_button.get('label', 'View'))}</a>
            </div>
        """

    intro_html = "".join(f"<p>{line}</p>" for line in intro_lines)
    outro_html = "".join(f'<p class="muted">{line}</p>' for line in (outro_lines or []))
    footer_html = "".join(f"<p>{line}</p>" for line in (footer_lines or []))

    return f"""
    <html>
        <head>
            <meta charset="utf-8">
            <meta http-equiv="x-ua-compatible" content="ie=edge">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
                body {{
                    margin: 0;
                    padding: 0;
                    background: #050914;
                    background-image: radial-gradient(circle at 20% 20%, rgba(0, 191, 255, 0.12), transparent 40%),
                                      radial-gradient(circle at 80% 0%, rgba(0, 98, 255, 0.18), transparent 45%),
                                      linear-gradient(135deg, #04050d 0%, #0f172a 55%, #091326 100%);
                    font-family: 'Inter', 'Segoe UI', Tahoma, sans-serif;
                    color: #e2ecff;
                }}
                .outer {{
                    width: 100%;
                    padding: 40px 16px;
                    box-sizing: border-box;
                }}
                .card {{
                    max-width: 620px;
                    margin: 0 auto;
                    background: rgba(10, 16, 32, 0.95);
                    border: 1px solid rgba(0, 191, 255, 0.25);
                    border-radius: 20px;
                    overflow: hidden;
                    box-shadow: 0 25px 60px rgba(2, 12, 34, 0.55);
                }}
                .card-header {{
                    background: linear-gradient(135deg, #0ea5e9 0%, #2563eb 50%, #4338ca 100%);
                    padding: 36px 32px;
                    text-align: center;
                }}
                .card-header h1 {{
                    margin: 0;
                    font-size: 26px;
                    letter-spacing: 0.4px;
                    color: #ffffff;
                    text-shadow: 0 12px 28px rgba(3, 7, 18, 0.45);
                }}
                .card-body {{
                    padding: 32px;
                }}
                .card-body p {{
                    margin: 12px 0;
                    color: rgba(226, 240, 255, 0.92);
                    font-size: 16px;
                    line-height: 1.6;
                }}
                .card-body p strong {{
                    color: #ffffff;
                }}
                .code-card {{
                    background: linear-gradient(135deg, rgba(14, 23, 42, 0.95) 0%, rgba(12, 18, 35, 0.95) 100%);
                    border: 1px solid rgba(96, 165, 250, 0.55);
                    border-radius: 14px;
                    padding: 24px;
                    text-align: center;
                    margin: 26px 0;
                    box-shadow: 0 18px 38px rgba(30, 64, 175, 0.35);
                }}
                .code-label {{
                    margin: 0 0 12px 0;
                    text-transform: uppercase;
                    font-size: 13px;
                    letter-spacing: 1.8px;
                    color: rgba(191, 219, 254, 0.85);
                }}
                .code-value {{
                    font-size: 32px;
                    font-weight: 700;
                    letter-spacing: 8px;
                    color: #f8fafc;
                }}
                .code-helper {{
                    margin: 14px 0 0 0;
                    font-size: 14px;
                    color: rgba(191, 219, 254, 0.75);
                }}
                .code-helper a {{
                    color: #60a5fa;
                    text-decoration: none;
                }}
                .feature-list {{
                    list-style: none;
                    padding: 0;
                    margin: 28px 0 24px 0;
                }}
                .feature-list li {{
                    display: flex;
                    align-items: flex-start;
                    margin: 10px 0;
                }}
                .bullet-icon {{
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    width: 22px;
                    height: 22px;
                    margin-right: 12px;
                    border-radius: 50%;
                    background: rgba(45, 212, 191, 0.18);
                    color: #2dd4bf;
                    font-size: 12px;
                    font-weight: 700;
                }}
                .bullet-text {{
                    color: rgba(226, 240, 255, 0.9);
                    font-size: 15px;
                    line-height: 1.6;
                }}
                .cta-wrap {{
                    text-align: center;
                    margin: 28px 0;
                }}
                .cta-button {{
                    display: inline-block;
                    padding: 14px 36px;
                    border-radius: 999px;
                    background: linear-gradient(135deg, #22d3ee 0%, #0ea5e9 45%, #2563eb 100%);
                    color: #0f172a !important;
                    text-decoration: none;
                    font-weight: 700;
                    letter-spacing: 1px;
                    text-transform: uppercase;
                    box-shadow: 0 20px 40px rgba(14, 165, 233, 0.35);
                }}
                .cta-button:hover {{
                    filter: brightness(1.05);
                }}
                .notice-card {{
                    display: flex;
                    align-items: flex-start;
                    border-radius: 14px;
                    padding: 18px 20px;
                    margin: 18px 0;
                }}
                .notice-icon {{
                    font-size: 20px;
                    margin-right: 14px;
                    margin-top: 2px;
                }}
                .notice-title {{
                    margin: 0 0 6px 0;
                    font-weight: 600;
                    color: #f8fafc;
                }}
                .notice-text {{
                    margin: 0;
                    color: rgba(226, 232, 240, 0.85);
                    font-size: 15px;
                    line-height: 1.6;
                }}
                .warning-card {{
                    background: rgba(251, 191, 36, 0.14);
                    border: 1px solid rgba(251, 191, 36, 0.35);
                }}
                .info-card {{
                    background: rgba(59, 130, 246, 0.12);
                    border: 1px solid rgba(59, 130, 246, 0.35);
                }}
                .security-card {{
                    background: rgba(14, 165, 233, 0.16);
                    border: 1px solid rgba(14, 165, 233, 0.4);
                }}
                .muted {{
                    color: rgba(148, 163, 184, 0.85) !important;
                    font-size: 14px !important;
                }}
                .card-footer {{
                    padding: 24px 32px 36px 32px;
                    border-top: 1px solid rgba(59, 130, 246, 0.15);
                    background: rgba(7, 12, 24, 0.9);
                    text-align: center;
                }}
                .card-footer p {{
                    margin: 6px 0;
                    font-size: 13px;
                    color: rgba(148, 163, 184, 0.88);
                }}
                .card-footer a {{
                    color: #38bdf8;
                    text-decoration: none;
                }}
                @media (max-width: 520px) {{
                    .card-body, .card-header, .card-footer {{
                        padding-left: 20px;
                        padding-right: 20px;
                    }}
                    .code-value {{
                        font-size: 26px;
                        letter-spacing: 6px;
                    }}
                    .cta-button {{
                        width: 100%;
                    }}
                }}
            </style>
        </head>
        <body>
            <div class="outer">
                <div class="card">
                    <div class="card-header">
                        <h1>{html.escape(title)}</h1>
                    </div>
                    <div class="card-body">
                        <p>Hi <strong>{html.escape(username)}</strong>,</p>
                        {intro_html}
                        {code_block_html}
                        {bullet_list_html}
                        {action_html}
                        {notice_html}
                        {outro_html}
                    </div>
                    <div class="card-footer">
                        {footer_html}
                    </div>
                </div>
            </div>
        </body>
    </html>
    """


@log_errors()
def send_verification_email(to_email, username, token, base_url, verification_code: Optional[str] = None):
    """
    Send email verification link to user
    
    Args:
        to_email: User's email address
        username: Username
        token: Verification token
        base_url: Base URL of the application
        verification_code: Optional numeric verification code for manual entry
    
    Returns:
        bool: True if email sent successfully
    """
    if not is_email_configured():
        logger.warning("Email credentials not configured. Verification email not sent.")
        return False
    
    try:
        verification_link = f"{base_url}/verify-email?token={token}"
        verification_code_url = f"{base_url}/verify-email-code"
        safe_verification_link = html.escape(verification_link, quote=True)
        safe_code_url = html.escape(verification_code_url, quote=True)
        
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = 'Verify Your Super-Bot Account'
        msg['From'] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
        msg['To'] = to_email
        
        # Plain text version
        text_lines = [
            f"Welcome to Botifex, {username}!",
            "",
            "You're one step away from activating your account.",
            "",
        ]

        if verification_code:
            text_lines.extend([
                f"1. Enter this verification code: {verification_code}",
                f"   Verification page: {verification_code_url}",
                "",
                "or",
                "",
            ])

        text_lines.extend([
            "2. Click the verification link:",
            f"   {verification_link}",
            "",
            f"The link and code expire in {TOKEN_EXPIRATION_HOURS} hours.",
            "",
            "Once you're verified you'll unlock:",
            "- Real-time marketplace alerts",
            "- Multi-platform scraping across your favorite sites",
            "- Pro dashboards and pricing insights",
            "",
            "If you didn't create this account, you can ignore this message.",
            "",
            "— The Botifex Team",
        ])

        text_content = "\n".join(text_lines)
        
        code_block_data = None
        if verification_code:
            code_block_data = {
                "label": "Your verification code",
                "value": verification_code,
                "helper": f'Enter this code at <a href="{safe_code_url}">{verification_code_url}</a>',
            }

        html_content = _render_brand_email_html(
            title="Verify Your Botifex Email",
            username=username,
            intro_lines=[
                "Thanks for joining Botifex! You're just one step away from activating your account.",
                "Choose the option that works best for you to confirm your email address.",
            ],
            action_button={
                "label": "Verify Email",
                "href": safe_verification_link,
            },
            code_block=code_block_data,
            bullet_points=[
                "Real-time marketplace alerts tuned to your saved searches",
                "Smart dashboards and pricing insights tailored for resellers",
                "Hands-off scraping across Facebook, Craigslist, eBay, and more",
            ],
            notice_sections=[
                {
                    "icon": "⏱️",
                    "title": "Expires Soon",
                    "body": f"The verification link and code expire in {TOKEN_EXPIRATION_HOURS} hours.",
                    "variant": "warning",
                }
            ],
            outro_lines=[
                "Didn't create this account? You can ignore this email and nothing will change.",
            ],
            footer_lines=[
                "Need a hand? Reply to this message or reach out to Botifex support any time.",
                "Botifex LLC · Boise, ID · botifex2025@gmail.com",
            ],
        )
        
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

We just received a request to reset your Botifex password.

Reset link: {reset_link}

This secure link is active for 60 minutes. If you didn't request a reset, you can safely ignore this email and your password will stay the same.

— The Botifex Team
        """.strip()

        html_content = _render_brand_email_html(
            title="Reset Your Botifex Password",
            username=username,
            intro_lines=[
                "We received a request to reset the password on your Botifex account.",
                "Use the secure button below to choose a new password and jump back into your dashboard.",
            ],
            action_button={
                "label": "Reset Password",
                "href": safe_reset_link,
            },
            bullet_points=[
                "One-time link that keeps your workspace secure",
                "Valid for 60 minutes from the time this email was sent",
            ],
            notice_sections=[
                {
                    "icon": "⏱️",
                    "title": "Link expires",
                    "body": "For your protection, this reset link automatically disables itself after 60 minutes.",
                    "variant": "warning",
                },
                {
                    "icon": "🛡️",
                    "title": "Didn't request this?",
                    "body": "Ignore the email and your password will remain unchanged. No further action is required.",
                    "variant": "security",
                },
            ],
            outro_lines=[
                "Botifex will never ask for your password via email. Always reset using our official forms for full protection.",
            ],
            footer_lines=[
                "Questions? Reply to this message or contact botifex2025@gmail.com.",
                "Botifex LLC · Boise, ID",
            ],
        )
        
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

