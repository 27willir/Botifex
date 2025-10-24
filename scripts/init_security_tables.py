#!/usr/bin/env python3
"""
Initialize security tables in the database
This script ensures all security-related tables are created properly
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlite3
from datetime import datetime
from utils import logger

def init_security_tables():
    """Initialize security-related tables"""
    db_file = "superbot.db"
    
    try:
        # Connect to database
        conn = sqlite3.connect(db_file, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        
        c = conn.cursor()
        
        # Create security_events table
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
        
        # Create index for better performance
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_security_events_ip 
            ON security_events(ip_address)
        """)
        
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_security_events_timestamp 
            ON security_events(timestamp)
        """)
        
        # Create rate_limits table if it doesn't exist
        c.execute("""
            CREATE TABLE IF NOT EXISTS rate_limits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                endpoint_type TEXT NOT NULL,
                request_count INTEGER DEFAULT 1,
                window_start DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(username, endpoint_type, window_start)
            )
        """)
        
        # Create index for rate limits
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_rate_limits_username 
            ON rate_limits(username, endpoint_type)
        """)
        
        # Commit changes
        conn.commit()
        
        # Verify tables exist
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('security_events', 'rate_limits')")
        tables = c.fetchall()
        
        logger.info(f"Security tables initialized successfully: {[table[0] for table in tables]}")
        
        # Test inserting a security event
        test_ip = "127.0.0.1"
        test_path = "/test"
        test_agent = "Test Agent"
        test_reason = "Table initialization test"
        
        c.execute("""
            INSERT INTO security_events (ip_address, path, user_agent, reason, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (test_ip, test_path, test_agent, test_reason, datetime.now()))
        
        conn.commit()
        
        # Verify the insert worked
        c.execute("SELECT COUNT(*) FROM security_events WHERE ip_address = ?", (test_ip,))
        count = c.fetchone()[0]
        
        if count > 0:
            logger.info("Security events table is working correctly")
            # Clean up test record
            c.execute("DELETE FROM security_events WHERE ip_address = ?", (test_ip,))
            conn.commit()
        else:
            logger.error("Security events table test failed")
            return False
            
        conn.close()
        return True
        
    except Exception as e:
        logger.error(f"Failed to initialize security tables: {e}")
        return False

if __name__ == "__main__":
    print("Initializing security tables...")
    success = init_security_tables()
    if success:
        print("✅ Security tables initialized successfully!")
    else:
        print("❌ Failed to initialize security tables")
        sys.exit(1)