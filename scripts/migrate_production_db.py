#!/usr/bin/env python3
"""
Production Database Migration Script
Fixes missing tables and columns for production deployment
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlite3
import time
from datetime import datetime
from utils import logger

def migrate_production_database():
    """Migrate production database with missing tables and columns"""
    db_file = "superbot.db"
    
    try:
        logger.info("Starting production database migration...")
        
        # Connect to database
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
        
        # Create subscriptions table if it doesn't exist
        logger.info("Creating subscriptions table...")
        c.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                tier TEXT DEFAULT 'free',
                status TEXT DEFAULT 'active',
                stripe_customer_id TEXT,
                stripe_subscription_id TEXT,
                current_period_start DATETIME,
                current_period_end DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
            )
        """)
        
        # Add user_id column to listings table if it doesn't exist
        logger.info("Adding user_id column to listings table...")
        try:
            c.execute("ALTER TABLE listings ADD COLUMN user_id TEXT")
            logger.info("Added user_id column to listings table")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                logger.info("user_id column already exists in listings table")
            else:
                raise e
        
        # Create security_events table if it doesn't exist
        logger.info("Creating security_events table...")
        c.execute("""
            CREATE TABLE IF NOT EXISTS security_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip_address TEXT NOT NULL,
                path TEXT NOT NULL,
                user_agent TEXT,
                reason TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create rate_limits table if it doesn't exist
        logger.info("Creating rate_limits table...")
        c.execute("""
            CREATE TABLE IF NOT EXISTS rate_limits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                request_count INTEGER DEFAULT 1,
                window_start DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(username, endpoint, window_start)
            )
        """)
        
        # Create user_activity table if it doesn't exist
        logger.info("Creating user_activity table...")
        c.execute("""
            CREATE TABLE IF NOT EXISTS user_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT,
                action TEXT,
                details TEXT,
                ip_address TEXT,
                user_agent TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
            )
        """)
        
        # Create email_verification_tokens table if it doesn't exist
        logger.info("Creating email_verification_tokens table...")
        c.execute("""
            CREATE TABLE IF NOT EXISTS email_verification_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                token TEXT UNIQUE NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                expires_at DATETIME NOT NULL,
                used BOOLEAN DEFAULT 0,
                FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
            )
        """)
        
        # Create password_reset_tokens table if it doesn't exist
        logger.info("Creating password_reset_tokens table...")
        c.execute("""
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                token TEXT UNIQUE NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                expires_at DATETIME NOT NULL,
                used BOOLEAN DEFAULT 0,
                FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
            )
        """)
        
        # Create indexes for performance
        logger.info("Creating performance indexes...")
        
        # Security events indexes
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_security_events_ip 
            ON security_events(ip_address)
        """)
        
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_security_events_timestamp 
            ON security_events(timestamp)
        """)
        
        # Rate limits indexes
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_rate_limits_username 
            ON rate_limits(username, endpoint)
        """)
        
        # User activity indexes
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_user_activity_username 
            ON user_activity(username)
        """)
        
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_user_activity_timestamp 
            ON user_activity(timestamp)
        """)
        
        # Subscriptions indexes
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_subscriptions_username 
            ON subscriptions(username)
        """)
        
        # Commit all changes
        conn.commit()
        
        # Verify tables exist
        c.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' 
            AND name IN ('subscriptions', 'security_events', 'rate_limits', 'user_activity', 'email_verification_tokens', 'password_reset_tokens')
        """)
        tables = c.fetchall()
        
        logger.info(f"Production database migration completed successfully: {[table[0] for table in tables]}")
        
        # Test database operations
        logger.info("Testing database operations...")
        
        # Test subscriptions table
        c.execute("SELECT COUNT(*) FROM subscriptions")
        count = c.fetchone()[0]
        logger.info(f"Subscriptions table working correctly ({count} records)")
        
        # Test listings table with user_id
        c.execute("SELECT COUNT(*) FROM listings")
        count = c.fetchone()[0]
        logger.info(f"Listings table working correctly ({count} records)")
        
        conn.close()
        logger.info("Production database migration completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"Production database migration failed: {e}")
        return False

if __name__ == "__main__":
    print("Migrating Production Database...")
    success = migrate_production_database()
    if success:
        print("Production database migration completed successfully!")
    else:
        print("Failed to migrate production database")
        sys.exit(1)
