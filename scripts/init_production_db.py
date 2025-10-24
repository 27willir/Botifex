#!/usr/bin/env python3
"""
Production Database Initialization Script
This script ensures all required tables exist on production deployment
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlite3
import time
from datetime import datetime
from utils import logger

def init_production_database():
    """Initialize production database with all required tables"""
    db_file = "superbot.db"
    
    try:
        logger.info("Starting production database initialization...")
        
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
        
        # Create security_events table
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
        
        # Create indexes for performance
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_security_events_ip 
            ON security_events(ip_address)
        """)
        
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_security_events_timestamp 
            ON security_events(timestamp)
        """)
        
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_security_events_path 
            ON security_events(path)
        """)
        
        # Create rate_limits table
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
        
        # Create indexes for rate limits
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_rate_limits_username 
            ON rate_limits(username, endpoint)
        """)
        
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_rate_limits_window 
            ON rate_limits(window_start)
        """)
        
        # Create users table if it doesn't exist
        logger.info("Ensuring users table exists...")
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                verified BOOLEAN DEFAULT 0,
                role TEXT DEFAULT 'user',
                active BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_login DATETIME,
                login_count INTEGER DEFAULT 0,
                subscription_tier TEXT DEFAULT 'free',
                tos_agreed BOOLEAN DEFAULT 0,
                tos_agreed_at DATETIME,
                email_notifications BOOLEAN DEFAULT 1,
                sms_notifications BOOLEAN DEFAULT 0
            )
        """)
        
        # Create listings table if it doesn't exist
        logger.info("Ensuring listings table exists...")
        c.execute("""
            CREATE TABLE IF NOT EXISTS listings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                price TEXT,
                link TEXT,
                image_url TEXT,
                source TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create user_activity table
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
        
        # Create indexes for user_activity
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_user_activity_username 
            ON user_activity(username)
        """)
        
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_user_activity_timestamp 
            ON user_activity(timestamp)
        """)
        
        # Commit all changes
        conn.commit()
        
        # Verify tables exist
        c.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' 
            AND name IN ('security_events', 'rate_limits', 'users', 'listings', 'user_activity')
        """)
        tables = c.fetchall()
        
        logger.info(f"Production database initialized successfully: {[table[0] for table in tables]}")
        
        # Test database operations
        logger.info("Testing database operations...")
        
        # Test security_events table
        test_ip = "127.0.0.1"
        test_path = "/test"
        test_agent = "Production Test"
        test_reason = "Database initialization test"
        
        c.execute("""
            INSERT INTO security_events (ip_address, path, user_agent, reason, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (test_ip, test_path, test_agent, test_reason, datetime.now()))
        
        conn.commit()
        
        # Verify insert worked
        c.execute("SELECT COUNT(*) FROM security_events WHERE ip_address = ?", (test_ip,))
        count = c.fetchone()[0]
        
        if count > 0:
            logger.info("Security events table working correctly")
            # Clean up test record
            c.execute("DELETE FROM security_events WHERE ip_address = ?", (test_ip,))
            conn.commit()
        else:
            logger.error("Security events table test failed")
            return False
        
        # Test rate_limits table
        c.execute("""
            INSERT OR REPLACE INTO rate_limits (username, endpoint, request_count, window_start)
            VALUES (?, ?, ?, ?)
        """, ("test_user", "api", 1, datetime.now()))
        
        conn.commit()
        
        # Verify rate_limits insert
        c.execute("SELECT COUNT(*) FROM rate_limits WHERE username = ?", ("test_user",))
        count = c.fetchone()[0]
        
        if count > 0:
            logger.info("Rate limits table working correctly")
            # Clean up test record
            c.execute("DELETE FROM rate_limits WHERE username = ?", ("test_user",))
            conn.commit()
        else:
            logger.error("Rate limits table test failed")
            return False
        
        conn.close()
        logger.info("Production database initialization completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"Production database initialization failed: {e}")
        return False

if __name__ == "__main__":
    print("Initializing Production Database...")
    success = init_production_database()
    if success:
        print("Production database initialized successfully!")
    else:
        print("Failed to initialize production database")
        sys.exit(1)
