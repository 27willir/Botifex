"""Advanced Proxy Manager with Residential Proxy Support.

This module provides intelligent proxy rotation with:
- Support for multiple proxy providers (BrightData, SmartProxy, free lists)
- Per-site proxy health tracking and automatic rotation
- Residential vs datacenter proxy classification
- Automatic proxy validation and blacklisting
- Geographic targeting support

Configuration:
    Set SCRAPER_PROXIES environment variable with comma-separated proxies:
    SCRAPER_PROXIES=http://user:pass@proxy1:8080,http://user:pass@proxy2:8080
    
    Or set provider-specific credentials:
    BRIGHTDATA_PROXY=http://user:pass@brd.superproxy.io:22225
    SMARTPROXY_PROXY=http://user:pass@gate.smartproxy.com:7000

Usage:
    from scrapers.proxy_manager import ProxyManager, get_proxy
    
    # Get a proxy for a site
    proxy = get_proxy("ebay")
    
    # Record success/failure for health tracking
    record_proxy_success("ebay", proxy, response_time=1.5)
    record_proxy_failure("ebay", proxy, is_block=True)
"""

from __future__ import annotations

import os
import random
import time
import threading
import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Set, Tuple
from collections import defaultdict, deque
from urllib.parse import urlparse, urlencode
from pathlib import Path

from utils import logger


class ProxyType(Enum):
    """Types of proxies."""
    DATACENTER = "datacenter"
    RESIDENTIAL = "residential"
    MOBILE = "mobile"
    ISP = "isp"
    ROTATING = "rotating"


class ProxyProvider(Enum):
    """Known proxy providers."""
    BRIGHTDATA = "brightdata"
    SMARTPROXY = "smartproxy"
    OXYLABS = "oxylabs"
    WEBSHARE = "webshare"
    FREE = "free"
    CUSTOM = "custom"


@dataclass
class ProxyConfig:
    """Configuration for a single proxy."""
    url: str
    provider: ProxyProvider = ProxyProvider.CUSTOM
    proxy_type: ProxyType = ProxyType.DATACENTER
    country: Optional[str] = None
    city: Optional[str] = None
    session_id: Optional[str] = None
    
    # For rotating proxies with session support
    session_duration: int = 600  # 10 minutes
    
    def __hash__(self):
        return hash(self.url)
    
    def __eq__(self, other):
        if isinstance(other, ProxyConfig):
            return self.url == other.url
        return False


@dataclass
class ProxyHealth:
    """Health tracking for a proxy."""
    proxy: ProxyConfig
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    blocked_requests: int = 0
    consecutive_failures: int = 0
    last_success_ts: float = 0.0
    last_failure_ts: float = 0.0
    blocked_until: float = 0.0
    response_times: deque = field(default_factory=lambda: deque(maxlen=20))
    
    # Per-site health (some proxies work better for certain sites)
    site_stats: Dict[str, Dict[str, int]] = field(default_factory=lambda: defaultdict(lambda: {"success": 0, "fail": 0}))
    
    @property
    def success_rate(self) -> float:
        if self.total_requests == 0:
            return 1.0  # Unknown, assume good
        return self.successful_requests / self.total_requests
    
    @property
    def avg_response_time(self) -> float:
        if not self.response_times:
            return 5.0  # Default
        return sum(self.response_times) / len(self.response_times)
    
    @property
    def is_healthy(self) -> bool:
        now = time.time()
        
        # Check if blocked
        if self.blocked_until > now:
            return False
        
        # Too many consecutive failures
        if self.consecutive_failures >= 5:
            return False
        
        # Very low success rate with enough data
        if self.total_requests > 20 and self.success_rate < 0.2:
            return False
        
        return True
    
    def site_success_rate(self, site_name: str) -> float:
        """Get success rate for a specific site."""
        stats = self.site_stats.get(site_name)
        if not stats:
            return self.success_rate  # Fall back to overall
        total = stats["success"] + stats["fail"]
        if total == 0:
            return self.success_rate
        return stats["success"] / total
    
    def record_success(self, response_time: float, site_name: Optional[str] = None) -> None:
        self.total_requests += 1
        self.successful_requests += 1
        self.consecutive_failures = 0
        self.last_success_ts = time.time()
        self.response_times.append(response_time)
        
        if site_name:
            self.site_stats[site_name]["success"] += 1
    
    def record_failure(self, is_block: bool = False, site_name: Optional[str] = None) -> None:
        now = time.time()
        self.total_requests += 1
        self.failed_requests += 1
        self.consecutive_failures += 1
        self.last_failure_ts = now
        
        if is_block:
            self.blocked_requests += 1
        
        if site_name:
            self.site_stats[site_name]["fail"] += 1
        
        # Block proxy after consecutive failures or blocks
        if is_block or self.consecutive_failures >= 3:
            # Exponential backoff
            block_duration = min(60 * (2 ** self.consecutive_failures), 3600)
            self.blocked_until = now + block_duration
            logger.debug(f"Proxy {self.proxy.url[:30]}... blocked for {block_duration}s")


