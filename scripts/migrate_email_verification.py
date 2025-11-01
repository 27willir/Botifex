#!/usr/bin/env python3
"""
Migration script to update email verification system
This script:
1. Adds verified column if it doesn't exist
2. Optionally marks specific users as verified (e.g., admin accounts)
3. Leaves regular users unverified by default
"""

import sys
import os
import sqlite3
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import logger

DB_FILE = os.getenv('DB_FILE', 'superbot.db')


def migrate_email_verification(mark_existing_users_verified=True):
    """
    Migrate database for email verification
    
    Args:
        mark_existing_users_verified: If True, marks all existing users as verified
                                      If False, marks all users as unverified
    """
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        # Check if verified column exists
        c.execute("PRAGMA table_info(users)")
        columns = [row[1] for row in c.fetchall()]
        
        if 'verified' not in columns:
            logger.info("Adding 'verified' column to users table...")
            c.execute("ALTER TABLE users ADD COLUMN verified BOOLEAN DEFAULT 0")
            conn.commit()
            logger.info("✅ Added 'verified' column")
        else:
            logger.info("✓ 'verified' column already exists")
        
        # Get count of users
        c.execute("SELECT COUNT(*) FROM users")
        user_count = c.fetchone()[0]
        logger.info(f"Found {user_count} existing users")
        
        if user_count > 0:
            if mark_existing_users_verified:
                # Mark all existing users as verified (grandfathering in)
                c.execute("UPDATE users SET verified = 1 WHERE verified IS NULL OR verified = 0")
                updated = c.rowcount
                conn.commit()
                logger.info(f"✅ Marked {updated} existing users as verified (grandfathered)")
            else:
                # Mark all users as unverified (strict mode)
                c.execute("UPDATE users SET verified = 0")
                updated = c.rowcount
                conn.commit()
                logger.warning(f"⚠️  Marked {updated} users as unverified - they will need to verify their emails")
        
        # Show current verification status
        c.execute("SELECT COUNT(*) FROM users WHERE verified = 1")
        verified_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM users WHERE verified = 0")
        unverified_count = c.fetchone()[0]
        
        logger.info(f"\n📊 Current status:")
        logger.info(f"  Verified users: {verified_count}")
        logger.info(f"  Unverified users: {unverified_count}")
        
        conn.close()
        logger.info("\n✅ Migration completed successfully!")
        
        return True
        
    except sqlite3.Error as e:
        logger.error(f"❌ Database error during migration: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Unexpected error during migration: {e}")
        return False


def verify_specific_user(username):
    """Mark a specific user as verified"""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        c.execute("UPDATE users SET verified = 1 WHERE username = ?", (username,))
        if c.rowcount > 0:
            conn.commit()
            logger.info(f"✅ Verified user: {username}")
            return True
        else:
            logger.warning(f"❌ User not found: {username}")
            return False
            
    except sqlite3.Error as e:
        logger.error(f"❌ Database error: {e}")
        return False
    finally:
        conn.close()


def show_verification_status():
    """Show verification status of all users"""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        c.execute("""
            SELECT username, email, verified, role, created_at 
            FROM users 
            ORDER BY created_at DESC
        """)
        
        users = c.fetchall()
        
        if not users:
            logger.info("No users found in database")
            return
        
        logger.info("\n📊 User Verification Status:")
        logger.info("=" * 80)
        logger.info(f"{'Username':<20} {'Email':<30} {'Verified':<10} {'Role':<10}")
        logger.info("-" * 80)
        
        for username, email, verified, role, created_at in users:
            verified_str = "✅ Yes" if verified else "❌ No"
            logger.info(f"{username:<20} {email:<30} {verified_str:<10} {role:<10}")
        
        logger.info("=" * 80)
        
        conn.close()
        
    except sqlite3.Error as e:
        logger.error(f"❌ Database error: {e}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Migrate email verification system')
    parser.add_argument('--mode', choices=['grandfather', 'strict', 'status'], 
                       default='grandfather',
                       help='Migration mode: grandfather (verify existing users), strict (require verification), status (show current status)')
    parser.add_argument('--verify-user', type=str,
                       help='Verify a specific user by username')
    
    args = parser.parse_args()
    
    if args.verify_user:
        verify_specific_user(args.verify_user)
    elif args.mode == 'status':
        show_verification_status()
    else:
        mark_existing_verified = (args.mode == 'grandfather')
        logger.info(f"\n🔄 Running migration in {args.mode.upper()} mode...")
        if mark_existing_verified:
            logger.info("Existing users will be marked as verified (grandfathered in)")
        else:
            logger.info("⚠️  WARNING: All users will need to verify their emails!")
        
        logger.info("\nStarting in 2 seconds... (Ctrl+C to cancel)")
        import time
        time.sleep(2)
        
        migrate_email_verification(mark_existing_verified)
        logger.info("\n📊 Final verification status:")
        show_verification_status()

