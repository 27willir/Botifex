#!/usr/bin/env python3
"""Check database schema for email functionality"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

DB_FILE = "superbot.db"

print("\n" + "="*70)
print("  DATABASE SCHEMA CHECK - EMAIL TABLES")
print("="*70 + "\n")

try:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Check all tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
    tables = [t[0] for t in cursor.fetchall()]
    
    # Check users table
    print("1. Users Table:")
    if 'users' in tables:
        cursor.execute("PRAGMA table_info(users);")
        cols = {c[1]: c[2] for c in cursor.fetchall()}
        
        required_email_cols = ['email', 'verified']
        for col in required_email_cols:
            if col in cols:
                print(f"   ✅ {col} ({cols[col]})")
            else:
                print(f"   ❌ {col} - MISSING")
    else:
        print("   ❌ Users table not found!\n")
        sys.exit(1)
    
    # Check email_verification_tokens table
    print("\n2. Email Verification Tokens Table:")
    if 'email_verification_tokens' in tables:
        cursor.execute("PRAGMA table_info(email_verification_tokens);")
        cols = cursor.fetchall()
        print("   ✅ Table exists")
        for c in cols:
            print(f"      • {c[1]} ({c[2]})")
    else:
        print("   ⚠️  Table does not exist - will be created on first use")
    
    # Check password_reset_tokens table
    print("\n3. Password Reset Tokens Table:")
    if 'password_reset_tokens' in tables:
        cursor.execute("PRAGMA table_info(password_reset_tokens);")
        cols = cursor.fetchall()
        print("   ✅ Table exists")
        for c in cols:
            print(f"      • {c[1]} ({c[2]})")
    else:
        print("   ⚠️  Table does not exist - will be created on first use")
    
    # Check if verified column has correct default
    print("\n4. User Verification Status:")
    cursor.execute("SELECT COUNT(*) FROM users WHERE verified = 1;")
    verified = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM users WHERE verified = 0;")
    unverified = cursor.fetchone()[0]
    total = verified + unverified
    
    print(f"   Total users: {total}")
    print(f"   Verified: {verified}")
    print(f"   Unverified: {unverified}")
    
    conn.close()
    
    print("\n" + "="*70)
    print("  ✅ DATABASE SCHEMA CHECK COMPLETE")
    print("="*70 + "\n")
    
except Exception as e:
    print(f"\n❌ Error: {e}\n")
    sys.exit(1)