# ======================
# PROXY PROVIDER CONFIGS
# ======================

def _build_brightdata_url(
    username: str,
    password: str,
    country: str = "us",
    session: str = None,
    residential: bool = True,
) -> str:
    """Build BrightData proxy URL with session support."""
    host = "brd.superproxy.io" if residential else "brd-customer-CUST-dc.zproxy.lum-superproxy.io"
    port = 22225
    
    # Add session for sticky IPs
    user_part = username
    if country:
        user_part += f"-country-{country}"
    if session:
        user_part += f"-session-{session}"
    
    return f"http://{user_part}:{password}@{host}:{port}"


def _build_smartproxy_url(
    username: str,
    password: str,
    country: str = "us",
    session: str = None,
    residential: bool = True,
) -> str:
    """Build SmartProxy URL with session support."""
    host = "gate.smartproxy.com" if residential else "us.smartproxy.com"
    port = 7000 if residential else 10000
    
    user_part = username
    if session:
        user_part += f"-session-{session}"
    
    return f"http://{user_part}:{password}@{host}:{port}"


def _build_oxylabs_url(
    username: str,
    password: str,
    country: str = "us",
    session: str = None,
) -> str:
    """Build Oxylabs proxy URL."""
    host = "pr.oxylabs.io"
    port = 7777
    
    user_part = f"customer-{username}"
    if country:
        user_part += f"-cc-{country}"
    if session:
        user_part += f"-sessid-{session}"
    
    return f"http://{user_part}:{password}@{host}:{port}"


# ======================
# PROXY MANAGER
# ======================

