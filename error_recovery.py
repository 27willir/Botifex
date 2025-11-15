# error_recovery.py
"""
Error recovery and monitoring system for the super-bot application.
Provides automatic recovery mechanisms, health monitoring, and graceful degradation.
"""

import time
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Callable, Any
from utils import logger
from error_handling import ErrorHandler, ScraperError, NetworkError, DatabaseError

class HealthMonitor:
    """Monitor system health and trigger recovery actions."""
    
    def __init__(self):
        self.health_status = {
            "database": {"status": "healthy", "last_check": None, "error_count": 0},
            "network": {"status": "healthy", "last_check": None, "error_count": 0},
            "scrapers": {"status": "healthy", "last_check": None, "error_count": 0}
        }
        self.recovery_actions = []
        self.monitoring = False
        self.monitor_thread = None
    
    def start_monitoring(self):
        """Start the health monitoring system."""
        if not self.monitoring:
            self.monitoring = True
            self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self.monitor_thread.start()
            logger.info("Health monitoring started")
    
    def stop_monitoring(self):
        """Stop the health monitoring system."""
        self.monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        logger.info("Health monitoring stopped")
    
    def _monitor_loop(self):
        """Main monitoring loop."""
        while self.monitoring:
            try:
                self._check_database_health()
                self._check_network_health()
                self._check_scraper_health()
                time.sleep(30)  # Check every 30 seconds
            except Exception as e:
                logger.error(f"Error in health monitoring: {e}")
                time.sleep(60)  # Wait longer on error
    
    def _check_database_health(self):
        """Check database connectivity and performance."""
        try:
            from db_enhanced import get_pool
            # Simple database health check without reinitializing
            pool = get_pool()
            with pool.get_connection() as conn:
                cursor = conn.cursor()
                try:
                    cursor.execute("SELECT 1")
                    cursor.fetchone()
                finally:
                    try:
                        cursor.close()
                    except Exception:
                        pass
            self.health_status["database"]["status"] = "healthy"
            self.health_status["database"]["last_check"] = datetime.now()
            self.health_status["database"]["error_count"] = 0
        except Exception as e:
            self.health_status["database"]["status"] = "unhealthy"
            self.health_status["database"]["error_count"] += 1
            logger.warning(f"Database health check failed: {e}")
    
    def _check_network_health(self):
        """Check network connectivity."""
        try:
            import requests
            # Try multiple endpoints for better reliability
            endpoints = [
                "https://httpbin.org/status/200",
                "https://www.google.com",
                "https://www.cloudflare.com"
            ]
            
            for endpoint in endpoints:
                try:
                    response = requests.get(endpoint, timeout=5)
                    if response.status_code in [200, 301, 302]:  # Accept redirects as healthy
                        self.health_status["network"]["status"] = "healthy"
                        self.health_status["network"]["last_check"] = datetime.now()
                        self.health_status["network"]["error_count"] = 0
                        return
                except Exception:
                    continue
            
            # If all endpoints fail, mark as unhealthy
            raise Exception("All network endpoints failed")
            
        except Exception as e:
            self.health_status["network"]["status"] = "unhealthy"
            self.health_status["network"]["error_count"] += 1
            logger.warning(f"Network health check failed: {e}")
    
    def _check_scraper_health(self):
        """Check scraper system health."""
        try:
            from scraper_thread import get_system_stats
            stats = get_system_stats()
            # Check if any scrapers are running system-wide
            if stats['total_scrapers'] > 0:
                self.health_status["scrapers"]["status"] = "healthy"
                self.health_status["scrapers"]["last_check"] = datetime.now()
                self.health_status["scrapers"]["error_count"] = 0
            else:
                self.health_status["scrapers"]["status"] = "idle"
        except Exception as e:
            self.health_status["scrapers"]["status"] = "unhealthy"
            self.health_status["scrapers"]["error_count"] += 1
            logger.warning(f"Scraper health check failed: {e}")
    
    def get_health_status(self) -> Dict:
        """Get current health status."""
        return self.health_status.copy()
    
    def is_healthy(self) -> bool:
        """Check if system is overall healthy."""
        return all(
            status["status"] in ["healthy", "idle"] 
            for status in self.health_status.values()
        )

class RecoveryManager:
    """Manage automatic recovery actions."""
    
    def __init__(self):
        self.recovery_strategies = {
            "database": self._recover_database,
            "network": self._recover_network,
            "scrapers": self._recover_scrapers
        }
        self.recovery_history = []
    
    def attempt_recovery(self, component: str, error: Exception) -> bool:
        """Attempt to recover from an error."""
        try:
            if component in self.recovery_strategies:
                success = self.recovery_strategies[component](error)
                self.recovery_history.append({
                    "component": component,
                    "error": str(error),
                    "success": success,
                    "timestamp": datetime.now()
                })
                return success
            return False
        except Exception as e:
            logger.error(f"Recovery attempt failed for {component}: {e}")
            return False
    
    def _recover_database(self, error: Exception) -> bool:
        """Recover from database errors."""
        try:
            logger.info("Attempting database recovery...")
            from db_enhanced import init_db, maintain_database, cleanup_old_connections, reset_connection_pool
            
            # Clean up old connections first
            cleanup_old_connections()
            
            # Perform database maintenance
            maintain_database()
            
            # If still having issues, reset the entire connection pool
            if "database is locked" in str(error).lower():
                logger.warning("Persistent locking detected, resetting connection pool")
                reset_connection_pool()
            
            # Reinitialize database if needed
            init_db()
            
            logger.info("Database recovery successful")
            return True
        except Exception as e:
            logger.error(f"Database recovery failed: {e}")
            return False
    
    def _recover_network(self, error: Exception) -> bool:
        """Recover from network errors."""
        try:
            logger.info("Attempting network recovery...")
            # Wait and retry
            time.sleep(5)
            import requests
            
            # Try multiple endpoints for better reliability
            endpoints = [
                "https://httpbin.org/status/200",
                "https://www.google.com",
                "https://www.cloudflare.com"
            ]
            
            for endpoint in endpoints:
                try:
                    response = requests.get(endpoint, timeout=5)
                    if response.status_code in [200, 301, 302]:
                        logger.info("Network recovery successful")
                        return True
                except Exception:
                    continue
            
            logger.error("Network recovery failed - all endpoints unreachable")
            return False
        except Exception as e:
            logger.error(f"Network recovery failed: {e}")
            return False
    
    def _recover_scrapers(self, error: Exception) -> bool:
        """Recover from scraper errors."""
        try:
            logger.info("Attempting scraper recovery...")
            from scraper_thread import stop_all_scrapers, start_facebook, start_craigslist, start_ksl
            
            # Stop all scrapers
            stop_all_scrapers()
            time.sleep(2)
            
            # Restart scrapers
            start_facebook()
            start_craigslist()
            start_ksl()
            
            logger.info("Scraper recovery successful")
            return True
        except Exception as e:
            logger.error(f"Scraper recovery failed: {e}")
            return False

