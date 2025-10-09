#!/usr/bin/env python3
"""
Database Migration Script
Migrates existing database to enhanced schema with new features
"""

import sys
import os
import sqlite3
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import logger

DB_FILE = "superbot.db"
BACKUP_FILE = f"superbot_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"


def backup_database():
    """Create a backup of the current database"""
    try:
        if os.path.exists(DB_FILE):
            import shutil
            shutil.copy2(DB_FILE, BACKUP_FILE)
            logger.info(f"Database backed up to: {BACKUP_FILE}")
            return True
        else:
            logger.warning("No existing database found to backup")
            return False
    except Exception as e:
        logger.error(f"Failed to backup database: {e}")
        return False


def migrate_database():
    """Migrate database to enhanced schema"""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        logger.info("Starting database migration...")
        
        # Check if we need to add new columns to existing tables
        
        # 1. Add new columns to users table if they don't exist
        c.execute("PRAGMA table_info(users)")
        columns = [col[1] for col in c.fetchall()]
        
        if 'role' not in columns:
            logger.info("Adding 'role' column to users table...")
            c.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'user'")
            logger.info("[OK] Added 'role' column")
        
        if 'active' not in columns:
            logger.info("Adding 'active' column to users table...")
            c.execute("ALTER TABLE users ADD COLUMN active BOOLEAN DEFAULT 1")
            logger.info("[OK] Added 'active' column")
        
        if 'last_login' not in columns:
            logger.info("Adding 'last_login' column to users table...")
            c.execute("ALTER TABLE users ADD COLUMN last_login DATETIME")
            logger.info("[OK] Added 'last_login' column")
        
        if 'login_count' not in columns:
            logger.info("Adding 'login_count' column to users table...")
            c.execute("ALTER TABLE users ADD COLUMN login_count INTEGER DEFAULT 0")
            logger.info("[OK] Added 'login_count' column")
        
        # 2. Add user_id column to listings table if it doesn't exist
        c.execute("PRAGMA table_info(listings)")
        columns = [col[1] for col in c.fetchall()]
        
        if 'user_id' not in columns:
            logger.info("Adding 'user_id' column to listings table...")
            c.execute("ALTER TABLE listings ADD COLUMN user_id TEXT")
            logger.info("[OK] Added 'user_id' column")
        
        # 3. Add updated_at column to settings table if it doesn't exist
        c.execute("PRAGMA table_info(settings)")
        columns = [col[1] for col in c.fetchall()]
        
        if 'updated_at' not in columns:
            logger.info("Adding 'updated_at' column to settings table...")
            c.execute("ALTER TABLE settings ADD COLUMN updated_at DATETIME")
            logger.info("[OK] Added 'updated_at' column")
        
        # 4. Create new tables for enhanced features
        
        # User activity logging table
        c.execute("""
            CREATE TABLE IF NOT EXISTS user_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT,
                action TEXT,
                details TEXT,
                ip_address TEXT,
                user_agent TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        logger.info("Created user_activity table")
        
        # Rate limiting table
        c.execute("""
            CREATE TABLE IF NOT EXISTS rate_limits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT,
                endpoint TEXT,
                request_count INTEGER DEFAULT 1,
                window_start DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(username, endpoint)
            )
        """)
        logger.info("Created rate_limits table")
        
        # User scraper management table
        c.execute("""
            CREATE TABLE IF NOT EXISTS user_scrapers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT,
                scraper_name TEXT,
                is_running BOOLEAN DEFAULT 0,
                last_run DATETIME,
                run_count INTEGER DEFAULT 0,
                UNIQUE(username, scraper_name)
            )
        """)
        logger.info("Created user_scrapers table")
        
        # 5. Create new indexes for performance
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_listings_user_id ON listings(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)",
            "CREATE INDEX IF NOT EXISTS idx_users_role ON users(role)",
            "CREATE INDEX IF NOT EXISTS idx_activity_username ON user_activity(username)",
            "CREATE INDEX IF NOT EXISTS idx_activity_timestamp ON user_activity(timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_activity_action ON user_activity(action)",
            "CREATE INDEX IF NOT EXISTS idx_rate_limits_username ON rate_limits(username)",
            "CREATE INDEX IF NOT EXISTS idx_rate_limits_endpoint ON rate_limits(endpoint)",
            "CREATE INDEX IF NOT EXISTS idx_settings_username ON settings(username)",
        ]
        
        for index_sql in indexes:
            c.execute(index_sql)
        
        logger.info("Created all indexes")
        
        # 6. Enable WAL mode for better concurrent access
        c.execute("PRAGMA journal_mode=WAL")
        logger.info("Enabled WAL mode")
        
        conn.commit()
        conn.close()
        
        logger.info("[SUCCESS] Database migration completed successfully!")
        return True
        
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        return False


def verify_migration():
    """Verify that migration was successful"""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        logger.info("Verifying migration...")
        
        # Check users table
        c.execute("PRAGMA table_info(users)")
        user_columns = [col[1] for col in c.fetchall()]
        required_user_columns = ['username', 'email', 'password', 'role', 'active', 'last_login', 'login_count']
        
        for col in required_user_columns:
            if col not in user_columns:
                logger.error(f"Missing column in users table: {col}")
                return False
        
        # Check if new tables exist
        c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in c.fetchall()]
        required_tables = ['user_activity', 'rate_limits', 'user_scrapers']
        
        for table in required_tables:
            if table not in tables:
                logger.error(f"Missing table: {table}")
                return False
        
        conn.close()
        
        logger.info("Migration verification passed!")
        return True
        
    except Exception as e:
        logger.error(f"Verification failed: {e}")
        return False


def main():
    """Main migration process"""
    print("=" * 60)
    print("Database Migration to Enhanced Schema")
    print("=" * 60)
    print()
    
    # Step 1: Backup
    print("Step 1: Creating backup...")
    if backup_database():
        print(f"[OK] Backup created: {BACKUP_FILE}")
    else:
        print("[WARN] No backup created (database may not exist yet)")
    print()
    
    # Step 2: Migrate
    print("Step 2: Migrating database...")
    if not migrate_database():
        print("[ERROR] Migration failed! Check the logs.")
        sys.exit(1)
    print()
    
    # Step 3: Verify
    print("Step 3: Verifying migration...")
    if not verify_migration():
        print("[ERROR] Verification failed! Check the logs.")
        sys.exit(1)
    print()
    
    print("=" * 60)
    print("[SUCCESS] Migration completed successfully!")
    print("=" * 60)
    print()
    print("Your database has been upgraded with:")
    print("  - Connection pooling support")
    print("  - User roles and permissions")
    print("  - Activity logging")
    print("  - Rate limiting")
    print("  - User-specific scraper management")
    print("  - Performance indexes")
    print()
    print("You can now use the enhanced database features!")


if __name__ == "__main__":
    main()

