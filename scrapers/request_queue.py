"""Coordinated request scheduling for scrapers.

This module provides centralized request coordination to:
- Prevent simultaneous requests to the same domain
- Implement priority-based request ordering
- Apply global rate limiting across all scrapers
- Track request timing for optimal spacing

Usage:
    from scrapers.request_queue import request_queue
    
    # Queue a request
    response = await request_queue.enqueue(
        url="https://example.com/search",
        site_name="example",
        priority=Priority.NORMAL,
    )
"""

from __future__ import annotations

import asyncio
import heapq
import threading
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable, Dict, List, Optional, Tuple
from collections import defaultdict

from utils import logger


class Priority(IntEnum):
    """Request priority levels."""
    
    CRITICAL = 0    # System-critical requests (health checks)
    HIGH = 1        # User-initiated searches
    NORMAL = 2      # Scheduled scraper checks
    LOW = 3         # Background prefetch
    IDLE = 4        # Lowest priority


@dataclass(order=True)
class QueuedRequest:
    """A request waiting in the queue."""
    
    priority: int
    timestamp: float = field(compare=False)
    request_id: str = field(compare=False)
    site_name: str = field(compare=False)
    url: str = field(compare=False)
    callback: Optional[Callable] = field(compare=False, default=None)
    kwargs: Dict[str, Any] = field(compare=False, default_factory=dict)
    result: Any = field(compare=False, default=None)
    error: Optional[Exception] = field(compare=False, default=None)
    completed: bool = field(compare=False, default=False)
    event: Optional[threading.Event] = field(compare=False, default=None)


