#!/usr/bin/env python3
"""
Fix 502 Bad Gateway Errors
This script addresses the root causes of 502 errors and timeouts
"""

import os
import sys
import sqlite3
import time
import subprocess
from pathlib import Path

# Add the parent directory to the path so we can import our modules
sys.path.append(str(Path(__file__).parent.parent))

from utils import logger
from db_enhanced import get_pool_status, maintain_database, cleanup_old_connections

def check_database_health():
    """Check database health and connection pool status"""
    logger.info("🔍 Checking database health...")
    
    try:
        # Check pool status
        pool_status = get_pool_status()
        logger.info(f"📊 Connection Pool Status: {pool_status}")
        
        # Check database file
        db_file = "superbot.db"
        if os.path.exists(db_file):
            file_size = os.path.getsize(db_file)
            logger.info(f"📁 Database file size: {file_size / (1024*1024):.2f} MB")
        else:
            logger.error("❌ Database file not found!")
            return False
            
        # Test database connection
        conn = sqlite3.connect(db_file, timeout=5)
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        result = cursor.fetchone()
        conn.close()
        
        if result:
            logger.info("✅ Database connection test passed")
            return True
        else:
            logger.error("❌ Database connection test failed")
            return False
            
    except Exception as e:
        logger.error(f"❌ Database health check failed: {e}")
        return False

def fix_database_locks():
    """Fix database locking issues"""
    logger.info("🔧 Fixing database locks...")
    
    try:
        # Remove WAL files if they exist
        wal_files = ["superbot.db-wal", "superbot.db-shm"]
        for wal_file in wal_files:
            if os.path.exists(wal_file):
                os.remove(wal_file)
                logger.info(f"🗑️ Removed {wal_file}")
        
        # Run database maintenance
        maintain_database()
        
        # Clean up old connections
        cleanup_old_connections()
        
        logger.info("✅ Database lock fixes applied")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to fix database locks: {e}")
        return False

def check_gunicorn_config():
    """Check and fix gunicorn configuration"""
    logger.info("🔧 Checking gunicorn configuration...")
    
    config_file = "gunicorn_config.py"
    if not os.path.exists(config_file):
        logger.error(f"❌ {config_file} not found!")
        return False
    
    # Check if timeout is reasonable
    with open(config_file, 'r') as f:
        content = f.read()
        if 'timeout = 60' in content:
            logger.info("✅ Gunicorn timeout is properly configured (60s)")
        elif 'timeout = 30' in content:
            logger.warning("⚠️ Gunicorn timeout is too low (30s), should be 60s")
        else:
            logger.warning("⚠️ Gunicorn timeout configuration unclear")
    
    return True

def restart_application():
    """Restart the application if needed"""
    logger.info("🔄 Checking if application restart is needed...")
    
    # Check if we're in a production environment
    if os.getenv('FLASK_ENV') == 'production' or os.getenv('ENVIRONMENT') == 'production':
        logger.info("🚀 Production environment detected - restart may be needed")
        logger.info("💡 Consider restarting your application server (gunicorn/uwsgi)")
        return True
    else:
        logger.info("🏠 Development environment - manual restart not needed")
        return True

def run_health_monitoring():
    """Run continuous health monitoring"""
    logger.info("📊 Starting health monitoring...")
    
    for i in range(5):  # Monitor for 5 cycles
        logger.info(f"📈 Health check cycle {i+1}/5")
        
        # Check database health
        db_healthy = check_database_health()
        
        # Check pool status
        pool_status = get_pool_status()
        logger.info(f"📊 Pool status: {pool_status}")
        
        if not db_healthy:
            logger.warning("⚠️ Database health issues detected")
            fix_database_locks()
        
        time.sleep(10)  # Wait 10 seconds between checks
    
    logger.info("✅ Health monitoring completed")

def main():
    """Main function"""
    logger.info("🚀 Starting 502 error diagnosis and fixes...")
    
    # Step 1: Check database health
    if not check_database_health():
        logger.error("❌ Database health check failed")
        return False
    
    # Step 2: Fix database locks
    if not fix_database_locks():
        logger.error("❌ Failed to fix database locks")
        return False
    
    # Step 3: Check gunicorn config
    if not check_gunicorn_config():
        logger.error("❌ Gunicorn configuration issues")
        return False
    
    # Step 4: Run health monitoring
    run_health_monitoring()
    
    # Step 5: Restart recommendation
    restart_application()
    
    logger.info("✅ 502 error fixes completed!")
    logger.info("💡 If issues persist, consider:")
    logger.info("   1. Increasing connection pool size")
    logger.info("   2. Switching to PostgreSQL for production")
    logger.info("   3. Adding Redis for session storage")
    logger.info("   4. Implementing request queuing")
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
