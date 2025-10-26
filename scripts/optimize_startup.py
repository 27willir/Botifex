#!/usr/bin/env python3
"""
Optimize application startup for production deployment
Reduces timeout issues by optimizing database and connection settings
"""

import os
import sys
import sqlite3
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from utils import logger
from db_enhanced import get_pool, init_db

def optimize_database():
    """Optimize database for production performance"""
    try:
        logger.info("Optimizing database for production...")
        
        # Initialize database with optimized settings
        init_db()
        
        # Get connection pool
        pool = get_pool()
        
        with pool.get_connection() as conn:
            c = conn.cursor()
            
            # Optimize database settings for production
            optimizations = [
                "PRAGMA journal_mode=WAL",
                "PRAGMA synchronous=NORMAL", 
                "PRAGMA cache_size=20000",
                "PRAGMA temp_store=MEMORY",
                "PRAGMA mmap_size=268435456",
                "PRAGMA busy_timeout=2000",
                "PRAGMA foreign_keys=ON",
                "PRAGMA read_uncommitted=1",
                "PRAGMA locking_mode=NORMAL",
                "PRAGMA wal_autocheckpoint=1000",
                "PRAGMA optimize"
            ]
            
            for pragma in optimizations:
                try:
                    c.execute(pragma)
                except sqlite3.OperationalError as e:
                    logger.warning(f"Failed to set {pragma}: {e}")
            
            # Create indexes for better performance
            indexes = [
                "CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)",
                "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)",
                "CREATE INDEX IF NOT EXISTS idx_user_activity_username ON user_activity(username)",
                "CREATE INDEX IF NOT EXISTS idx_user_activity_timestamp ON user_activity(timestamp)",
                "CREATE INDEX IF NOT EXISTS idx_listings_created_at ON listings(created_at)",
                "CREATE INDEX IF NOT EXISTS idx_listings_source ON listings(source)"
            ]
            
            for index_sql in indexes:
                try:
                    c.execute(index_sql)
                except sqlite3.OperationalError as e:
                    logger.warning(f"Failed to create index: {e}")
            
            conn.commit()
            logger.info("Database optimization completed")
            
    except Exception as e:
        logger.error(f"Failed to optimize database: {e}")
        raise

def optimize_environment():
    """Set environment variables for optimal performance"""
    os.environ.setdefault('WEB_CONCURRENCY', '2')
    os.environ.setdefault('GUNICORN_WORKER_CLASS', 'gevent')
    os.environ.setdefault('LOG_LEVEL', 'info')
    os.environ.setdefault('PYTHONUNBUFFERED', '1')
    
    logger.info("Environment variables optimized for production")

def main():
    """Main optimization function"""
    try:
        logger.info("Starting application optimization...")
        
        # Optimize environment
        optimize_environment()
        
        # Optimize database
        optimize_database()
        
        logger.info("Application optimization completed successfully")
        
    except Exception as e:
        logger.error(f"Optimization failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
