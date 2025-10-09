#!/usr/bin/env python3
"""
Database Backup Script for Super-Bot
Automatically backs up the SQLite database with compression and rotation
"""

import os
import shutil
import gzip
import time
from datetime import datetime, timedelta
from pathlib import Path

# Configuration
DB_FILE = "superbot.db"
BACKUP_DIR = Path("backups")
KEEP_DAYS = 7  # Keep backups for 7 days
MAX_BACKUPS = 30  # Maximum number of backups to keep

def create_backup():
    """Create a compressed backup of the database"""
    # Create backup directory if it doesn't exist
    BACKUP_DIR.mkdir(exist_ok=True)
    
    # Check if database file exists
    db_path = Path(DB_FILE)
    if not db_path.exists():
        print(f"❌ Database file not found: {DB_FILE}")
        return False
    
    # Generate backup filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"superbot_backup_{timestamp}.db.gz"
    backup_path = BACKUP_DIR / backup_filename
    
    try:
        print(f"📦 Creating backup: {backup_filename}")
        
        # Read the database file and compress it
        with open(db_path, 'rb') as f_in:
            with gzip.open(backup_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        
        # Get file sizes
        original_size = db_path.stat().st_size / (1024 * 1024)  # MB
        compressed_size = backup_path.stat().st_size / (1024 * 1024)  # MB
        compression_ratio = (1 - compressed_size / original_size) * 100
        
        print(f"✅ Backup created successfully!")
        print(f"   Original size: {original_size:.2f} MB")
        print(f"   Compressed size: {compressed_size:.2f} MB")
        print(f"   Compression: {compression_ratio:.1f}%")
        print(f"   Location: {backup_path}")
        
        return True
    
    except Exception as e:
        print(f"❌ Error creating backup: {e}")
        return False


def cleanup_old_backups():
    """Remove backups older than KEEP_DAYS"""
    if not BACKUP_DIR.exists():
        return
    
    print(f"\n🧹 Cleaning up old backups (keeping last {KEEP_DAYS} days)...")
    
    cutoff_date = datetime.now() - timedelta(days=KEEP_DAYS)
    removed_count = 0
    
    # Get all backup files
    backup_files = sorted(BACKUP_DIR.glob("superbot_backup_*.db.gz"))
    
    # Keep only the most recent MAX_BACKUPS files
    if len(backup_files) > MAX_BACKUPS:
        files_to_remove = backup_files[:-MAX_BACKUPS]
        for backup_file in files_to_remove:
            try:
                backup_file.unlink()
                removed_count += 1
                print(f"   Removed (max backups): {backup_file.name}")
            except Exception as e:
                print(f"   Error removing {backup_file.name}: {e}")
    
    # Remove old backups based on date
    for backup_file in BACKUP_DIR.glob("superbot_backup_*.db.gz"):
        try:
            # Parse timestamp from filename
            timestamp_str = backup_file.stem.replace("superbot_backup_", "").replace(".db", "")
            backup_date = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
            
            if backup_date < cutoff_date:
                backup_file.unlink()
                removed_count += 1
                print(f"   Removed (old): {backup_file.name}")
        
        except (ValueError, OSError) as e:
            print(f"   Warning: Could not process {backup_file.name}: {e}")
    
    if removed_count > 0:
        print(f"✅ Removed {removed_count} old backup(s)")
    else:
        print(f"✅ No old backups to remove")


def list_backups():
    """List all available backups"""
    if not BACKUP_DIR.exists():
        print("No backups directory found")
        return
    
    backup_files = sorted(BACKUP_DIR.glob("superbot_backup_*.db.gz"), reverse=True)
    
    if not backup_files:
        print("No backups found")
        return
    
    print(f"\n📋 Available backups ({len(backup_files)}):")
    print("-" * 80)
    
    for backup_file in backup_files:
        try:
            # Get file size
            size_mb = backup_file.stat().st_size / (1024 * 1024)
            
            # Parse timestamp from filename
            timestamp_str = backup_file.stem.replace("superbot_backup_", "").replace(".db", "")
            backup_date = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
            date_str = backup_date.strftime("%Y-%m-%d %H:%M:%S")
            
            # Calculate age
            age = datetime.now() - backup_date
            if age.days > 0:
                age_str = f"{age.days}d ago"
            elif age.seconds >= 3600:
                age_str = f"{age.seconds // 3600}h ago"
            else:
                age_str = f"{age.seconds // 60}m ago"
            
            print(f"   {backup_file.name}")
            print(f"      Date: {date_str} ({age_str}) | Size: {size_mb:.2f} MB")
        
        except Exception as e:
            print(f"   {backup_file.name} (error reading details: {e})")


def restore_backup(backup_filename):
    """Restore a backup file"""
    backup_path = BACKUP_DIR / backup_filename
    
    if not backup_path.exists():
        print(f"❌ Backup file not found: {backup_filename}")
        return False
    
    # Create a backup of the current database before restoring
    current_db = Path(DB_FILE)
    if current_db.exists():
        safety_backup = current_db.parent / f"{DB_FILE}.before_restore"
        try:
            shutil.copy2(current_db, safety_backup)
            print(f"📦 Created safety backup: {safety_backup.name}")
        except Exception as e:
            print(f"❌ Could not create safety backup: {e}")
            return False
    
    try:
        print(f"♻️  Restoring backup: {backup_filename}")
        
        # Decompress and restore
        with gzip.open(backup_path, 'rb') as f_in:
            with open(current_db, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        
        print(f"✅ Database restored successfully from {backup_filename}")
        print(f"   Safety backup saved as: {safety_backup.name}")
        return True
    
    except Exception as e:
        print(f"❌ Error restoring backup: {e}")
        # Try to restore the safety backup
        if safety_backup.exists():
            try:
                shutil.copy2(safety_backup, current_db)
                print(f"♻️  Restored original database from safety backup")
            except:
                pass
        return False


def main():
    """Main function"""
    import sys
    
    if len(sys.argv) < 2:
        # Default action: create backup and cleanup
        print("🚀 Super-Bot Database Backup Tool")
        print("=" * 80)
        
        if create_backup():
            cleanup_old_backups()
            list_backups()
        
    elif sys.argv[1] == "list":
        list_backups()
    
    elif sys.argv[1] == "restore":
        if len(sys.argv) < 3:
            print("❌ Usage: python backup_database.py restore <backup_filename>")
            print("\nAvailable backups:")
            list_backups()
        else:
            restore_backup(sys.argv[2])
    
    elif sys.argv[1] == "cleanup":
        cleanup_old_backups()
        list_backups()
    
    else:
        print("❌ Unknown command")
        print("\nUsage:")
        print("  python backup_database.py          - Create backup and cleanup")
        print("  python backup_database.py list     - List all backups")
        print("  python backup_database.py restore <filename> - Restore a backup")
        print("  python backup_database.py cleanup  - Remove old backups")


if __name__ == "__main__":
    main()