class RequestQueue:
    """Centralized request queue with rate limiting and prioritization."""
    
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
        
        self._queue: List[QueuedRequest] = []
        self._queue_lock = threading.Lock()
        
        # Per-site rate limiting
        self._last_request_time: Dict[str, float] = defaultdict(float)
        self._site_locks: Dict[str, threading.Lock] = defaultdict(threading.Lock)
        
        # Rate limiting configuration (seconds between requests per site)
        self._min_intervals: Dict[str, float] = {
            "ebay": 4.0,
            "mercari": 5.0,
            "craigslist": 3.0,
            "ksl": 3.5,
            "poshmark": 4.0,
            "facebook": 5.0,
            "default": 3.0,
        }
        
        # Global rate limiting
        self._global_min_interval = 0.5  # Minimum time between any requests
        self._last_global_request = 0.0
        self._global_lock = threading.Lock()
        
        # Request counter for unique IDs
        self._request_counter = 0
        self._counter_lock = threading.Lock()
        
        # Pending requests by site
        self._pending_by_site: Dict[str, int] = defaultdict(int)
        
        # Worker thread
        self._worker_thread: Optional[threading.Thread] = None
        self._running = False
        
        self._initialized = True
    
    def _generate_request_id(self) -> str:
        """Generate a unique request ID."""
        with self._counter_lock:
            self._request_counter += 1
            return f"req_{self._request_counter}_{int(time.time() * 1000)}"
    
    def _get_min_interval(self, site_name: str) -> float:
        """Get minimum interval between requests for a site."""
        return self._min_intervals.get(site_name, self._min_intervals["default"])
    
    def _can_request_now(self, site_name: str) -> Tuple[bool, float]:
        """
        Check if we can make a request to the site now.
        
        Returns:
            tuple: (can_request, wait_time)
        """
        now = time.time()
        
        # Check global rate limit
        with self._global_lock:
            global_elapsed = now - self._last_global_request
            if global_elapsed < self._global_min_interval:
                return False, self._global_min_interval - global_elapsed
        
        # Check site-specific rate limit
        with self._site_locks[site_name]:
            min_interval = self._get_min_interval(site_name)
            site_elapsed = now - self._last_request_time[site_name]
            if site_elapsed < min_interval:
                return False, min_interval - site_elapsed
        
        return True, 0.0
    
    def _record_request_start(self, site_name: str) -> None:
        """Record that a request is starting."""
        now = time.time()
        
        with self._global_lock:
            self._last_global_request = now
        
        with self._site_locks[site_name]:
            self._last_request_time[site_name] = now
    
    def enqueue_sync(
        self,
        url: str,
        site_name: str,
        priority: Priority = Priority.NORMAL,
        callback: Optional[Callable] = None,
        timeout: float = 60.0,
        **kwargs,
    ) -> Optional[Any]:
        """
        Synchronously queue a request and wait for result.
        
        Args:
            url: URL to request
            site_name: Name of the site
            priority: Request priority
            callback: Function to call with (url, **kwargs) to make the request
            timeout: Maximum time to wait for result
            **kwargs: Additional arguments for the callback
            
        Returns:
            Result from the callback, or None on timeout/error
        """
        request_id = self._generate_request_id()
        event = threading.Event()
        
        request = QueuedRequest(
            priority=int(priority),
            timestamp=time.time(),
            request_id=request_id,
            site_name=site_name,
            url=url,
            callback=callback,
            kwargs=kwargs,
            event=event,
        )
        
        # Add to queue
        with self._queue_lock:
            heapq.heappush(self._queue, request)
            self._pending_by_site[site_name] += 1
        
        # Process immediately if we can
        self._process_one()
        
        # Wait for completion
        if event.wait(timeout=timeout):
            if request.error:
                logger.debug(f"Request {request_id} failed: {request.error}")
                return None
            return request.result
        else:
            logger.warning(f"Request {request_id} timed out after {timeout}s")
            return None
    
    def _process_one(self) -> bool:
        """
        Process one request from the queue if possible.
        
        Returns:
            True if a request was processed, False otherwise
        """
        with self._queue_lock:
            if not self._queue:
                return False
            
            # Find the highest priority request we can execute now
            processable_idx = None
            for idx, request in enumerate(self._queue):
                can_request, wait_time = self._can_request_now(request.site_name)
                if can_request:
                    processable_idx = idx
                    break
            
            if processable_idx is None:
                return False
            
            # Pop the request (need to rebuild heap)
            request = self._queue.pop(processable_idx)
            heapq.heapify(self._queue)
            self._pending_by_site[request.site_name] -= 1
        
        # Execute the request
        self._record_request_start(request.site_name)
        
        try:
            if request.callback:
                result = request.callback(request.url, **request.kwargs)
                request.result = result
            else:
                # Default to using make_request_with_retry
                from scrapers.common import make_request_with_retry
                result = make_request_with_retry(
                    request.url,
                    request.site_name,
                    **request.kwargs,
                )
                request.result = result
        except Exception as e:
            request.error = e
            logger.error(f"Request {request.request_id} failed: {e}")
        finally:
            request.completed = True
            if request.event:
                request.event.set()
        
        return True
    
    def get_queue_stats(self) -> Dict[str, Any]:
        """Get current queue statistics."""
        with self._queue_lock:
            return {
                "total_pending": len(self._queue),
                "pending_by_site": dict(self._pending_by_site),
                "pending_by_priority": {
                    Priority(p).name: sum(1 for r in self._queue if r.priority == p)
                    for p in Priority
                },
            }
    
    def get_rate_limit_status(self) -> Dict[str, Any]:
        """Get current rate limiting status."""
        now = time.time()
        status = {}
        
        for site_name, last_time in self._last_request_time.items():
            min_interval = self._get_min_interval(site_name)
            elapsed = now - last_time
            status[site_name] = {
                "last_request_ago": round(elapsed, 1),
                "min_interval": min_interval,
                "can_request": elapsed >= min_interval,
            }
        
        return status
    
    def set_rate_limit(self, site_name: str, min_interval: float) -> None:
        """Set custom rate limit for a site."""
        self._min_intervals[site_name] = min_interval
    
    def clear_queue(self, site_name: Optional[str] = None) -> int:
        """
        Clear pending requests from the queue.
        
        Args:
            site_name: If provided, only clear requests for this site
            
        Returns:
            Number of requests cleared
        """
        with self._queue_lock:
            if site_name:
                original_len = len(self._queue)
                self._queue = [r for r in self._queue if r.site_name != site_name]
                heapq.heapify(self._queue)
                cleared = original_len - len(self._queue)
                self._pending_by_site[site_name] = 0
            else:
                cleared = len(self._queue)
                self._queue.clear()
                self._pending_by_site.clear()
            
            return cleared


# Global singleton instance
_request_queue = RequestQueue()


# Public convenience functions
def enqueue_request(
    url: str,
    site_name: str,
    priority: Priority = Priority.NORMAL,
    callback: Optional[Callable] = None,
    timeout: float = 60.0,
    **kwargs,
) -> Optional[Any]:
    """Queue a request and wait for result."""
    return _request_queue.enqueue_sync(
        url, site_name, priority, callback, timeout, **kwargs
    )


def get_queue_stats() -> Dict[str, Any]:
    """Get current queue statistics."""
    return _request_queue.get_queue_stats()


def get_rate_limit_status() -> Dict[str, Any]:
    """Get current rate limiting status."""
    return _request_queue.get_rate_limit_status()


def set_rate_limit(site_name: str, min_interval: float) -> None:
    """Set custom rate limit for a site."""
    _request_queue.set_rate_limit(site_name, min_interval)


def clear_queue(site_name: Optional[str] = None) -> int:
    """Clear pending requests from the queue."""
    return _request_queue.clear_queue(site_name)


def get_request_queue() -> RequestQueue:
    """Get the global request queue instance."""
    return _request_queue


__all__ = [
    "Priority",
    "RequestQueue",
    "enqueue_request",
    "get_queue_stats",
    "get_rate_limit_status",
    "set_rate_limit",
    "clear_queue",
    "get_request_queue",
]

