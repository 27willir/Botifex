#!/usr/bin/env python3
"""
Quick Database Lock Fix Script
This script provides immediate fixes for database locking issues.
"""

import sys
import os
import time
import sqlite3
import subprocess
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db_enhanced import get_pool, reset_connection_pool
from utils import logger

def kill_database_connections():
    """Kill any processes that might be holding database connections"""
    try:
        print("Checking for processes holding database connections...")
        
        # Find processes using the database file
        result = subprocess.run(['lsof', 'superbot.db'], capture_output=True, text=True)
        if result.returncode == 0 and result.stdout:
            print("Found processes using database:")
            print(result.stdout)
            
            # Extract PIDs and kill them
            lines = result.stdout.strip().split('\n')[1:]  # Skip header
            for line in lines:
                if line.strip():
                    pid = line.split()[1]
                    try:
                        subprocess.run(['kill', '-9', pid], check=True)
                        print(f"Killed process {pid}")
                    except subprocess.CalledProcessError:
                        print(f"Could not kill process {pid}")
        else:
            print("No processes found using database")
            
    except FileNotFoundError:
        print("lsof command not found - skipping process check")
    except Exception as e:
        print(f"Error checking processes: {e}")

def force_database_unlock():
    """Force unlock the database using SQLite commands"""
    try:
        print("Attempting to force database unlock...")
        
        # Try to connect and force checkpoint
        conn = sqlite3.connect("superbot.db", timeout=1)
        c = conn.cursor()
        
        # Force WAL checkpoint
        c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        result = c.fetchone()
        print(f"WAL checkpoint result: {result}")
        
        # Close connection
        conn.close()
        
        print("✅ Database unlock attempted")
        return True
        
    except sqlite3.OperationalError as e:
        if "database is locked" in str(e).lower():
            print("❌ Database still locked after unlock attempt")
            return False
        else:
            print(f"❌ Database error: {e}")
            return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

def reset_application_connections():
    """Reset all application database connections"""
    try:
        print("Resetting application database connections...")
        reset_connection_pool()
        print("✅ Application connections reset")
        return True
    except Exception as e:
        print(f"❌ Error resetting connections: {e}")
        return False

def backup_and_recreate_database():
    """Last resort: backup and recreate database"""
    try:
        print("⚠️  WARNING: This will backup and recreate the database")
        confirm = input("Are you sure? This may cause data loss (yes/no): ").strip().lower()
        
        if confirm != "yes":
            print("Operation cancelled")
            return False
        
        # Backup current database
        backup_name = f"superbot_backup_{int(time.time())}.db"
        print(f"Creating backup: {backup_name}")
        
        # Copy database file
        import shutil
        shutil.copy2("superbot.db", backup_name)
        print(f"✅ Backup created: {backup_name}")
        
        # Remove WAL and SHM files
        for ext in ['.db-wal', '.db-shm']:
            try:
                os.remove(f"superbot{ext}")
                print(f"Removed {ext} file")
            except FileNotFoundError:
                pass
        
        # Reset connections
        reset_connection_pool()
        
        print("✅ Database recreated")
        return True
        
    except Exception as e:
        print(f"❌ Error recreating database: {e}")
        return False

def quick_fix():
    """Apply quick fixes for database locking"""
    print("Applying quick fixes for database locking...")
    
    # Step 1: Reset application connections
    print("\n1. Resetting application connections...")
    reset_application_connections()
    
    # Step 2: Try to force unlock
    print("\n2. Attempting database unlock...")
    unlock_success = force_database_unlock()
    
    if not unlock_success:
        # Step 3: Kill processes if needed
        print("\n3. Checking for blocking processes...")
        kill_database_connections()
        
        # Try unlock again
        print("\n4. Retrying database unlock...")
        unlock_success = force_database_unlock()
    
    if unlock_success:
        print("\n✅ Database locking issues resolved!")
        return True
    else:
        print("\n❌ Quick fixes failed - manual intervention may be required")
        return False

def main():
    """Main function"""
    print("Database Lock Fix Tool")
    print("=" * 30)
    
    while True:
        print("\nOptions:")
        print("1. Apply quick fixes")
        print("2. Reset application connections")
        print("3. Force database unlock")
        print("4. Kill blocking processes")
        print("5. Backup and recreate database (LAST RESORT)")
        print("6. Exit")
        
        choice = input("\nEnter your choice (1-6): ").strip()
        
        if choice == "1":
            quick_fix()
            
        elif choice == "2":
            reset_application_connections()
            
        elif choice == "3":
            force_database_unlock()
            
        elif choice == "4":
            kill_database_connections()
            
        elif choice == "5":
            backup_and_recreate_database()
            
        elif choice == "6":
            print("Goodbye!")
            break
            
        else:
            print("Invalid choice. Please enter 1-6.")

if __name__ == "__main__":
    main()
