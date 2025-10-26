#!/usr/bin/env python3
"""
Production Schema Fix Script
This script fixes missing columns in production database:
- user_id column in listings table
- cancel_at_period_end column in subscriptions table
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlite3
from utils import logger

def fix_production_schema():
    """Fix missing cancel_at_period_end column in production database"""
    db_file = "superbot.db"
    
    try:
        logger.info("Starting production schema fix...")
        
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
        
        # Check if user_id column exists in listings table
        logger.info("Checking listings table schema...")
        c.execute("PRAGMA table_info(listings)")
        columns = [col[1] for col in c.fetchall()]
        
        if 'user_id' not in columns:
            logger.info("Adding missing user_id column to listings table...")
            c.execute("ALTER TABLE listings ADD COLUMN user_id TEXT")
            conn.commit()
            logger.info("[OK] Added user_id column to listings table")
        else:
            logger.info("[OK] user_id column already exists in listings table")
        
        # Check if cancel_at_period_end column exists
        logger.info("Checking subscriptions table schema...")
        c.execute("PRAGMA table_info(subscriptions)")
        columns = [col[1] for col in c.fetchall()]
        
        if 'cancel_at_period_end' not in columns:
            logger.info("Adding missing cancel_at_period_end column...")
            c.execute("ALTER TABLE subscriptions ADD COLUMN cancel_at_period_end BOOLEAN DEFAULT 0")
            conn.commit()
            logger.info("[OK] Added cancel_at_period_end column to subscriptions table")
        else:
            logger.info("[OK] cancel_at_period_end column already exists")
        
        # Verify the fixes
        c.execute("PRAGMA table_info(listings)")
        listings_columns = [col[1] for col in c.fetchall()]
        
        c.execute("PRAGMA table_info(subscriptions)")
        subscriptions_columns = [col[1] for col in c.fetchall()]
        
        if 'user_id' in listings_columns and 'cancel_at_period_end' in subscriptions_columns:
            logger.info("Schema fix completed successfully!")
            logger.info("  - listings.user_id: OK")
            logger.info("  - subscriptions.cancel_at_period_end: OK")
            return True
        else:
            logger.error("Failed to add required columns")
            if 'user_id' not in listings_columns:
                logger.error("  - listings.user_id: MISSING")
            if 'cancel_at_period_end' not in subscriptions_columns:
                logger.error("  - subscriptions.cancel_at_period_end: MISSING")
            return False
            
    except Exception as e:
        logger.error(f"Production schema fix failed: {e}")
        return False
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    print("Fixing Production Schema...")
    success = fix_production_schema()
    if success:
        print("Production schema fixed successfully!")
    else:
        print("Failed to fix production schema")
        sys.exit(1)
