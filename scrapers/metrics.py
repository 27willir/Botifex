"""
Performance metrics tracking for scrapers.
Tracks success rates, response times, and listings found.
"""
import time
import threading
from collections import deque
from datetime import datetime, timedelta
from utils import logger


# Metrics storage (in-memory)
_metrics = {
    'craigslist': {'runs': deque(maxlen=100), 'total_listings': 0, 'total_errors': 0},
    'ebay': {'runs': deque(maxlen=100), 'total_listings': 0, 'total_errors': 0},
    'facebook': {'runs': deque(maxlen=100), 'total_listings': 0, 'total_errors': 0},
    'ksl': {'runs': deque(maxlen=100), 'total_listings': 0, 'total_errors': 0},
    'mercari': {'runs': deque(maxlen=100), 'total_listings': 0, 'total_errors': 0},
    'poshmark': {'runs': deque(maxlen=100), 'total_listings': 0, 'total_errors': 0}
}

_metrics_lock = threading.Lock()


class ScraperMetrics:
    """Context manager for tracking scraper run metrics."""
    
    def __init__(self, site_name):
        self.site_name = site_name
        self.start_time = None
        self.listings_found = 0
        self.success = False
        self.error = None
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = time.time() - self.start_time
        
        # Record the run
        with _metrics_lock:
            if self.site_name in _metrics:
                run_data = {
                    'timestamp': datetime.now().isoformat(),
                    'duration': duration,
                    'listings_found': self.listings_found,
                    'success': self.success,
                    'error': str(self.error) if self.error else None
                }
                
                _metrics[self.site_name]['runs'].append(run_data)
                _metrics[self.site_name]['total_listings'] += self.listings_found
                
                if not self.success:
                    _metrics[self.site_name]['total_errors'] += 1
        
        # Log the metrics
        if self.success:
            logger.info(f"{self.site_name} scrape completed in {duration:.2f}s, found {self.listings_found} listings")
        else:
            logger.warning(f"{self.site_name} scrape failed after {duration:.2f}s: {self.error}")
        
        # Don't suppress exceptions
        return False


def record_scraper_run(site_name, duration, listings_found, success=True, error=None):
    """
    Manually record a scraper run (alternative to using context manager).
    
    Args:
        site_name: Name of the scraper site
        duration: Duration in seconds
        listings_found: Number of listings found
        success: Whether the run was successful
        error: Error message if failed
    """
    with _metrics_lock:
        if site_name in _metrics:
            run_data = {
                'timestamp': datetime.now().isoformat(),
                'duration': duration,
                'listings_found': listings_found,
                'success': success,
                'error': str(error) if error else None
            }
            
            _metrics[site_name]['runs'].append(run_data)
            _metrics[site_name]['total_listings'] += listings_found
            
            if not success:
                _metrics[site_name]['total_errors'] += 1


def get_metrics_summary(site_name=None, hours=24):
    """
    Get summary metrics for scraper(s).
    
    Args:
        site_name: Optional specific site name, or None for all sites
        hours: Number of hours to look back (default 24)
        
    Returns:
        Dictionary of metrics
    """
    cutoff_time = datetime.now() - timedelta(hours=hours)
    
    def calculate_site_metrics(site):
        with _metrics_lock:
            if site not in _metrics:
                return None
            
            site_data = _metrics[site]
            runs = list(site_data['runs'])
            
            # Filter runs within time window
            recent_runs = [
                r for r in runs 
                if datetime.fromisoformat(r['timestamp']) > cutoff_time
            ]
            
            if not recent_runs:
                return {
                    'site': site,
                    'total_runs': 0,
                    'successful_runs': 0,
                    'failed_runs': 0,
                    'success_rate': 0.0,
                    'total_listings': 0,
                    'avg_listings_per_run': 0.0,
                    'avg_duration': 0.0,
                    'total_listings_all_time': site_data['total_listings'],
                    'total_errors_all_time': site_data['total_errors']
                }
            
            total_runs = len(recent_runs)
            successful_runs = sum(1 for r in recent_runs if r['success'])
            failed_runs = total_runs - successful_runs
            success_rate = (successful_runs / total_runs * 100) if total_runs > 0 else 0.0
            
            total_listings = sum(r['listings_found'] for r in recent_runs)
            avg_listings = total_listings / total_runs if total_runs > 0 else 0.0
            
            total_duration = sum(r['duration'] for r in recent_runs)
            avg_duration = total_duration / total_runs if total_runs > 0 else 0.0
            
            # Get last run info
            last_run = recent_runs[-1] if recent_runs else None
            
            return {
                'site': site,
                'total_runs': total_runs,
                'successful_runs': successful_runs,
                'failed_runs': failed_runs,
                'success_rate': round(success_rate, 2),
                'total_listings': total_listings,
                'avg_listings_per_run': round(avg_listings, 2),
                'avg_duration': round(avg_duration, 2),
                'last_run': last_run,
                'total_listings_all_time': site_data['total_listings'],
                'total_errors_all_time': site_data['total_errors']
            }
    
    if site_name:
        return calculate_site_metrics(site_name)
    else:
        # Return metrics for all sites
        return {
            site: calculate_site_metrics(site)
            for site in _metrics.keys()
        }


def get_recent_runs(site_name, limit=10):
    """
    Get recent run history for a scraper.
    
    Args:
        site_name: Name of the scraper site
        limit: Maximum number of runs to return
        
    Returns:
        List of recent run data
    """
    with _metrics_lock:
        if site_name not in _metrics:
            return []
        
        runs = list(_metrics[site_name]['runs'])
        return runs[-limit:] if len(runs) > limit else runs


def reset_metrics(site_name=None):
    """
    Reset metrics for a site or all sites.
    
    Args:
        site_name: Optional specific site name, or None for all sites
    """
    with _metrics_lock:
        if site_name:
            if site_name in _metrics:
                _metrics[site_name]['runs'].clear()
                _metrics[site_name]['total_listings'] = 0
                _metrics[site_name]['total_errors'] = 0
                logger.info(f"Reset metrics for {site_name}")
        else:
            for site in _metrics.keys():
                _metrics[site]['runs'].clear()
                _metrics[site]['total_listings'] = 0
                _metrics[site]['total_errors'] = 0
            logger.info("Reset metrics for all scrapers")


def get_performance_status(site_name):
    """
    Get simple performance status indicator.
    
    Args:
        site_name: Name of the scraper site
        
    Returns:
        String: 'excellent', 'good', 'degraded', 'poor', or 'unknown'
    """
    metrics = get_metrics_summary(site_name, hours=1)
    
    if not metrics or metrics['total_runs'] == 0:
        return 'unknown'
    
    success_rate = metrics['success_rate']
    
    if success_rate >= 95:
        return 'excellent'
    elif success_rate >= 80:
        return 'good'
    elif success_rate >= 50:
        return 'degraded'
    else:
        return 'poor'

