#!/usr/bin/env python3
"""
Monitor 502 Issues
Real-time monitoring script to track and diagnose 502 errors
"""

import os
import sys
import time
import json
from datetime import datetime
from pathlib import Path

# Add the parent directory to the path so we can import our modules
sys.path.append(str(Path(__file__).parent.parent))

from utils import logger
from db_enhanced import get_pool_status

class Monitor502:
    def __init__(self):
        self.start_time = datetime.now()
        self.checks_performed = 0
        self.issues_detected = 0
        
    def check_connection_pool(self):
        """Check connection pool status"""
        try:
            status = get_pool_status()
            utilization = float(status.get('pool_utilization', '0%').replace('%', ''))
            
            if utilization > 80:
                logger.warning(f"⚠️ High pool utilization: {utilization}%")
                self.issues_detected += 1
                return False
            else:
                logger.info(f"✅ Pool utilization: {utilization}%")
                return True
        except Exception as e:
            logger.error(f"❌ Pool check failed: {e}")
            self.issues_detected += 1
            return False
    
    def check_database_file(self):
        """Check database file status"""
        try:
            db_file = "superbot.db"
            if not os.path.exists(db_file):
                logger.error("❌ Database file not found!")
                self.issues_detected += 1
                return False
            
            # Check file size
            file_size = os.path.getsize(db_file)
            if file_size > 100 * 1024 * 1024:  # 100MB
                logger.warning(f"⚠️ Large database file: {file_size / (1024*1024):.2f} MB")
            
            # Check for WAL files
            wal_files = ["superbot.db-wal", "superbot.db-shm"]
            wal_count = sum(1 for f in wal_files if os.path.exists(f))
            if wal_count > 0:
                logger.info(f"📄 WAL files present: {wal_count}")
            
            return True
        except Exception as e:
            logger.error(f"❌ Database file check failed: {e}")
            self.issues_detected += 1
            return False
    
    def check_system_resources(self):
        """Check system resource usage"""
        try:
            import psutil
            
            # Check memory usage
            memory = psutil.virtual_memory()
            if memory.percent > 90:
                logger.warning(f"⚠️ High memory usage: {memory.percent}%")
                self.issues_detected += 1
            else:
                logger.info(f"✅ Memory usage: {memory.percent}%")
            
            # Check CPU usage
            cpu_percent = psutil.cpu_percent(interval=1)
            if cpu_percent > 90:
                logger.warning(f"⚠️ High CPU usage: {cpu_percent}%")
                self.issues_detected += 1
            else:
                logger.info(f"✅ CPU usage: {cpu_percent}%")
            
            return True
        except ImportError:
            logger.info("📊 psutil not available, skipping system resource checks")
            return True
        except Exception as e:
            logger.error(f"❌ System resource check failed: {e}")
            return False
    
    def run_monitoring_cycle(self):
        """Run one monitoring cycle"""
        logger.info(f"🔍 Monitoring cycle #{self.checks_performed + 1}")
        
        # Check connection pool
        pool_ok = self.check_connection_pool()
        
        # Check database file
        db_ok = self.check_database_file()
        
        # Check system resources
        system_ok = self.check_system_resources()
        
        self.checks_performed += 1
        
        # Summary
        if pool_ok and db_ok and system_ok:
            logger.info("✅ All checks passed")
        else:
            logger.warning("⚠️ Some issues detected")
        
        return pool_ok and db_ok and system_ok
    
    def generate_report(self):
        """Generate monitoring report"""
        runtime = datetime.now() - self.start_time
        
        report = {
            "monitoring_start": self.start_time.isoformat(),
            "monitoring_duration": str(runtime),
            "checks_performed": self.checks_performed,
            "issues_detected": self.issues_detected,
            "success_rate": f"{((self.checks_performed - self.issues_detected) / max(self.checks_performed, 1)) * 100:.1f}%"
        }
        
        logger.info("📊 Monitoring Report:")
        logger.info(f"   Duration: {runtime}")
        logger.info(f"   Checks performed: {self.checks_performed}")
        logger.info(f"   Issues detected: {self.issues_detected}")
        logger.info(f"   Success rate: {report['success_rate']}")
        
        return report

def main():
    """Main monitoring function"""
    logger.info("🚀 Starting 502 error monitoring...")
    
    monitor = Monitor502()
    
    try:
        # Run monitoring for 10 cycles (5 minutes with 30s intervals)
        for i in range(10):
            monitor.run_monitoring_cycle()
            if i < 9:  # Don't sleep after the last cycle
                time.sleep(30)
        
        # Generate final report
        report = monitor.generate_report()
        
        # Save report to file
        with open("monitoring_report.json", "w") as f:
            json.dump(report, f, indent=2)
        
        logger.info("📄 Report saved to monitoring_report.json")
        
        if monitor.issues_detected > 0:
            logger.warning("⚠️ Issues detected during monitoring")
            logger.info("💡 Consider running: python scripts/fix_502_errors.py")
        else:
            logger.info("✅ No issues detected - system appears healthy")
        
    except KeyboardInterrupt:
        logger.info("🛑 Monitoring stopped by user")
        report = monitor.generate_report()
    except Exception as e:
        logger.error(f"❌ Monitoring failed: {e}")
        return False
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
