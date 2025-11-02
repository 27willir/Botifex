"""
Scraper metrics tracking module.
Provides context manager for tracking scraper performance and results.
"""

from utils import logger
from datetime import datetime


class ScraperMetrics:
    """Context manager for tracking scraper metrics."""
    
    def __init__(self, scraper_name):
        """Initialize metrics tracker.
        
        Args:
            scraper_name: Name of the scraper being tracked
        """
        self.scraper_name = scraper_name
        self.success = False
        self.error = None
        self.listings_found = 0
        self.start_time = None
        self.end_time = None
    
    def __enter__(self):
        """Enter context manager."""
        self.start_time = datetime.now()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context manager and log metrics."""
        self.end_time = datetime.now()
        duration = (self.end_time - self.start_time).total_seconds()
        
        # Log metrics
        if self.error:
            logger.debug(f"[{self.scraper_name}] Scraper run failed after {duration:.2f}s: {self.error}")
        elif self.success:
            logger.debug(f"[{self.scraper_name}] Scraper run completed in {duration:.2f}s: {self.listings_found} listings found")
        else:
            logger.debug(f"[{self.scraper_name}] Scraper run completed in {duration:.2f}s (status unknown)")
        
        # Don't suppress exceptions
        return False

