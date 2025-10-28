#!/usr/bin/env python3
"""
Production Schema Fix Script
This script fixes missing database schema elements in production
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlite3
import time
from datetime import datetime
from utils import logger

def fix_production_schema():
    """Fix production database schema issues"""
    db_file = "superbot.db"
    
    try:
        logger.info("Starting production schema fix...")
        
        # Connect with optimized settings for production
        conn = sqlite3.connect(
            db_file, 
            timeout=30,
            check_same_thread=False
        )
        
        # Set production-optimized pragmas
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=10000")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA mmap_size=268435456")  # 256MB
        conn.execute("PRAGMA busy_timeout=10000")  # 10 second timeout
        conn.execute("PRAGMA foreign_keys=ON")
        
        c = conn.cursor()
        
        # 1. Fix users table - add missing phone_number column
        logger.info("Checking users table schema...")
        c.execute("PRAGMA table_info(users)")
        columns = [col[1] for col in c.fetchall()]
        
        if 'phone_number' not in columns:
            logger.info("Adding missing phone_number column to users table...")
            try:
                c.execute("ALTER TABLE users ADD COLUMN phone_number TEXT")
                logger.info("[OK] Added phone_number column to users table")
            except sqlite3.OperationalError as e:
                logger.warning(f"Could not add phone_number column: {e}")
        else:
            logger.info("[OK] phone_number column already exists in users table")
        
        # Add other missing notification columns if they don't exist
        if 'email_notifications' not in columns:
            logger.info("Adding missing email_notifications column to users table...")
            try:
                c.execute("ALTER TABLE users ADD COLUMN email_notifications BOOLEAN DEFAULT 1")
                logger.info("[OK] Added email_notifications column to users table")
            except sqlite3.OperationalError as e:
                logger.warning(f"Could not add email_notifications column: {e}")
        else:
            logger.info("[OK] email_notifications column already exists in users table")
        
        if 'sms_notifications' not in columns:
            logger.info("Adding missing sms_notifications column to users table...")
            try:
                c.execute("ALTER TABLE users ADD COLUMN sms_notifications BOOLEAN DEFAULT 0")
                logger.info("[OK] Added sms_notifications column to users table")
            except sqlite3.OperationalError as e:
                logger.warning(f"Could not add sms_notifications column: {e}")
        else:
            logger.info("[OK] sms_notifications column already exists in users table")
        
        # 2. Create settings table if it doesn't exist
        logger.info("Checking for settings table...")
        c.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='settings'
        """)
        settings_table_exists = c.fetchone()
        
        if not settings_table_exists:
            logger.info("Creating missing settings table...")
            c.execute("""
                CREATE TABLE settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT,
                    key TEXT,
                    value TEXT,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(username, key),
                    FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)
            logger.info("[OK] Created settings table")
        else:
            logger.info("[OK] Settings table already exists")
        
        # 3. Create indexes for settings table
        logger.info("Creating indexes for settings table...")
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_settings_username 
            ON settings(username)
        """)
        
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_settings_key 
            ON settings(key)
        """)
        
        # 4. Check for other missing tables that might be needed
        required_tables = [
            'user_activity',
            'rate_limits', 
            'subscriptions',
            'subscription_history',
            'email_verification_tokens',
            'password_reset_tokens',
            'favorites',
            'saved_searches',
            'price_alerts'
        ]
        
        logger.info("Checking for other required tables...")
        c.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' 
            AND name IN ('user_activity', 'rate_limits', 'subscriptions', 'subscription_history',
                        'email_verification_tokens', 'password_reset_tokens', 'favorites',
                        'saved_searches', 'price_alerts')
        """)
        existing_tables = [table[0] for table in c.fetchall()]
        
        missing_tables = [table for table in required_tables if table not in existing_tables]
        
        if missing_tables:
            logger.warning(f"Missing tables detected: {missing_tables}")
            logger.info("These tables should be created by the main production initialization script")
        else:
            logger.info("[OK] All required tables exist")
        
        # 5. Test the fixes
        logger.info("Testing schema fixes...")
        
        # Test phone_number column access
        try:
            c.execute("SELECT phone_number FROM users LIMIT 1")
            logger.info("[OK] phone_number column is accessible")
        except sqlite3.OperationalError as e:
            logger.error(f"phone_number column test failed: {e}")
        
        # Test settings table access
        try:
            c.execute("SELECT COUNT(*) FROM settings")
            logger.info("[OK] settings table is accessible")
        except sqlite3.OperationalError as e:
            logger.error(f"settings table test failed: {e}")
        
        # Test inserting into settings table
        try:
            test_username = "schema_test_user"
            test_key = "test_setting"
            test_value = "test_value"
            
            c.execute("""
                INSERT OR REPLACE INTO settings (username, key, value, updated_at)
                VALUES (?, ?, ?, ?)
            """, (test_username, test_key, test_value, datetime.now()))
            
            # Verify insert
            c.execute("SELECT value FROM settings WHERE username = ? AND key = ?", 
                     (test_username, test_key))
            result = c.fetchone()
            
            if result and result[0] == test_value:
                logger.info("[OK] settings table insert/select working")
                # Clean up test data
                c.execute("DELETE FROM settings WHERE username = ?", (test_username,))
            else:
                logger.error("settings table insert/select test failed")
        except sqlite3.OperationalError as e:
            logger.error(f"settings table insert test failed: {e}")
        
        # Commit all changes
        conn.commit()
        
        # Final verification
        logger.info("Performing final schema verification...")
        
        # Check users table columns
        c.execute("PRAGMA table_info(users)")
        user_columns = [col[1] for col in c.fetchall()]
        required_user_columns = ['phone_number', 'email_notifications', 'sms_notifications']
        
        missing_user_columns = [col for col in required_user_columns if col not in user_columns]
        if missing_user_columns:
            logger.error(f"Still missing user columns: {missing_user_columns}")
        else:
            logger.info("[OK] All required user columns exist")
        
        # Check settings table exists
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='settings'")
        if c.fetchone():
            logger.info("[OK] Settings table exists and is accessible")
        else:
            logger.error("Settings table still missing")
        
        conn.close()
        logger.info("Production schema fix completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"Production schema fix failed: {e}")
        return False

if __name__ == "__main__":
    print("Fixing Production Database Schema...")
    success = fix_production_schema()
    if success:
        print("Production schema fixed successfully!")
    else:
        print("Failed to fix production schema")
        sys.exit(1)