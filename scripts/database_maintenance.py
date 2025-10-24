#!/usr/bin/env python3
"""
Database Maintenance Script for Production
This script performs regular maintenance to prevent locking issues
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlite3
import time
from datetime import datetime, timedelta
from utils import logger

def perform_database_maintenance():
    """Perform database maintenance to prevent locking issues"""
    db_file = "superbot.db"
    
    try:
        logger.info("Starting database maintenance...")
        
        # Connect to database
        conn = sqlite3.connect(
            db_file,
            timeout=30,
            check_same_thread=False
        )
        
        # Set maintenance-optimized settings
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=30000")  # 30 second timeout for maintenance
        
        c = conn.cursor()
        
        # 1. Analyze database for better query planning
        logger.info("Analyzing database for query optimization...")
        c.execute("ANALYZE")
        
        # 2. Clean up old security events (older than 30 days)
        logger.info("Cleaning up old security events...")
        cutoff_date = datetime.now() - timedelta(days=30)
        c.execute("DELETE FROM security_events WHERE timestamp < ?", (cutoff_date,))
        deleted_events = c.rowcount
        logger.info(f"Deleted {deleted_events} old security events")
        
        # 3. Clean up old rate limit records (older than 1 day)
        logger.info("Cleaning up old rate limit records...")
        cutoff_date = datetime.now() - timedelta(days=1)
        c.execute("DELETE FROM rate_limits WHERE window_start < ?", (cutoff_date,))
        deleted_limits = c.rowcount
        logger.info(f"Deleted {deleted_limits} old rate limit records")
        
        # 4. Clean up old user activity (older than 90 days)
        logger.info("Cleaning up old user activity...")
        cutoff_date = datetime.now() - timedelta(days=90)
        c.execute("DELETE FROM user_activity WHERE timestamp < ?", (cutoff_date,))
        deleted_activity = c.rowcount
        logger.info(f"Deleted {deleted_activity} old user activity records")
        
        # 5. Optimize database
        logger.info("Optimizing database...")
        c.execute("PRAGMA optimize")
        
        # 6. Check database integrity
        logger.info("Checking database integrity...")
        c.execute("PRAGMA integrity_check")
        integrity_result = c.fetchone()[0]
        
        if integrity_result == "ok":
            logger.info("✅ Database integrity check passed")
        else:
            logger.warning(f"⚠️ Database integrity check result: {integrity_result}")
        
        # 7. Get database statistics
        c.execute("SELECT COUNT(*) FROM security_events")
        security_count = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM rate_limits")
        rate_limit_count = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM user_activity")
        activity_count = c.fetchone()[0]
        
        logger.info(f"Database statistics:")
        logger.info(f"  Security events: {security_count}")
        logger.info(f"  Rate limits: {rate_limit_count}")
        logger.info(f"  User activity: {activity_count}")
        
        # 8. Perform WAL checkpoint
        logger.info("Performing WAL checkpoint...")
        c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        
        # Commit all changes
        conn.commit()
        conn.close()
        
        logger.info("✅ Database maintenance completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"❌ Database maintenance failed: {e}")
        return False

def check_database_health():
    """Check database health and report issues"""
    db_file = "superbot.db"
    
    try:
        conn = sqlite3.connect(db_file, timeout=10)
        c = conn.cursor()
        
        # Check if all required tables exist
        required_tables = ['security_events', 'rate_limits', 'users', 'listings', 'user_activity']
        c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        existing_tables = [row[0] for row in c.fetchall()]
        
        missing_tables = [table for table in required_tables if table not in existing_tables]
        
        if missing_tables:
            logger.warning(f"Missing tables: {missing_tables}")
            return False
        
        # Check database size
        c.execute("PRAGMA page_count")
        page_count = c.fetchone()[0]
        c.execute("PRAGMA page_size")
        page_size = c.fetchone()[0]
        db_size_mb = (page_count * page_size) / (1024 * 1024)
        
        logger.info(f"Database size: {db_size_mb:.2f} MB")
        
        # Check WAL file size
        try:
            wal_size = os.path.getsize(db_file + "-wal") / (1024 * 1024)
            logger.info(f"WAL file size: {wal_size:.2f} MB")
        except FileNotFoundError:
            logger.info("No WAL file found (normal for new databases)")
        
        conn.close()
        return True
        
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False

if __name__ == "__main__":
    print("🔧 Database Maintenance Script")
    print("=" * 50)
    
    # Check database health
    print("Checking database health...")
    health_ok = check_database_health()
    
    if health_ok:
        print("✅ Database health check passed")
    else:
        print("⚠️ Database health check found issues")
    
    # Perform maintenance
    print("\nPerforming database maintenance...")
    maintenance_success = perform_database_maintenance()
    
    if maintenance_success:
        print("✅ Database maintenance completed successfully!")
    else:
        print("❌ Database maintenance failed!")
        sys.exit(1)