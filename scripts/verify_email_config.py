#!/usr/bin/env python3
"""
Quick Email Configuration Verification
Non-interactive test to verify email system is working
"""

import os
import sys
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
from email_utils import (
    EmailConfigurationError,
    SMTP_REQUIRE_AUTH,
    SMTP_USE_SSL,
    SMTP_USE_TLS,
    smtp_connection,
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
print(f"   SMTP_USE_TLS: {'ON' if SMTP_USE_TLS else 'OFF'}")
print(f"   SMTP_USE_SSL: {'ON' if SMTP_USE_SSL else 'OFF'}")
print(f"   SMTP_REQUIRE_AUTH: {'ON' if SMTP_REQUIRE_AUTH else 'OFF'}")
print(f"   Configured: {'✅ YES' if is_email_configured() else '❌ NO'}\n")

# Test SMTP connection
print("2. SMTP Connection Test:")
if not is_email_configured():
    print("   ❌ SKIPPED - Email not configured\n")
    sys.exit(1)

try:
    with smtp_connection():
        pass
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
    
except EmailConfigurationError as e:
    print(f"   ❌ Configuration error: {e}\n")
    print("="*70)
    print("  ⚠️  EMAIL SYSTEM NEEDS ATTENTION")
    print("="*70 + "\n")
    sys.exit(1)
except Exception as e:
    print(f"   ❌ Connection failed: {e}\n")
    print("="*70)
    print("  ⚠️  EMAIL SYSTEM NEEDS ATTENTION")
    print("="*70 + "\n")
    sys.exit(1)

