#!/usr/bin/env python3
"""
SQLite to PostgreSQL Migration Script
Exports data from SQLite and imports into PostgreSQL to preserve user logins
"""

import os
import sys
import sqlite3
from pathlib import Path


def _to_bool(value):
    """Convert SQLite truthy values to Python booleans for PostgreSQL."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "t", "yes", "y"}
    return bool(value)

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

def migrate_users_only():
    """Migrate only user accounts to preserve logins"""
    sqlite_db = "superbot.db"
    database_url = os.getenv('DATABASE_URL', '')
    
    if not database_url or not database_url.startswith(('postgres://', 'postgresql://')):
        print("❌ ERROR: DATABASE_URL not set or not PostgreSQL")
        print("   Set DATABASE_URL environment variable to your PostgreSQL connection string")
        return False
    
    if not Path(sqlite_db).exists():
        print(f"❌ ERROR: SQLite database not found: {sqlite_db}")
        return False
    
    try:
        import psycopg2
        from urllib.parse import urlparse, parse_qs
    except ImportError:
        print("❌ ERROR: psycopg2 not installed")
        print("   Install with: pip install psycopg2-binary")
        return False
    
    print("🚀 Starting migration from SQLite to PostgreSQL...")
    print("=" * 80)
    
    # Connect to SQLite
    print(f"📖 Reading from SQLite: {sqlite_db}")
    sqlite_conn = sqlite3.connect(sqlite_db)
    sqlite_cur = sqlite_conn.cursor()
    
    # Connect to PostgreSQL
    print(f"📝 Writing to PostgreSQL")
    pg_conn = psycopg2.connect(database_url)
    pg_cur = pg_conn.cursor()
    
    try:
        # Initialize PostgreSQL schema first
        print("\n📋 Initializing PostgreSQL schema...")
        from db_enhanced import init_db
        init_db()
        print("✅ Schema initialized")
        
        # Migrate users table
        print("\n👥 Migrating users...")
        sqlite_cur.execute("SELECT username, email, password, verified, role, active, created_at, last_login, login_count, email_notifications, sms_notifications FROM users")
        users = sqlite_cur.fetchall()
        
        migrated_users = 0
        if not users:
            print("   No users found to migrate")
        else:
            print(f"   Found {len(users)} users to migrate")
            for user in users:
                username, email, password, verified, role, active, created_at, last_login, login_count, email_notifications, sms_notifications = user
                payload = (
                    username,
                    email,
                    password,
                    _to_bool(verified),
                    role or 'user',
                    _to_bool(active),
                    created_at,
                    last_login,
                    login_count or 0,
                    _to_bool(email_notifications),
                    _to_bool(sms_notifications),
                )
                try:
                    pg_cur.execute("""
                        INSERT INTO users (username, email, password, verified, role, active, created_at, last_login, login_count, email_notifications, sms_notifications)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (username) DO UPDATE SET
                            email = EXCLUDED.email,
                            password = EXCLUDED.password,
                            verified = EXCLUDED.verified,
                            role = EXCLUDED.role,
                            active = EXCLUDED.active,
                            last_login = EXCLUDED.last_login,
                            login_count = EXCLUDED.login_count,
                            email_notifications = EXCLUDED.email_notifications,
                            sms_notifications = EXCLUDED.sms_notifications
                    """, payload)
                    pg_conn.commit()
                    migrated_users += 1
                except Exception as e:
                    pg_conn.rollback()
                    print(f"   ⚠️  Error migrating user {username}: {e}")
            
            print(f"   ✅ Migrated {migrated_users} users")
        
        # Migrate settings
        print("\n⚙️  Migrating user settings...")
        sqlite_cur.execute("SELECT username, key, value, updated_at FROM settings")
        settings = sqlite_cur.fetchall()
        
        if settings:
            print(f"   Found {len(settings)} settings to migrate")
            for setting in settings:
                try:
                    pg_cur.execute("""
                        INSERT INTO settings (username, key, value, updated_at)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (username, key) DO UPDATE SET
                            value = EXCLUDED.value,
                            updated_at = EXCLUDED.updated_at
                    """, setting)
                    pg_conn.commit()
                except Exception as e:
                    pg_conn.rollback()
                    print(f"   ⚠️  Error migrating settings for {setting[0]}: {e}")
            print(f"   ✅ Migrated {len(settings)} settings")
        
        # Migrate subscriptions
        print("\n💳 Migrating subscriptions...")
        sqlite_cur.execute("SELECT username, tier, status, stripe_customer_id, stripe_subscription_id, current_period_start, current_period_end, cancel_at_period_end, created_at, updated_at FROM subscriptions")
        subscriptions = sqlite_cur.fetchall()
        
        if subscriptions:
            print(f"   Found {len(subscriptions)} subscriptions to migrate")
            for sub in subscriptions:
                try:
                    pg_cur.execute("""
                        INSERT INTO subscriptions (username, tier, status, stripe_customer_id, stripe_subscription_id, current_period_start, current_period_end, cancel_at_period_end, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (username) DO UPDATE SET
                            tier = EXCLUDED.tier,
                            status = EXCLUDED.status,
                            stripe_customer_id = EXCLUDED.stripe_customer_id,
                            stripe_subscription_id = EXCLUDED.stripe_subscription_id,
                            current_period_start = EXCLUDED.current_period_start,
                            current_period_end = EXCLUDED.current_period_end,
                            cancel_at_period_end = EXCLUDED.cancel_at_period_end,
                            updated_at = EXCLUDED.updated_at
                    """, (
                        sub[0],
                        sub[1],
                        sub[2],
                        sub[3],
                        sub[4],
                        sub[5],
                        sub[6],
                        _to_bool(sub[7]),
                        sub[8],
                        sub[9],
                    ))
                    pg_conn.commit()
                except Exception as e:
                    pg_conn.rollback()
                    print(f"   ⚠️  Error migrating subscription for {sub[0]}: {e}")
            print(f"   ✅ Migrated {len(subscriptions)} subscriptions")
        
        # Commit all changes
        pg_conn.commit()
        
        print("\n" + "=" * 80)
        print("✅ Migration completed successfully!")
        print(f"   Users migrated: {migrated_users}")
        print("   Your user logins and data are now in PostgreSQL")
        print("   Data will persist across deployments!")
        return True
        
    except Exception as e:
        pg_conn.rollback()
        print(f"\n❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        sqlite_conn.close()
        pg_conn.close()


if __name__ == "__main__":
    print("🔄 SQLite to PostgreSQL Migration Tool")
    print("=" * 80)
    print("\nThis script will migrate your user accounts and settings from SQLite to PostgreSQL")
    print("to preserve user logins across deployments.\n")
    
    if migrate_users_only():
        print("\n✅ Migration successful! Your users can now log in with PostgreSQL.")
    else:
        print("\n❌ Migration failed. Please check the errors above.")
        sys.exit(1)

