#!/usr/bin/env python3
"""
Database Schema Fix Script
This script fixes the missing columns and tables causing the application errors
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlite3
import time
from datetime import datetime
from utils import logger

def fix_database_schema():
    """Fix missing database schema elements"""
    db_file = "superbot.db"
    
    try:
        logger.info("Starting database schema fixes...")
        
        # Connect with optimized settings
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
        
        # 1. Fix listings table - add user_id column if missing
        logger.info("Checking listings table schema...")
        c.execute("PRAGMA table_info(listings)")
        columns = [col[1] for col in c.fetchall()]
        
        if 'user_id' not in columns:
            logger.info("Adding 'user_id' column to listings table...")
            c.execute("ALTER TABLE listings ADD COLUMN user_id TEXT")
            logger.info("[OK] Added 'user_id' column to listings table")
        else:
            logger.info("[OK] 'user_id' column already exists in listings table")
        
        # 2. Create subscriptions table if it doesn't exist, or fix missing columns
        logger.info("Checking subscriptions table...")
        c.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='subscriptions'
        """)
        
        if not c.fetchone():
            logger.info("Creating subscriptions table...")
            c.execute("""
                CREATE TABLE subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    tier TEXT DEFAULT 'free',
                    status TEXT DEFAULT 'active',
                    stripe_customer_id TEXT,
                    stripe_subscription_id TEXT,
                    current_period_start DATETIME,
                    current_period_end DATETIME,
                    cancel_at_period_end BOOLEAN DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)
            logger.info("[OK] Created subscriptions table")
        else:
            logger.info("[OK] Subscriptions table already exists")
            
            # Check for missing columns and add them
            c.execute("PRAGMA table_info(subscriptions)")
            columns = [col[1] for col in c.fetchall()]
            
            required_columns = {
                'cancel_at_period_end': 'BOOLEAN DEFAULT 0',
                'current_period_start': 'DATETIME',
                'current_period_end': 'DATETIME',
                'stripe_customer_id': 'TEXT',
                'stripe_subscription_id': 'TEXT'
            }
            
            for col_name, col_def in required_columns.items():
                if col_name not in columns:
                    logger.info(f"Adding missing column '{col_name}' to subscriptions table...")
                    try:
                        c.execute(f"ALTER TABLE subscriptions ADD COLUMN {col_name} {col_def}")
                        logger.info(f"[OK] Added column '{col_name}' to subscriptions table")
                    except sqlite3.OperationalError as e:
                        logger.warning(f"Could not add column '{col_name}': {e}")
                else:
                    logger.info(f"[OK] Column '{col_name}' already exists in subscriptions table")
        
        # 3. Create subscription_history table if it doesn't exist
        logger.info("Checking subscription_history table...")
        c.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='subscription_history'
        """)
        
        if not c.fetchone():
            logger.info("Creating subscription_history table...")
            c.execute("""
                CREATE TABLE subscription_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    tier TEXT NOT NULL,
                    action TEXT NOT NULL,
                    stripe_event_id TEXT,
                    details TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)
            logger.info("[OK] Created subscription_history table")
        else:
            logger.info("[OK] Subscription_history table already exists")
        
        # 4. Create indexes for subscriptions table
        logger.info("Creating indexes for subscriptions table...")
        try:
            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_subscriptions_username 
                ON subscriptions(username)
            """)
            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_subscriptions_tier 
                ON subscriptions(tier)
            """)
            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_subscriptions_status 
                ON subscriptions(status)
            """)
            logger.info("[OK] Created subscription indexes")
        except sqlite3.OperationalError as e:
            logger.warning(f"Index creation warning: {e}")
        
        # 5. Create indexes for subscription_history table
        logger.info("Creating indexes for subscription_history table...")
        try:
            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_subscription_history_username 
                ON subscription_history(username)
            """)
            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_subscription_history_created_at 
                ON subscription_history(created_at)
            """)
            logger.info("[OK] Created subscription_history indexes")
        except sqlite3.OperationalError as e:
            logger.warning(f"Index creation warning: {e}")
        
        # 6. Ensure all users have default subscriptions
        logger.info("Ensuring all users have default subscriptions...")
        c.execute("""
            SELECT username FROM users 
            WHERE username NOT IN (SELECT username FROM subscriptions)
        """)
        users_without_subscriptions = c.fetchall()
        
        for (username,) in users_without_subscriptions:
            c.execute("""
                INSERT INTO subscriptions (username, tier, status, created_at, updated_at)
                VALUES (?, 'free', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """, (username,))
            logger.info(f"Created default subscription for user: {username}")
        
        # 7. Create other missing tables that might be needed
        logger.info("Checking for other missing tables...")
        
        # Email verification tokens table
        c.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='email_verification_tokens'
        """)
        if not c.fetchone():
            logger.info("Creating email_verification_tokens table...")
            c.execute("""
                CREATE TABLE email_verification_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    token TEXT UNIQUE NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    expires_at DATETIME NOT NULL,
                    used BOOLEAN DEFAULT 0,
                    FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)
            logger.info("[OK] Created email_verification_tokens table")
        
        # Password reset tokens table
        c.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='password_reset_tokens'
        """)
        if not c.fetchone():
            logger.info("Creating password_reset_tokens table...")
            c.execute("""
                CREATE TABLE password_reset_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    token TEXT UNIQUE NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    expires_at DATETIME NOT NULL,
                    used BOOLEAN DEFAULT 0,
                    FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)
            logger.info("[OK] Created password_reset_tokens table")
        
        # Favorites table
        c.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='favorites'
        """)
        if not c.fetchone():
            logger.info("Creating favorites table...")
            c.execute("""
                CREATE TABLE favorites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    listing_id INTEGER NOT NULL,
                    notes TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(username, listing_id),
                    FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE,
                    FOREIGN KEY (listing_id) REFERENCES listings (id) ON DELETE CASCADE
                )
            """)
            logger.info("[OK] Created favorites table")
        
        # Saved searches table
        c.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='saved_searches'
        """)
        if not c.fetchone():
            logger.info("Creating saved_searches table...")
            c.execute("""
                CREATE TABLE saved_searches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    name TEXT NOT NULL,
                    keywords TEXT,
                    min_price REAL,
                    max_price REAL,
                    sources TEXT,
                    location TEXT,
                    radius INTEGER,
                    notify_new BOOLEAN DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_run DATETIME,
                    FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)
            logger.info("[OK] Created saved_searches table")
        
        # Price alerts table
        c.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='price_alerts'
        """)
        if not c.fetchone():
            logger.info("Creating price_alerts table...")
            c.execute("""
                CREATE TABLE price_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    keywords TEXT NOT NULL,
                    threshold_price REAL NOT NULL,
                    alert_type TEXT NOT NULL CHECK (alert_type IN ('under', 'over')),
                    active BOOLEAN DEFAULT 1,
                    last_triggered DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)
            logger.info("[OK] Created price_alerts table")
        
        # Commit all changes
        conn.commit()
        
        # Verify all tables exist
        logger.info("Verifying all required tables exist...")
        required_tables = [
            'users', 'listings', 'subscriptions', 'subscription_history',
            'email_verification_tokens', 'password_reset_tokens', 
            'favorites', 'saved_searches', 'price_alerts'
        ]
        
        c.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' 
            AND name IN ({})
        """.format(','.join(['?' for _ in required_tables])), required_tables)
        
        existing_tables = [row[0] for row in c.fetchall()]
        missing_tables = set(required_tables) - set(existing_tables)
        
        if missing_tables:
            logger.error(f"Missing tables: {missing_tables}")
            return False
        else:
            logger.info(f"All required tables exist: {existing_tables}")
        
        # Test database operations
        logger.info("Testing database operations...")
        
        # Test listings table with user_id column
        c.execute("SELECT COUNT(*) FROM listings")
        listing_count = c.fetchone()[0]
        logger.info(f"Listings table has {listing_count} records")
        
        # Test subscriptions table
        c.execute("SELECT COUNT(*) FROM subscriptions")
        subscription_count = c.fetchone()[0]
        logger.info(f"Subscriptions table has {subscription_count} records")
        
        # Test that we can query with user_id
        c.execute("SELECT COUNT(*) FROM listings WHERE user_id IS NOT NULL")
        listings_with_user = c.fetchone()[0]
        logger.info(f"Listings with user_id: {listings_with_user}")
        
        conn.close()
        logger.info("Database schema fixes completed successfully!")
        return True
        
    except Exception as e:
        logger.error(f"Database schema fix failed: {e}")
        return False

if __name__ == "__main__":
    print("Fixing Database Schema...")
    success = fix_database_schema()
    if success:
        print("Database schema fixed successfully!")
    else:
        print("Failed to fix database schema")
        sys.exit(1)
