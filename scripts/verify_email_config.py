#!/usr/bin/env python3
"""
Quick Email Configuration Verification
Non-interactive test to verify email system is working
"""

import os
import sys
import smtplib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from email_verification import (
    is_email_configured,
    SMTP_HOST,
    SMTP_PORT,
    SMTP_USERNAME,
    SMTP_PASSWORD,
)

load_dotenv()

print("\n" + "="*70)
print("  EMAIL SYSTEM VERIFICATION")
print("="*70 + "\n")

# Check environment variables
print("1. Environment Variables:")
print(f"   SMTP_HOST: {SMTP_HOST}")
print(f"   SMTP_PORT: {SMTP_PORT}")
print(f"   SMTP_USERNAME: {SMTP_USERNAME[:4]}***{SMTP_USERNAME[-4:] if len(SMTP_USERNAME) > 8 else '***'}")
print(f"   SMTP_PASSWORD: {'***' if SMTP_PASSWORD else 'NOT SET'}")
print(f"   Configured: {'✅ YES' if is_email_configured() else '❌ NO'}\n")

# Test SMTP connection
print("2. SMTP Connection Test:")
if not is_email_configured():
    print("   ❌ SKIPPED - Email not configured\n")
    sys.exit(1)

try:
    server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10)
    server.starttls()
    server.login(SMTP_USERNAME, SMTP_PASSWORD)
    server.quit()
    print("   ✅ Connection successful\n")
    
    print("="*70)
    print("  ✅ EMAIL SYSTEM IS READY")
    print("="*70)
    print("\nYour email system is properly configured and working!")
    print("\nEmail features available:")
    print("  • Email verification for new users")
    print("  • Password reset emails")
    print("  • Listing notification emails")
    print("\n")
    sys.exit(0)
    
except Exception as e:
    print(f"   ❌ Connection failed: {e}\n")
    print("="*70)
    print("  ⚠️  EMAIL SYSTEM NEEDS ATTENTION")
    print("="*70 + "\n")
    sys.exit(1)

