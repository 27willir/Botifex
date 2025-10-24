#!/usr/bin/env python3
"""
Database Maintenance and Monitoring Script
This script helps monitor and maintain database health to prevent locking issues.
"""

import sys
import os
import time
import sqlite3
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db_enhanced import get_pool, reset_connection_pool
from utils import logger

def check_database_locks():
    """Check for active database locks"""
    try:
        with get_pool().get_connection() as conn:
            c = conn.cursor()
            # Check for active connections
            c.execute("PRAGMA database_list")
            databases = c.fetchall()
            
            # Check WAL file status
            c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            wal_info = c.fetchone()
            
            print("Database Status:")
            print(f"  Active databases: {len(databases)}")
            print(f"  WAL checkpoint: {wal_info}")
            
            return True
    except sqlite3.OperationalError as e:
        if "database is locked" in str(e).lower():
            print("❌ Database is currently locked")
            return False
        else:
            print(f"❌ Database error: {e}")
            return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

def analyze_connection_pool():
    """Analyze connection pool status"""
    try:
        pool = get_pool()
        status = {
            'pool_size': pool.pool_size,
            'available_connections': pool.pool.qsize(),
            'total_connections': len(pool.all_connections)
        }
        
        print("Connection Pool Status:")
        print(f"  Pool size: {status['pool_size']}")
        print(f"  Available connections: {status['available_connections']}")
        print(f"  Total connections: {status['total_connections']}")
        
        if status['available_connections'] < status['pool_size'] * 0.1:
            print("⚠️  Warning: Connection pool is nearly exhausted")
            return False
        
        return True
    except Exception as e:
        print(f"❌ Error analyzing connection pool: {e}")
        return False

def check_long_running_queries():
    """Check for long-running queries that might be causing locks"""
    try:
        with get_pool().get_connection() as conn:
            c = conn.cursor()
            
            # Check for active transactions
            c.execute("SELECT * FROM sqlite_master WHERE type='table'")
            tables = c.fetchall()
            
            print(f"Database tables: {len(tables)}")
            
            # Check rate_limits table size
            c.execute("SELECT COUNT(*) FROM rate_limits")
            rate_limit_count = c.fetchone()[0]
            print(f"Rate limit entries: {rate_limit_count}")
            
            if rate_limit_count > 10000:
                print("⚠️  Warning: Large number of rate limit entries may cause performance issues")
                return False
            
            return True
    except Exception as e:
        print(f"❌ Error checking queries: {e}")
        return False

def optimize_database():
    """Run database optimization"""
    try:
        with get_pool().get_connection() as conn:
            c = conn.cursor()
            
            print("Running database optimization...")
            
            # Analyze tables for better query planning
            c.execute("ANALYZE")
            
            # Optimize database
            c.execute("PRAGMA optimize")
            
            # Checkpoint WAL file
            c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            
            # Update statistics
            c.execute("PRAGMA analysis_limit=1000")
            
            print("✅ Database optimization completed")
            return True
    except Exception as e:
        print(f"❌ Error optimizing database: {e}")
        return False

def cleanup_old_data():
    """Clean up old data that might be causing issues"""
    try:
        with get_pool().get_connection() as conn:
            c = conn.cursor()
            
            print("Cleaning up old data...")
            
            # Clean up old rate limits (older than 1 hour)
            c.execute("""
                DELETE FROM rate_limits 
                WHERE datetime(window_start) < datetime('now', '-1 hour')
            """)
            deleted_rate_limits = c.rowcount
            
            # Clean up old sessions (if you have a sessions table)
            # c.execute("DELETE FROM sessions WHERE expires_at < datetime('now')")
            
            conn.commit()
            
            print(f"✅ Cleaned up {deleted_rate_limits} old rate limit entries")
            return True
    except Exception as e:
        print(f"❌ Error cleaning up data: {e}")
        return False

def reset_database_connections():
    """Reset all database connections"""
    try:
        print("Resetting database connections...")
        reset_connection_pool()
        print("✅ Database connections reset")
        return True
    except Exception as e:
        print(f"❌ Error resetting connections: {e}")
        return False

def monitor_database_health():
    """Continuous database health monitoring"""
    print("Starting database health monitoring...")
    print("Press Ctrl+C to stop")
    
    try:
        while True:
            print(f"\n--- Database Health Check at {time.strftime('%Y-%m-%d %H:%M:%S')} ---")
            
            # Check database locks
            lock_status = check_database_locks()
            
            # Analyze connection pool
            pool_status = analyze_connection_pool()
            
            # Check queries
            query_status = check_long_running_queries()
            
            # Overall health
            if lock_status and pool_status and query_status:
                print("✅ Database is healthy")
            else:
                print("⚠️  Database issues detected")
            
            time.sleep(30)  # Check every 30 seconds
            
    except KeyboardInterrupt:
        print("\nMonitoring stopped")

def main():
    """Main function with interactive menu"""
    print("Database Maintenance Tool")
    print("=" * 40)
    
    while True:
        print("\nOptions:")
        print("1. Check database health")
        print("2. Analyze connection pool")
        print("3. Optimize database")
        print("4. Clean up old data")
        print("5. Reset database connections")
        print("6. Start health monitoring")
        print("7. Exit")
        
        choice = input("\nEnter your choice (1-7): ").strip()
        
        if choice == "1":
            print("\n--- Database Health Check ---")
            check_database_locks()
            analyze_connection_pool()
            check_long_running_queries()
            
        elif choice == "2":
            print("\n--- Connection Pool Analysis ---")
            analyze_connection_pool()
            
        elif choice == "3":
            print("\n--- Database Optimization ---")
            optimize_database()
            
        elif choice == "4":
            print("\n--- Data Cleanup ---")
            cleanup_old_data()
            
        elif choice == "5":
            print("\n--- Connection Reset ---")
            reset_database_connections()
            
        elif choice == "6":
            print("\n--- Health Monitoring ---")
            monitor_database_health()
            
        elif choice == "7":
            print("Goodbye!")
            break
            
        else:
            print("Invalid choice. Please enter 1-7.")

if __name__ == "__main__":
    main()