class GracefulDegradation:
    """Implement graceful degradation when errors occur."""
    
    def __init__(self):
        self.degradation_levels = {
            "full": 0,
            "limited": 1,
            "minimal": 2,
            "offline": 3
        }
        self.current_level = 0
    
    def adjust_degradation_level(self, error_count: int, component: str):
        """Adjust degradation level based on error frequency."""
        if error_count > 10:
            self.current_level = 3  # offline
        elif error_count > 5:
            self.current_level = 2  # minimal
        elif error_count > 2:
            self.current_level = 1  # limited
        else:
            self.current_level = 0  # full
        
        logger.info(f"Degradation level adjusted to {self.current_level} for {component}")
    
    def get_available_features(self) -> List[str]:
        """Get list of available features based on current degradation level."""
        if self.current_level == 0:  # full
            return ["scraping", "database", "network", "ui"]
        elif self.current_level == 1:  # limited
            return ["database", "ui"]
        elif self.current_level == 2:  # minimal
            return ["ui"]
        else:  # offline
            return []

class ErrorRecoverySystem:
    """Main error recovery system that coordinates all recovery mechanisms."""
    
    def __init__(self):
        self.health_monitor = HealthMonitor()
        self.recovery_manager = RecoveryManager()
        self.graceful_degradation = GracefulDegradation()
        self.error_counts = {"database": 0, "network": 0, "scrapers": 0}
        self.last_recovery_attempt = {}
    
    def start(self):
        """Start the error recovery system."""
        self.health_monitor.start_monitoring()
        logger.info("Error recovery system started")
    
    def stop(self):
        """Stop the error recovery system."""
        self.health_monitor.stop_monitoring()
        logger.info("Error recovery system stopped")
    
    def handle_error(self, error: Exception, component: str, context: str = ""):
        """Handle an error with automatic recovery."""
        self.error_counts[component] += 1
        
        # Use basic logging to avoid recursion in error handling
        try:
            logger.error(f"Error in {component}: {error} (Context: {context})")
        except (RecursionError, ImportError):
            # Fallback to print if logger causes recursion
            print(f"Error in {component}: {error} (Context: {context})")
        
        # Check if we should attempt recovery
        should_recover = self._should_attempt_recovery(component)
        
        if should_recover:
            success = self.recovery_manager.attempt_recovery(component, error)
            if success:
                self.error_counts[component] = 0  # Reset on successful recovery
                try:
                    logger.info(f"Recovery successful for {component}")
                except (RecursionError, ImportError):
                    print(f"Recovery successful for {component}")
            else:
                try:
                    logger.warning(f"Recovery failed for {component}")
                except (RecursionError, ImportError):
                    print(f"Recovery failed for {component}")
        
        # Adjust degradation level
        self.graceful_degradation.adjust_degradation_level(
            self.error_counts[component], component
        )
    
    def _should_attempt_recovery(self, component: str) -> bool:
        """Determine if recovery should be attempted."""
        # Don't attempt recovery too frequently
        now = datetime.now()
        last_attempt = self.last_recovery_attempt.get(component)
        
        if last_attempt and (now - last_attempt).seconds < 60:
            return False
        
        # Attempt recovery if error count is reasonable
        return self.error_counts[component] < 20
    
    def get_system_status(self) -> Dict:
        """Get comprehensive system status."""
        return {
            "health": self.health_monitor.get_health_status(),
            "error_counts": self.error_counts.copy(),
            "degradation_level": self.graceful_degradation.current_level,
            "available_features": self.graceful_degradation.get_available_features()
        }

# Global error recovery system instance
error_recovery_system = ErrorRecoverySystem()

def start_error_recovery():
    """Start the global error recovery system."""
    error_recovery_system.start()

def stop_error_recovery():
    """Stop the global error recovery system."""
    error_recovery_system.stop()

def handle_error(error: Exception, component: str, context: str = ""):
    """Handle an error using the global recovery system."""
    # Prevent recursion by checking if we're already handling an error
    if hasattr(handle_error, '_handling_error'):
        print(f"Recursion detected in error handling for {component}: {error}")
        return
    
    handle_error._handling_error = True
    try:
        error_recovery_system.handle_error(error, component, context)
    finally:
        handle_error._handling_error = False

def get_system_status() -> Dict:
    """Get current system status."""
    return error_recovery_system.get_system_status()