class ProxyManager:
    """Intelligent proxy manager with health tracking and rotation."""
    
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
        
        self._proxies: List[ProxyConfig] = []
        self._health: Dict[str, ProxyHealth] = {}
        self._lock = threading.Lock()
        
        # Per-site proxy preferences
        self._site_preferences: Dict[str, List[str]] = defaultdict(list)
        
        # Blacklisted proxies (permanent)
        self._blacklist: Set[str] = set()
        
        # Session tracking for rotating proxies
        self._sessions: Dict[str, Tuple[str, float]] = {}  # site -> (session_id, created_ts)
        
        self._initialized = True
        
        # Load proxies from environment
        self._load_from_env()
    
    def _load_from_env(self) -> None:
        """Load proxy configuration from environment variables."""
        loaded = 0
        
        # Load from SCRAPER_PROXIES (comma-separated list)
        proxy_list = os.environ.get("SCRAPER_PROXIES", "")
        if proxy_list:
            for proxy_url in proxy_list.split(","):
                proxy_url = proxy_url.strip()
                if proxy_url:
                    self.add_proxy(ProxyConfig(
                        url=proxy_url,
                        provider=ProxyProvider.CUSTOM,
                    ))
                    loaded += 1
        
        # Load from provider-specific variables
        brightdata_proxy = os.environ.get("BRIGHTDATA_PROXY", "")
        if brightdata_proxy:
            self.add_proxy(ProxyConfig(
                url=brightdata_proxy,
                provider=ProxyProvider.BRIGHTDATA,
                proxy_type=ProxyType.RESIDENTIAL,
            ))
            loaded += 1
        
        smartproxy_proxy = os.environ.get("SMARTPROXY_PROXY", "")
        if smartproxy_proxy:
            self.add_proxy(ProxyConfig(
                url=smartproxy_proxy,
                provider=ProxyProvider.SMARTPROXY,
                proxy_type=ProxyType.RESIDENTIAL,
            ))
            loaded += 1
        
        oxylabs_proxy = os.environ.get("OXYLABS_PROXY", "")
        if oxylabs_proxy:
            self.add_proxy(ProxyConfig(
                url=oxylabs_proxy,
                provider=ProxyProvider.OXYLABS,
                proxy_type=ProxyType.RESIDENTIAL,
            ))
            loaded += 1
        
        # Load from file if exists
        proxy_file = Path(".proxies.txt")
        if proxy_file.exists():
            try:
                for line in proxy_file.read_text().strip().split("\n"):
                    line = line.strip()
                    if line and not line.startswith("#"):
                        self.add_proxy(ProxyConfig(url=line))
                        loaded += 1
            except Exception as e:
                logger.debug(f"Error loading proxy file: {e}")
        
        if loaded > 0:
            logger.info(f"Loaded {loaded} proxies from environment/config")
    
    def add_proxy(self, proxy: ProxyConfig) -> bool:
        """Add a proxy to the pool."""
        with self._lock:
            if proxy.url in self._blacklist:
                return False
            
            # Check if already exists
            for existing in self._proxies:
                if existing.url == proxy.url:
                    return False
            
            self._proxies.append(proxy)
            self._health[proxy.url] = ProxyHealth(proxy=proxy)
            return True
    
    def remove_proxy(self, proxy_url: str) -> bool:
        """Remove a proxy from the pool."""
        with self._lock:
            for i, proxy in enumerate(self._proxies):
                if proxy.url == proxy_url:
                    del self._proxies[i]
                    self._health.pop(proxy_url, None)
                    return True
            return False
    
    def blacklist_proxy(self, proxy_url: str) -> None:
        """Permanently blacklist a proxy."""
        with self._lock:
            self._blacklist.add(proxy_url)
            self.remove_proxy(proxy_url)
            logger.info(f"Blacklisted proxy: {proxy_url[:30]}...")
    
    def _get_session_id(self, site_name: str) -> str:
        """Get or create a session ID for sticky sessions."""
        now = time.time()
        
        if site_name in self._sessions:
            session_id, created = self._sessions[site_name]
            # Session valid for 10 minutes
            if now - created < 600:
                return session_id
        
        # Create new session
        session_id = hashlib.md5(f"{site_name}:{now}:{random.random()}".encode()).hexdigest()[:16]
        self._sessions[site_name] = (session_id, now)
        return session_id
    
    def get_proxy(
        self,
        site_name: Optional[str] = None,
        prefer_residential: bool = True,
        country: Optional[str] = None,
    ) -> Optional[str]:
        """
        Get the best available proxy for a site.
        
        Args:
            site_name: Site to get proxy for (for health-based selection)
            prefer_residential: Prefer residential proxies
            country: Preferred country code
            
        Returns:
            Proxy URL or None if no proxies available
        """
        with self._lock:
            if not self._proxies:
                return None
            
            # Filter healthy proxies
            healthy = [
                p for p in self._proxies
                if p.url not in self._blacklist and self._health[p.url].is_healthy
            ]
            
            if not healthy:
                # All proxies unhealthy, return a random one anyway
                return random.choice(self._proxies).url
            
            # Sort by site-specific success rate if site provided
            if site_name:
                def score(proxy: ProxyConfig) -> float:
                    health = self._health[proxy.url]
                    site_rate = health.site_success_rate(site_name)
                    overall_rate = health.success_rate
                    response_time = health.avg_response_time
                    
                    # Prefer residential for difficult sites
                    type_bonus = 0.1 if proxy.proxy_type == ProxyType.RESIDENTIAL else 0
                    
                    # Score: higher is better
                    return (site_rate * 0.5 + overall_rate * 0.3 + type_bonus - (response_time / 30))
                
                healthy.sort(key=score, reverse=True)
                
                # Pick from top 3 with some randomness
                top_proxies = healthy[:min(3, len(healthy))]
                return random.choice(top_proxies).url
            
            # No site specified, use random healthy proxy
            if prefer_residential:
                residential = [p for p in healthy if p.proxy_type == ProxyType.RESIDENTIAL]
                if residential:
                    return random.choice(residential).url
            
            return random.choice(healthy).url
    
    def record_success(
        self,
        proxy_url: str,
        response_time: float,
        site_name: Optional[str] = None,
    ) -> None:
        """Record a successful request."""
        with self._lock:
            if proxy_url in self._health:
                self._health[proxy_url].record_success(response_time, site_name)
    
    def record_failure(
        self,
        proxy_url: str,
        is_block: bool = False,
        site_name: Optional[str] = None,
    ) -> None:
        """Record a failed request."""
        with self._lock:
            if proxy_url in self._health:
                self._health[proxy_url].record_failure(is_block, site_name)
    
    def rotate_proxy(self, site_name: str) -> Optional[str]:
        """Force rotation to a different proxy."""
        with self._lock:
            current = self._site_preferences.get(site_name, [None])[0] if site_name in self._site_preferences else None
            
            # Get a different healthy proxy
            healthy = [
                p for p in self._proxies
                if p.url != current and p.url not in self._blacklist and self._health[p.url].is_healthy
            ]
            
            if healthy:
                new_proxy = random.choice(healthy).url
                self._site_preferences[site_name] = [new_proxy]
                return new_proxy
            
            return None
    
    def get_stats(self) -> Dict[str, Any]:
        """Get proxy pool statistics."""
        with self._lock:
            total = len(self._proxies)
            healthy = sum(1 for p in self._proxies if self._health[p.url].is_healthy)
            
            return {
                "total_proxies": total,
                "healthy_proxies": healthy,
                "blacklisted": len(self._blacklist),
                "proxies": [
                    {
                        "url": p.url[:30] + "..." if len(p.url) > 30 else p.url,
                        "provider": p.provider.value,
                        "type": p.proxy_type.value,
                        "success_rate": round(self._health[p.url].success_rate * 100, 1),
                        "requests": self._health[p.url].total_requests,
                        "is_healthy": self._health[p.url].is_healthy,
                        "avg_response_time": round(self._health[p.url].avg_response_time, 2),
                    }
                    for p in self._proxies
                ]
            }
    
    def add_free_proxies(self, count: int = 10) -> int:
        """Fetch and add free proxies from public lists.
        
        Note: Free proxies are unreliable and should only be used as fallback.
        Returns number of proxies added.
        """
        added = 0
        
        # List of free proxy API endpoints
        free_proxy_apis = [
            "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=5000&country=all&ssl=all&anonymity=elite",
            "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
            "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
        ]
        
        try:
            import requests
            
            for api_url in free_proxy_apis:
                if added >= count:
                    break
                
                try:
                    response = requests.get(api_url, timeout=10)
                    if response.status_code == 200:
                        for line in response.text.strip().split("\n"):
                            if added >= count:
                                break
                            
                            line = line.strip()
                            if line and ":" in line:
                                proxy_url = f"http://{line}"
                                if self.add_proxy(ProxyConfig(
                                    url=proxy_url,
                                    provider=ProxyProvider.FREE,
                                    proxy_type=ProxyType.DATACENTER,
                                )):
                                    added += 1
                except Exception:
                    continue
        except ImportError:
            pass
        
        if added > 0:
            logger.info(f"Added {added} free proxies to pool")
        
        return added
    
    @property
    def has_proxies(self) -> bool:
        """Check if any proxies are available."""
        return len(self._proxies) > 0


