#!/usr/bin/env python3
"""
Automated Backup Scheduler for Super-Bot
Runs daily backups in the background
"""

import schedule
import time
import sys
from pathlib import Path

# Add parent directory to path to import backup_database
sys.path.insert(0, str(Path(__file__).parent))

from backup_database import create_backup, cleanup_old_backups

def daily_backup_job():
    """Daily backup job"""
    print(f"\n{'='*80}")
    print(f"🕐 Scheduled backup started at {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*80}\n")
    
    if create_backup():
        cleanup_old_backups()
        print(f"\n✅ Scheduled backup completed successfully\n")
    else:
        print(f"\n❌ Scheduled backup failed\n")


def main():
    """Main scheduler loop"""
    print("🤖 Super-Bot Automated Backup Scheduler")
    print("=" * 80)
    print("📅 Schedule: Daily at 2:00 AM")
    print("💾 Retention: 7 days")
    print("🔄 Status: Running...")
    print("   Press Ctrl+C to stop\n")
    
    # Schedule daily backup at 2:00 AM
    schedule.every().day.at("02:00").do(daily_backup_job)
    
    # Also run immediately on startup
    print("Running initial backup...")
    daily_backup_job()
    
    # Main loop
    try:
        while True:
            schedule.run_pending()
            time.sleep(60)  # Check every minute
    except KeyboardInterrupt:
        print("\n\n🛑 Backup scheduler stopped by user")
        sys.exit(0)


if __name__ == "__main__":
    main()

