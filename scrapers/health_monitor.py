"""Real-time health monitoring and alerting for scrapers.

This module provides comprehensive health tracking for all scrapers including:
- Success/failure rates over configurable time windows
- Response time tracking and anomaly detection
- Block frequency monitoring
- Automatic alerting when health degrades
- Health status aggregation for dashboard display
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Deque, Dict, List, Optional, Tuple

from utils import logger


# Health thresholds
HEALTH_THRESHOLDS = {
    "excellent": 95.0,  # >= 95% success rate
    "good": 80.0,       # >= 80% success rate
    "degraded": 50.0,   # >= 50% success rate
    "poor": 0.0,        # < 50% success rate
}

# Alert thresholds
ALERT_THRESHOLDS = {
    "success_rate_warning": 80.0,
    "success_rate_critical": 50.0,
    "consecutive_failures_warning": 3,
    "consecutive_failures_critical": 5,
    "response_time_warning": 10.0,  # seconds
    "response_time_critical": 30.0,
    "block_rate_warning": 0.1,  # 10% of requests blocked
    "block_rate_critical": 0.25,
}


@dataclass
class HealthEvent:
    """Represents a single health event."""
    
    timestamp: float
    event_type: str  # "success", "failure", "block", "timeout"
    response_time: Optional[float] = None
    error_message: Optional[str] = None
    strategy_used: Optional[str] = None


@dataclass
class ScraperHealth:
    """Health tracking for a single scraper."""
    
    site_name: str
    events: Deque[HealthEvent] = field(default_factory=lambda: deque(maxlen=1000))
    consecutive_failures: int = 0
    last_success_ts: float = 0.0
    last_failure_ts: float = 0.0
    last_block_ts: float = 0.0
    total_requests: int = 0
    total_successes: int = 0
    total_failures: int = 0
    total_blocks: int = 0
    alerts: Deque[Dict[str, Any]] = field(default_factory=lambda: deque(maxlen=100))
    
    def record_success(self, response_time: float, strategy: Optional[str] = None) -> None:
        """Record a successful request."""
        now = time.time()
        self.events.append(HealthEvent(
            timestamp=now,
            event_type="success",
            response_time=response_time,
            strategy_used=strategy,
        ))
        self.consecutive_failures = 0
        self.last_success_ts = now
        self.total_requests += 1
        self.total_successes += 1
    
    def record_failure(self, error_message: Optional[str] = None) -> None:
        """Record a failed request."""
        now = time.time()
        self.events.append(HealthEvent(
            timestamp=now,
            event_type="failure",
            error_message=error_message,
        ))
        self.consecutive_failures += 1
        self.last_failure_ts = now
        self.total_requests += 1
        self.total_failures += 1
        
        # Check for alerts
        self._check_failure_alerts()
    
    def record_block(self, block_type: str) -> None:
        """Record a block detection."""
        now = time.time()
        self.events.append(HealthEvent(
            timestamp=now,
            event_type="block",
            error_message=block_type,
        ))
        self.consecutive_failures += 1
        self.last_block_ts = now
        self.total_requests += 1
        self.total_blocks += 1
        
        # Check for alerts
        self._check_block_alerts()
    
    def _check_failure_alerts(self) -> None:
        """Check and generate failure-related alerts."""
        if self.consecutive_failures >= ALERT_THRESHOLDS["consecutive_failures_critical"]:
            self._add_alert("critical", f"Critical: {self.consecutive_failures} consecutive failures")
        elif self.consecutive_failures >= ALERT_THRESHOLDS["consecutive_failures_warning"]:
            self._add_alert("warning", f"Warning: {self.consecutive_failures} consecutive failures")
    
    def _check_block_alerts(self) -> None:
        """Check and generate block-related alerts."""
        block_rate = self.get_block_rate(hours=1)
        if block_rate >= ALERT_THRESHOLDS["block_rate_critical"]:
            self._add_alert("critical", f"Critical: {block_rate*100:.1f}% block rate")
        elif block_rate >= ALERT_THRESHOLDS["block_rate_warning"]:
            self._add_alert("warning", f"Warning: {block_rate*100:.1f}% block rate")
    
    def _add_alert(self, severity: str, message: str) -> None:
        """Add an alert to the queue."""
        # Avoid duplicate alerts within 5 minutes
        now = time.time()
        recent_alerts = [a for a in self.alerts if now - a["timestamp"] < 300]
        if any(a["message"] == message for a in recent_alerts):
            return
        
        alert = {
            "timestamp": now,
            "severity": severity,
            "site": self.site_name,
            "message": message,
        }
        self.alerts.append(alert)
        
        # Log the alert
        if severity == "critical":
            logger.critical(f"[{self.site_name}] {message}")
        else:
            logger.warning(f"[{self.site_name}] {message}")
    
    def get_success_rate(self, hours: Optional[int] = 1) -> float:
        """Get success rate over the specified time window."""
        if not self.events:
            return 100.0  # No data = assume healthy
        
        cutoff = time.time() - (hours * 3600) if hours else 0
        relevant_events = [e for e in self.events if e.timestamp >= cutoff]
        
        if not relevant_events:
            return 100.0
        
        successes = sum(1 for e in relevant_events if e.event_type == "success")
        return (successes / len(relevant_events)) * 100
    
    def get_block_rate(self, hours: Optional[int] = 1) -> float:
        """Get block rate over the specified time window."""
        if not self.events:
            return 0.0
        
        cutoff = time.time() - (hours * 3600) if hours else 0
        relevant_events = [e for e in self.events if e.timestamp >= cutoff]
        
        if not relevant_events:
            return 0.0
        
        blocks = sum(1 for e in relevant_events if e.event_type == "block")
        return blocks / len(relevant_events)
    
    def get_avg_response_time(self, hours: Optional[int] = 1) -> float:
        """Get average response time over the specified time window."""
        if not self.events:
            return 0.0
        
        cutoff = time.time() - (hours * 3600) if hours else 0
        response_times = [
            e.response_time for e in self.events
            if e.timestamp >= cutoff and e.response_time is not None
        ]
        
        if not response_times:
            return 0.0
        
        return sum(response_times) / len(response_times)
    
    def get_health_status(self) -> str:
        """Get overall health status as a string."""
        success_rate = self.get_success_rate(hours=1)
        
        if success_rate >= HEALTH_THRESHOLDS["excellent"]:
            return "excellent"
        elif success_rate >= HEALTH_THRESHOLDS["good"]:
            return "good"
        elif success_rate >= HEALTH_THRESHOLDS["degraded"]:
            return "degraded"
        else:
            return "poor"
    
    def get_summary(self) -> Dict[str, Any]:
        """Get a comprehensive health summary."""
        return {
            "site": self.site_name,
            "status": self.get_health_status(),
            "success_rate_1h": round(self.get_success_rate(hours=1), 1),
            "success_rate_24h": round(self.get_success_rate(hours=24), 1),
            "block_rate_1h": round(self.get_block_rate(hours=1) * 100, 1),
            "avg_response_time": round(self.get_avg_response_time(hours=1), 2),
            "consecutive_failures": self.consecutive_failures,
            "total_requests": self.total_requests,
            "total_successes": self.total_successes,
            "total_failures": self.total_failures,
            "total_blocks": self.total_blocks,
            "last_success": datetime.fromtimestamp(self.last_success_ts).isoformat() if self.last_success_ts else None,
            "last_failure": datetime.fromtimestamp(self.last_failure_ts).isoformat() if self.last_failure_ts else None,
            "recent_alerts": [
                {
                    "time": datetime.fromtimestamp(a["timestamp"]).isoformat(),
                    "severity": a["severity"],
                    "message": a["message"],
                }
                for a in list(self.alerts)[-10:]
            ],
        }


class ScraperHealthMonitor:
    """Centralized health monitoring for all scrapers."""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._scrapers: Dict[str, ScraperHealth] = {}
        self._scraper_lock = threading.Lock()
        self._alert_callbacks: List[callable] = []
        self._initialized = True
        
        # Initialize default scrapers
        for site in ["ebay", "craigslist", "mercari", "ksl", "poshmark", "facebook"]:
            self._scrapers[site] = ScraperHealth(site_name=site)
    
    def _get_scraper(self, site_name: str) -> ScraperHealth:
        """Get or create scraper health tracker."""
        with self._scraper_lock:
            if site_name not in self._scrapers:
                self._scrapers[site_name] = ScraperHealth(site_name=site_name)
            return self._scrapers[site_name]
    
    def record_success(
        self,
        site_name: str,
        response_time: float,
        strategy: Optional[str] = None,
    ) -> None:
        """Record a successful scraper request."""
        scraper = self._get_scraper(site_name)
        scraper.record_success(response_time, strategy)
    
    def record_failure(
        self,
        site_name: str,
        error_message: Optional[str] = None,
    ) -> None:
        """Record a failed scraper request."""
        scraper = self._get_scraper(site_name)
        scraper.record_failure(error_message)
    
    def record_block(self, site_name: str, block_type: str) -> None:
        """Record a block detection."""
        scraper = self._get_scraper(site_name)
        scraper.record_block(block_type)
    
    def is_healthy(self, site_name: str) -> bool:
        """Check if a scraper is operating normally."""
        scraper = self._get_scraper(site_name)
        status = scraper.get_health_status()
        return status in ("excellent", "good")
    
    def get_health_summary(self, site_name: Optional[str] = None) -> Dict[str, Any]:
        """Get health summary for one or all scrapers."""
        if site_name:
            scraper = self._get_scraper(site_name)
            return scraper.get_summary()
        
        with self._scraper_lock:
            return {
                name: scraper.get_summary()
                for name, scraper in self._scrapers.items()
            }
    
    def get_overall_health(self) -> Dict[str, Any]:
        """Get overall system health across all scrapers."""
        with self._scraper_lock:
            if not self._scrapers:
                return {
                    "status": "unknown",
                    "healthy_scrapers": 0,
                    "total_scrapers": 0,
                    "overall_success_rate": 0.0,
                }
            
            statuses = [s.get_health_status() for s in self._scrapers.values()]
            success_rates = [s.get_success_rate(hours=1) for s in self._scrapers.values()]
            
            healthy_count = sum(1 for s in statuses if s in ("excellent", "good"))
            
            # Determine overall status
            if all(s == "excellent" for s in statuses):
                overall_status = "excellent"
            elif all(s in ("excellent", "good") for s in statuses):
                overall_status = "good"
            elif any(s == "poor" for s in statuses):
                overall_status = "poor"
            else:
                overall_status = "degraded"
            
            return {
                "status": overall_status,
                "healthy_scrapers": healthy_count,
                "total_scrapers": len(self._scrapers),
                "overall_success_rate": round(sum(success_rates) / len(success_rates), 1) if success_rates else 0.0,
                "per_scraper": {
                    name: {
                        "status": s.get_health_status(),
                        "success_rate": round(s.get_success_rate(hours=1), 1),
                    }
                    for name, s in self._scrapers.items()
                },
            }
    
    def get_recent_alerts(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent alerts across all scrapers."""
        all_alerts = []
        with self._scraper_lock:
            for scraper in self._scrapers.values():
                all_alerts.extend([
                    {
                        "time": datetime.fromtimestamp(a["timestamp"]).isoformat(),
                        "severity": a["severity"],
                        "site": a["site"],
                        "message": a["message"],
                    }
                    for a in scraper.alerts
                ])
        
        # Sort by timestamp descending
        all_alerts.sort(key=lambda x: x["time"], reverse=True)
        return all_alerts[:limit]
    
    def register_alert_callback(self, callback: callable) -> None:
        """Register a callback to be called when alerts are generated."""
        self._alert_callbacks.append(callback)
    
    def reset_scraper(self, site_name: str) -> None:
        """Reset health data for a specific scraper."""
        with self._scraper_lock:
            self._scrapers[site_name] = ScraperHealth(site_name=site_name)


# Global singleton instance
_monitor = ScraperHealthMonitor()


# Public convenience functions
def record_success(site_name: str, response_time: float, strategy: Optional[str] = None) -> None:
    _monitor.record_success(site_name, response_time, strategy)


def record_failure(site_name: str, error_message: Optional[str] = None) -> None:
    _monitor.record_failure(site_name, error_message)


def record_block(site_name: str, block_type: str) -> None:
    _monitor.record_block(site_name, block_type)


def is_healthy(site_name: str) -> bool:
    return _monitor.is_healthy(site_name)


def get_health_summary(site_name: Optional[str] = None) -> Dict[str, Any]:
    return _monitor.get_health_summary(site_name)


def get_overall_health() -> Dict[str, Any]:
    return _monitor.get_overall_health()


def get_recent_alerts(limit: int = 50) -> List[Dict[str, Any]]:
    return _monitor.get_recent_alerts(limit)


def get_monitor() -> ScraperHealthMonitor:
    """Get the global health monitor instance."""
    return _monitor


__all__ = [
    "ScraperHealthMonitor",
    "record_success",
    "record_failure",
    "record_block",
    "is_healthy",
    "get_health_summary",
    "get_overall_health",
    "get_recent_alerts",
    "get_monitor",
]