# Global manager instance
_manager = ProxyManager()


# ======================
# PUBLIC API
# ======================

def get_proxy(
    site_name: Optional[str] = None,
    prefer_residential: bool = True,
) -> Optional[str]:
    """Get the best available proxy for a site."""
    return _manager.get_proxy(site_name, prefer_residential)


def record_proxy_success(
    site_name: str,
    proxy_url: str,
    response_time: float,
) -> None:
    """Record a successful proxy request."""
    _manager.record_success(proxy_url, response_time, site_name)


def record_proxy_failure(
    site_name: str,
    proxy_url: str,
    is_block: bool = False,
) -> None:
    """Record a failed proxy request."""
    _manager.record_failure(proxy_url, is_block, site_name)


def rotate_proxy(site_name: str) -> Optional[str]:
    """Force rotation to a different proxy."""
    return _manager.rotate_proxy(site_name)


def add_proxies(proxy_urls: List[str]) -> int:
    """Add multiple proxies to the pool."""
    added = 0
    for url in proxy_urls:
        if _manager.add_proxy(ProxyConfig(url=url)):
            added += 1
    return added


def add_free_proxies(count: int = 10) -> int:
    """Fetch and add free proxies."""
    return _manager.add_free_proxies(count)


def get_proxy_stats() -> Dict[str, Any]:
    """Get proxy pool statistics."""
    return _manager.get_stats()


def has_proxies() -> bool:
    """Check if any proxies are available."""
    return _manager.has_proxies


def blacklist_proxy(proxy_url: str) -> None:
    """Permanently blacklist a proxy."""
    _manager.blacklist_proxy(proxy_url)


def get_proxy_manager() -> ProxyManager:
    """Get the proxy manager instance."""
    return _manager


__all__ = [
    "get_proxy",
    "record_proxy_success",
    "record_proxy_failure",
    "rotate_proxy",
    "add_proxies",
    "add_free_proxies",
    "get_proxy_stats",
    "has_proxies",
    "blacklist_proxy",
    "get_proxy_manager",
    "ProxyManager",
    "ProxyConfig",
    "ProxyType",
    "ProxyProvider",
]

