"""Advanced anti-blocking utilities for resilient web scraping.

This module implements sophisticated bypass techniques including:

- Realistic, session-consistent browser fingerprints with extensive user agent rotation
- Advanced block detection via content analysis, response size validation, and keyword matching
- Adaptive cooldown tracking with intelligent backoff strategies
- Proxy support infrastructure for IP rotation with health tracking
- Human-like timing patterns with variable jitter and dormant periods
- Session-based fingerprint consistency (same browser identity per session)
- TLS fingerprint randomization for enhanced stealth
- Burst detection to prevent rapid-fire requests
- Smart proxy pool management with per-site health metrics

These helpers operate entirely locally—no external proxy providers or SaaS dependencies
are required. Individual scrapers can opt-in by using the public functions exported
here. The module keeps a lightweight in-memory state so that behavior adapts over
time within the current process.
"""

from __future__ import annotations

import hashlib
import math
import random
import threading
import time
import ssl
import socket
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Iterable, List, Mapping, MutableMapping, Optional, Tuple, Any
from urllib.parse import urlparse, urlencode, parse_qs
import os
import re

# =====================
# HEADER/FINGERPRINT POOLS (EXTENSIVELY EXPANDED)
# =====================

# Complete browser fingerprint profiles (not just UA strings)
# Each profile contains consistent headers that match real browsers
@dataclass
class BrowserProfile:
    """Complete browser fingerprint for consistent identity."""
    user_agent: str
    sec_ch_ua: str
    sec_ch_ua_platform: str
    sec_ch_ua_mobile: str = "?0"
    sec_ch_ua_full_version_list: str = ""
    sec_ch_ua_arch: str = '"x86"'
    sec_ch_ua_bitness: str = '"64"'
    sec_ch_ua_model: str = '""'
    accept_language: str = "en-US,en;q=0.9"
    platform: str = "Windows"
    viewport_width: int = 1920

# Real browser profiles with matching headers (December 2024)
_BROWSER_PROFILES: Tuple[BrowserProfile, ...] = (
    # Chrome 131 Windows
    BrowserProfile(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        sec_ch_ua='"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        sec_ch_ua_platform='"Windows"',
        sec_ch_ua_full_version_list='"Google Chrome";v="131.0.6778.85", "Chromium";v="131.0.6778.85", "Not_A Brand";v="24.0.0.0"',
        sec_ch_ua_arch='"x86"',
        sec_ch_ua_bitness='"64"',
        accept_language="en-US,en;q=0.9",
        platform="Windows",
        viewport_width=1920,
    ),
    # Chrome 130 Windows  
    BrowserProfile(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        sec_ch_ua='"Google Chrome";v="130", "Chromium";v="130", "Not_A Brand";v="24"',
        sec_ch_ua_platform='"Windows"',
        sec_ch_ua_full_version_list='"Google Chrome";v="130.0.6723.91", "Chromium";v="130.0.6723.91", "Not_A Brand";v="24.0.0.0"',
        sec_ch_ua_arch='"x86"',
        sec_ch_ua_bitness='"64"',
        accept_language="en-US,en;q=0.9",
        platform="Windows",
        viewport_width=1920,
    ),
    # Chrome 131 Mac
    BrowserProfile(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        sec_ch_ua='"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        sec_ch_ua_platform='"macOS"',
        sec_ch_ua_full_version_list='"Google Chrome";v="131.0.6778.85", "Chromium";v="131.0.6778.85", "Not_A Brand";v="24.0.0.0"',
        sec_ch_ua_arch='"arm"',
        sec_ch_ua_bitness='"64"',
        accept_language="en-US,en;q=0.9",
        platform="macOS",
        viewport_width=1440,
    ),
    # Chrome 129 Windows (older but common)
    BrowserProfile(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        sec_ch_ua='"Google Chrome";v="129", "Chromium";v="129", "Not_A Brand";v="24"',
        sec_ch_ua_platform='"Windows"',
        sec_ch_ua_full_version_list='"Google Chrome";v="129.0.6668.89", "Chromium";v="129.0.6668.89", "Not_A Brand";v="24.0.0.0"',
        sec_ch_ua_arch='"x86"',
        sec_ch_ua_bitness='"64"',
        accept_language="en-US,en;q=0.9",
        platform="Windows",
        viewport_width=1920,
    ),
    # Edge 131 Windows
    BrowserProfile(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
        sec_ch_ua='"Microsoft Edge";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        sec_ch_ua_platform='"Windows"',
        sec_ch_ua_full_version_list='"Microsoft Edge";v="131.0.2903.51", "Chromium";v="131.0.6778.85", "Not_A Brand";v="24.0.0.0"',
        sec_ch_ua_arch='"x86"',
        sec_ch_ua_bitness='"64"',
        accept_language="en-US,en;q=0.9",
        platform="Windows",
        viewport_width=1920,
    ),
    # Firefox 133 Windows (Firefox has different headers)
    BrowserProfile(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
        sec_ch_ua="",  # Firefox doesn't send sec-ch-ua
        sec_ch_ua_platform="",
        sec_ch_ua_full_version_list="",
        accept_language="en-US,en;q=0.5",
        platform="Windows",
        viewport_width=1920,
    ),
    # Safari 18 Mac
    BrowserProfile(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
        sec_ch_ua="",  # Safari doesn't send sec-ch-ua
        sec_ch_ua_platform="",
        sec_ch_ua_full_version_list="",
        accept_language="en-US,en;q=0.9",
        platform="macOS",
        viewport_width=1440,
    ),
)

# Legacy UA list for backward compatibility
_USER_AGENTS: Tuple[str, ...] = tuple(p.user_agent for p in _BROWSER_PROFILES)

_ACCEPT_LANGUAGES: Tuple[str, ...] = (
    "en-US,en;q=0.9",
    "en-US,en;q=0.9,es;q=0.8",
    "en-US,en;q=0.8,en-GB;q=0.7",
    "en-US,en;q=0.5",  # Firefox style
)

_ACCEPT_HEADERS: Tuple[str, ...] = (
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",  # Firefox style
)

_SEC_CH_UA_PLATFORMS: Tuple[str, ...] = (
    '"Windows"',
    '"macOS"',
    '"Linux"',
)

_CACHE_CONTROL_VALUES: Tuple[str, ...] = (
    "max-age=0",  # Most common for real browsers
    "no-cache",
)

# Priority header values for HTTP/2 (helps with fingerprinting)
_PRIORITY_VALUES: Tuple[str, ...] = (
    "u=0, i",  # Highest priority, incremental
    "u=1, i",  # High priority, incremental
)

# Mobile user agents for fallback
_MOBILE_USER_AGENTS: Tuple[str, ...] = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/135.0.6998.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPad; CPU OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
)

# TLS cipher suites for fingerprint randomization (Chrome-like)
_TLS_CIPHER_SUITES_CHROME: Tuple[str, ...] = (
    "TLS_AES_128_GCM_SHA256",
    "TLS_AES_256_GCM_SHA384",
    "TLS_CHACHA20_POLY1305_SHA256",
    "ECDHE-ECDSA-AES128-GCM-SHA256",
    "ECDHE-RSA-AES128-GCM-SHA256",
    "ECDHE-ECDSA-AES256-GCM-SHA384",
    "ECDHE-RSA-AES256-GCM-SHA384",
)

# TLS cipher suites for Firefox-like fingerprint
_TLS_CIPHER_SUITES_FIREFOX: Tuple[str, ...] = (
    "TLS_AES_128_GCM_SHA256",
    "TLS_CHACHA20_POLY1305_SHA256",
    "TLS_AES_256_GCM_SHA384",
    "ECDHE-ECDSA-AES128-GCM-SHA256",
    "ECDHE-RSA-AES128-GCM-SHA256",
    "DHE-RSA-AES128-GCM-SHA256",
)


# =====================
# BLOCK/COOLDOWN PROFILES
# =====================

@dataclass
class SiteProfile:
    """Configuration for a site's anti-blocking behavior."""

    # INCREASED delays - previous values were too aggressive
    min_delay: float = 3.0  # Was 1.5 - too fast
    max_delay: float = 8.0  # Was 4.5 - too fast
    post_success_jitter: Tuple[float, float] = (0.5, 2.0)
    block_status_codes: Tuple[int, ...] = (403, 429, 503)  # Added 503
    block_keywords: Tuple[str, ...] = (
        "captcha",
        "access denied",
        "unusual traffic",
        "verify you are a human",
        "blocked",
        "temporarily unavailable",
        "service unavailable",
        "zero size object",
        "robot check",
        "forbidden",
        "cloudflare",
        "ray id",
        "checking your browser",
        "please wait",
        "ddos protection",
        "security check",
        "challenge page",
        "cf-browser-verification",
        "just a moment",
        "enable javascript",
        "browser verification",
        "anti-bot",
        "rate limit",
        "too many requests",
        "automated access",
        "distil networks",
        "incapsula",
        "shape security",
        "imperva",
        "datadome",
        "are you a bot",
        "prove you're human",
        "human verification",
        "not a robot",
        "security challenge",
        "access to this page has been denied",
    )
    soft_block_css_selectors: Tuple[str, ...] = ()
    cooldown_seconds: Tuple[float, float] = (60.0, 180.0)  # Increased from (45, 120)
    adaptive_multiplier: float = 2.0  # Increased from 1.8
    sample_html_bytes: int = 8192  # Increased from 4096
    default_referers: Tuple[str, ...] = ()
    # New: simulate reading time after loading a page
    reading_time: Tuple[float, float] = (1.0, 3.0)


_DEFAULT_PROFILE = SiteProfile()

_SITE_SPECIFIC_PROFILES: Dict[str, SiteProfile] = {
    "default": _DEFAULT_PROFILE,
    "ksl": SiteProfile(
        min_delay=4.0,  # Increased
        max_delay=10.0,  # Increased
        cooldown_seconds=(120.0, 300.0),  # Increased
        block_keywords=(
            "ksl classified",
            "unusual activity",
            "slow down",
            "verify",
            "blocked",
            "access denied",
            "are you a robot",
            "403",
            "security check",
        ),
        default_referers=("https://classifieds.ksl.com/", "https://www.ksl.com/"),
        reading_time=(2.0, 5.0),
    ),
    "mercari": SiteProfile(
        min_delay=5.0,  # Increased - Mercari is aggressive
        max_delay=12.0,  # Increased
        cooldown_seconds=(180.0, 420.0),  # Increased
        adaptive_multiplier=2.5,  # More aggressive backoff
        block_keywords=(
            "mercari",
            "unusual traffic",
            "access denied",
            "please verify",
            "for security reasons",
            "are you a robot",
            "403",
            "bot detection",
            "security check",
            "too many requests",
        ),
        default_referers=("https://www.mercari.com/", "https://www.mercari.com/search/"),
        reading_time=(2.0, 6.0),
    ),
    "ebay": SiteProfile(
        min_delay=5.0,  # Increased
        max_delay=12.0,  # Increased
        cooldown_seconds=(240.0, 600.0),  # Increased significantly
        adaptive_multiplier=2.5,
        block_keywords=_DEFAULT_PROFILE.block_keywords
        + (
            "pardon our interruption",
            "bot protection",
            "why did this happen",
            "verify you are human",
            "attention required",
            "something went wrong",
            "security challenge",
            "we're sorry",
            "try again later",
        ),
        default_referers=(
            "https://www.ebay.com/",
            "https://www.ebay.com/sch/",
        ),
        reading_time=(2.0, 5.0),
    ),
    "facebook": SiteProfile(
        min_delay=6.0,  # Increased - Facebook is very aggressive
        max_delay=15.0,  # Increased
        cooldown_seconds=(300.0, 600.0),  # Very high cooldown
        adaptive_multiplier=3.0,  # Very aggressive backoff
        block_keywords=_DEFAULT_PROFILE.block_keywords
        + (
            "facebook",
            "log in",
            "unusual activity",
            "security check",
            "confirm your identity",
            "create an account",
            "sign up",
        ),
        default_referers=("https://www.facebook.com/", "https://www.facebook.com/marketplace/"),
        reading_time=(3.0, 8.0),
    ),
    "craigslist": SiteProfile(
        min_delay=3.0,  # Craigslist is more lenient
        max_delay=8.0,
        cooldown_seconds=(90.0, 240.0),
        adaptive_multiplier=2.0,
        block_keywords=_DEFAULT_PROFILE.block_keywords
        + (
            "craigslist",
            "temporarily unavailable",
            "automated access",
            "this ip has been",
            "blocked",
        ),
        default_referers=("https://www.craigslist.org/",),
        reading_time=(1.5, 4.0),
    ),
    "poshmark": SiteProfile(
        min_delay=5.0,  # Increased
        max_delay=12.0,  # Increased
        cooldown_seconds=(150.0, 360.0),
        adaptive_multiplier=2.5,
        block_keywords=_DEFAULT_PROFILE.block_keywords
        + (
            "poshmark",
            "access denied",
            "please verify",
            "security check",
        ),
        default_referers=("https://poshmark.com/", "https://poshmark.com/category/"),
        reading_time=(2.0, 5.0),
    ),
}


@dataclass
class SiteState:
    """Mutable runtime state used to adapt scraper requests."""

    last_request_ts: float = 0.0
    last_success_ts: float = 0.0
    cooldown_until: float = 0.0
    consecutive_failures: int = 0
    recent_blocks: Deque[float] = field(default_factory=lambda: deque(maxlen=10))
    last_headers: Optional[Mapping[str, str]] = None
    session_fingerprint: Optional[str] = None  # Consistent fingerprint per session
    expected_min_response_size: int = 5000  # Track expected response sizes to detect empty blocks
    
    # Burst detection fields
    request_timestamps: Deque[float] = field(default_factory=lambda: deque(maxlen=50))
    burst_cooldown_until: float = 0.0
    
    # Dormant period tracking
    requests_since_dormant: int = 0
    next_dormant_threshold: int = 0  # Randomized between 10-20 requests
    last_dormant_ts: float = 0.0
    
    # Request statistics
    total_requests: int = 0
    total_successes: int = 0
    total_failures: int = 0
    response_times: Deque[float] = field(default_factory=lambda: deque(maxlen=20))


@dataclass
class ProxyHealth:
    """Health tracking for individual proxies."""
    
    proxy_url: str
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    consecutive_failures: int = 0
    last_success_ts: float = 0.0
    last_failure_ts: float = 0.0
    blocked_until: float = 0.0
    avg_response_time: float = 0.0
    response_times: Deque[float] = field(default_factory=lambda: deque(maxlen=10))
    
    @property
    def success_rate(self) -> float:
        if self.total_requests == 0:
            return 1.0
        return self.successful_requests / self.total_requests
    
    @property
    def is_healthy(self) -> bool:
        now = time.time()
        if self.blocked_until > now:
            return False
        if self.consecutive_failures >= 5:
            return False
        if self.total_requests > 10 and self.success_rate < 0.3:
            return False
        return True
    
    def record_success(self, response_time: float) -> None:
        self.total_requests += 1
        self.successful_requests += 1
        self.consecutive_failures = 0
        self.last_success_ts = time.time()
        self.response_times.append(response_time)
        if self.response_times:
            self.avg_response_time = sum(self.response_times) / len(self.response_times)
    
    def record_failure(self, is_block: bool = False) -> None:
        self.total_requests += 1
        self.failed_requests += 1
        self.consecutive_failures += 1
        self.last_failure_ts = time.time()
        
        if is_block or self.consecutive_failures >= 3:
            # Block proxy for increasing duration
            block_duration = min(60 * (2 ** self.consecutive_failures), 3600)
            self.blocked_until = time.time() + block_duration


class AntiBlockManager:
    """Thread-safe manager for anti-blocking state and utilities."""

    def __init__(self):
        self._states: Dict[str, SiteState] = defaultdict(SiteState)
        self._lock = threading.Lock()
        self._proxies: List[str] = []
        self._proxy_lock = threading.Lock()
        self._current_proxy_idx: Dict[str, int] = defaultdict(int)
        
        # Enhanced proxy pool with health tracking
        self._proxy_health: Dict[str, ProxyHealth] = {}
        self._site_proxy_preferences: Dict[str, List[str]] = defaultdict(list)
        
        # Burst detection configuration
        self._burst_threshold = 10  # Max requests in burst window
        self._burst_window = 30.0  # Window in seconds
        self._burst_cooldown_base = 30.0  # Base cooldown after burst
        
        # Dormant period configuration
        self._dormant_min_requests = 10
        self._dormant_max_requests = 20
        self._dormant_min_duration = 120.0  # 2 minutes
        self._dormant_max_duration = 300.0  # 5 minutes
        
        # Load proxies from environment if available
        self._load_proxies_from_env()
        
    def _initialize_dormant_threshold(self, state: SiteState) -> None:
        """Set random threshold for next dormant period."""
        state.next_dormant_threshold = random.randint(
            self._dormant_min_requests, 
            self._dormant_max_requests
        )

    # ---------- State helpers ----------
    def _get_state(self, site_name: Optional[str]) -> SiteState:
        key = site_name or "default"
        return self._states[key]

    def _get_profile(self, site_name: Optional[str]) -> SiteProfile:
        if not site_name:
            return _SITE_SPECIFIC_PROFILES["default"]
        return _SITE_SPECIFIC_PROFILES.get(site_name, _SITE_SPECIFIC_PROFILES["default"])

    # ---------- Timing / Cooldown ----------
    def pre_request_wait(self, site_name: Optional[str]) -> float:
        """Return delay (seconds) to sleep before issuing next request."""

        profile = self._get_profile(site_name)
        state = self._get_state(site_name)

        now = time.time()
        wait = 0.0
        
        # Initialize dormant threshold if not set
        if state.next_dormant_threshold == 0:
            self._initialize_dormant_threshold(state)

        # Check cooldown from rate limiting/blocks
        if state.cooldown_until > now:
            wait = max(wait, state.cooldown_until - now)
            
        # Check burst cooldown
        if state.burst_cooldown_until > now:
            wait = max(wait, state.burst_cooldown_until - now)
        
        # Check for dormant period
        dormant_wait = self._check_dormant_period(site_name, state, now)
        if dormant_wait > 0:
            wait = max(wait, dormant_wait)
        
        # Check for burst detection
        burst_wait = self._detect_burst(state, now)
        if burst_wait > 0:
            wait = max(wait, burst_wait)

        if state.last_request_ts > 0:
            elapsed = now - state.last_request_ts
            # Ensure minimum spacing between requests
            desired = random.uniform(profile.min_delay, profile.max_delay)
            if elapsed < desired:
                wait = max(wait, desired - elapsed)
        else:
            wait = random.uniform(0.3, 0.8)

        # Mild extra delay if we recently had several failures
        if state.consecutive_failures >= 2:
            wait = max(wait, profile.min_delay * (1 + 0.4 * state.consecutive_failures))

        if wait <= 0:
            return 0.0

        jitter = random.uniform(0.1, 0.35)
        return wait + jitter
    
    def _detect_burst(self, state: SiteState, now: float) -> float:
        """Detect if requests are coming too fast and return cooldown if needed."""
        
        # Clean old timestamps outside the window
        cutoff = now - self._burst_window
        while state.request_timestamps and state.request_timestamps[0] < cutoff:
            state.request_timestamps.popleft()
        
        # Check if we're in a burst
        if len(state.request_timestamps) >= self._burst_threshold:
            # Calculate cooldown with exponential factor
            burst_count = len(state.request_timestamps) - self._burst_threshold + 1
            cooldown = self._burst_cooldown_base * (1.5 ** min(burst_count, 5))
            cooldown += random.uniform(5, 15)  # Add jitter
            state.burst_cooldown_until = now + cooldown
            return cooldown
        
        return 0.0
    
    def _check_dormant_period(self, site_name: Optional[str], state: SiteState, now: float) -> float:
        """Check if we should enter a dormant period and return wait time."""
        
        # Skip if we recently had a dormant period
        if state.last_dormant_ts > 0 and (now - state.last_dormant_ts) < 300:
            return 0.0
        
        # Check if we've hit the threshold
        if state.requests_since_dormant >= state.next_dormant_threshold:
            # Enter dormant period
            dormant_duration = random.uniform(
                self._dormant_min_duration, 
                self._dormant_max_duration
            )
            
            # Reset counters
            state.requests_since_dormant = 0
            state.last_dormant_ts = now
            self._initialize_dormant_threshold(state)
            
            # Log the dormant period
            try:
                from utils import logger
                logger.debug(f"{site_name}: entering dormant period for {dormant_duration:.1f}s")
            except Exception:
                pass
            
            return dormant_duration
        
        return 0.0

    def record_request_start(self, site_name: Optional[str]) -> None:
        state = self._get_state(site_name)
        now = time.time()
        state.last_request_ts = now
        state.request_timestamps.append(now)
        state.requests_since_dormant += 1
        state.total_requests += 1

    def record_success(self, site_name: Optional[str], response_time: Optional[float] = None) -> None:
        profile = self._get_profile(site_name)
        state = self._get_state(site_name)
        now = time.time()
        state.last_success_ts = now
        state.consecutive_failures = 0
        state.total_successes += 1
        
        if response_time is not None:
            state.response_times.append(response_time)
        
        # Shrink cooldown sooner after a success
        if state.cooldown_until > 0 and state.cooldown_until - now > profile.min_delay:
            state.cooldown_until = now + profile.min_delay

    def record_failure(self, site_name: Optional[str]) -> None:
        state = self._get_state(site_name)
        state.consecutive_failures += 1
        state.total_failures += 1

    def record_block(self, site_name: Optional[str], signal: str, cooldown_hint: Optional[float] = None) -> None:
        profile = self._get_profile(site_name)
        state = self._get_state(site_name)
        now = time.time()
        state.consecutive_failures += 1
        state.recent_blocks.append(now)

        base = random.uniform(*profile.cooldown_seconds)
        if cooldown_hint:
            base = max(base, cooldown_hint)
        # Escalate cooldown when multiple blocks occur close together
        multiplier = profile.adaptive_multiplier ** min(len(state.recent_blocks), 3)
        cooldown = min(base * multiplier, base * 4)
        state.cooldown_until = max(state.cooldown_until, now + cooldown)

    # ---------- Headers / Fingerprints ----------
    def _infer_sec_fetch_site(self, referer: Optional[str], origin: Optional[str]) -> str:
        """Derive a realistic Sec-Fetch-Site header from referer/origin context."""
        ref_host = urlparse(referer).hostname if referer else None
        origin_host = urlparse(origin).hostname if origin else None

        if ref_host and origin_host:
            return "same-origin" if ref_host == origin_host else "cross-site"
        if ref_host:
            return "same-origin"
        if origin_host:
            return "same-site"
        return "none"

    def build_headers(
        self,
        site_name: Optional[str],
        referer: Optional[str] = None,
        origin: Optional[str] = None,
        base_headers: Optional[Mapping[str, str]] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, str]:
        """Return headers representing a plausible browser request with session consistency."""

        profile = self._get_profile(site_name)
        state = self._get_state(site_name)
        
        # Use session-consistent fingerprint if session_id provided, otherwise create new one
        if session_id:
            fingerprint_key = f"{site_name}:{session_id}"
            if state.session_fingerprint != fingerprint_key:
                state.session_fingerprint = fingerprint_key
        elif not state.session_fingerprint:
            # Create a new session fingerprint for this site
            state.session_fingerprint = f"{site_name}:{int(time.time())}"
        
        # Generate consistent headers for this session using hash of fingerprint
        fingerprint_hash = hashlib.md5(state.session_fingerprint.encode()).hexdigest()
        hash_int = int(fingerprint_hash[:8], 16)
        
        # Select a complete browser profile (consistent per session)
        profile_idx = hash_int % len(_BROWSER_PROFILES)
        browser_profile = _BROWSER_PROFILES[profile_idx]
        
        # Build headers based on the selected browser profile
        headers: Dict[str, str] = {}
        
        # Header order matters for fingerprinting - use realistic Chrome order
        # These are ordered as Chrome actually sends them
        header_order = [
            ("Host", None),  # Will be set by requests library
            ("Connection", "keep-alive"),
            ("Cache-Control", random.choice(_CACHE_CONTROL_VALUES)),
            ("Upgrade-Insecure-Requests", "1"),
            ("User-Agent", browser_profile.user_agent),
            ("Accept", _ACCEPT_HEADERS[hash_int % len(_ACCEPT_HEADERS)]),
            ("Accept-Language", browser_profile.accept_language),
            ("Accept-Encoding", "gzip, deflate, br, zstd"),
        ]
        
        # Add sec-ch-ua headers only for Chromium browsers (not Firefox/Safari)
        if browser_profile.sec_ch_ua:
            header_order.extend([
                ("sec-ch-ua", browser_profile.sec_ch_ua),
                ("sec-ch-ua-mobile", browser_profile.sec_ch_ua_mobile),
                ("sec-ch-ua-platform", browser_profile.sec_ch_ua_platform),
            ])
            
            # Add extended client hints (modern Chrome)
            if browser_profile.sec_ch_ua_full_version_list:
                header_order.extend([
                    ("sec-ch-ua-full-version-list", browser_profile.sec_ch_ua_full_version_list),
                    ("sec-ch-ua-arch", browser_profile.sec_ch_ua_arch),
                    ("sec-ch-ua-bitness", browser_profile.sec_ch_ua_bitness),
                    ("sec-ch-ua-model", browser_profile.sec_ch_ua_model),
                ])
        
        # Add fetch metadata headers
        header_order.extend([
            ("Sec-Fetch-Dest", "document"),
            ("Sec-Fetch-Mode", "navigate"),
            ("Sec-Fetch-Site", self._infer_sec_fetch_site(referer, origin)),
            ("Sec-Fetch-User", "?1"),
        ])
        
        # Add priority header for HTTP/2 (Chrome sends this)
        if browser_profile.sec_ch_ua:  # Chromium browsers
            header_order.append(("Priority", random.choice(_PRIORITY_VALUES)))
        
        # Build the ordered headers dict
        for key, value in header_order:
            if value is not None:
                headers[key] = value

        # Add referer
        if referer:
            headers["Referer"] = referer
        elif profile.default_referers:
            ref_idx = (hash_int // 100) % len(profile.default_referers)
            headers["Referer"] = profile.default_referers[ref_idx]

        if origin:
            headers["Origin"] = origin

        # Merge with base headers (caller's headers take precedence)
        if base_headers:
            for k, v in base_headers.items():
                headers[k] = v

        state.last_headers = headers
        return headers

    def enrich_headers(self, site_name: Optional[str], headers: MutableMapping[str, str]) -> Dict[str, str]:
        """Fill in any missing fingerprint headers for an existing headers dict."""

        new_headers = self.build_headers(site_name, base_headers=headers)
        # Preserve explicit overrides from caller
        for key, value in list(headers.items()):
            new_headers[key] = value
        return new_headers

    def _random_sec_ch_ua(self) -> str:
        """Generate random sec-ch-ua header."""
        brands = [
            '"Not_A Brand";v="{}"'.format(random.randint(8, 99)),
            '"Chromium";v="{}"'.format(random.randint(110, 135)),
            '"Google Chrome";v="{}"'.format(random.randint(110, 135)),
        ]
        random.shuffle(brands)
        return ", ".join(brands)
    
    def _random_sec_ch_ua_consistent(self, hash_str: str) -> str:
        """Generate consistent sec-ch-ua header based on hash."""
        hash_int = int(hash_str[:8], 16)
        v1 = 8 + (hash_int % 92)
        v2 = 110 + ((hash_int // 100) % 26)
        v3 = 110 + ((hash_int // 10000) % 26)
        brands = [
            f'"Not_A Brand";v="{v1}"',
            f'"Chromium";v="{v2}"',
            f'"Google Chrome";v="{v3}"',
        ]
        # Deterministic shuffle
        if (hash_int % 2) == 0:
            brands = [brands[1], brands[0], brands[2]]
        return ", ".join(brands)
    
    def build_mobile_headers(
        self,
        site_name: Optional[str],
        referer: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, str]:
        """Build headers mimicking a mobile browser for fallback requests."""
        
        # Select mobile user agent
        if session_id:
            hash_int = int(hashlib.md5(session_id.encode()).hexdigest()[:8], 16)
            ua_idx = hash_int % len(_MOBILE_USER_AGENTS)
        else:
            ua_idx = random.randint(0, len(_MOBILE_USER_AGENTS) - 1)
        
        headers = {
            "User-Agent": _MOBILE_USER_AGENTS[ua_idx],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": random.choice(_ACCEPT_LANGUAGES),
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none" if not referer else "same-origin",
            "Sec-Fetch-User": "?1",
        }
        
        if referer:
            headers["Referer"] = referer
            
        return headers
    
    def get_site_stats(self, site_name: Optional[str]) -> Dict[str, Any]:
        """Get statistics for a specific site."""
        state = self._get_state(site_name)
        profile = self._get_profile(site_name)
        
        avg_response_time = 0.0
        if state.response_times:
            avg_response_time = sum(state.response_times) / len(state.response_times)
        
        success_rate = 0.0
        if state.total_requests > 0:
            success_rate = state.total_successes / state.total_requests
        
        return {
            "site": site_name or "default",
            "total_requests": state.total_requests,
            "total_successes": state.total_successes,
            "total_failures": state.total_failures,
            "success_rate": round(success_rate * 100, 1),
            "consecutive_failures": state.consecutive_failures,
            "avg_response_time": round(avg_response_time, 2),
            "recent_blocks": len(state.recent_blocks),
            "requests_since_dormant": state.requests_since_dormant,
            "is_in_cooldown": state.cooldown_until > time.time(),
            "is_in_burst_cooldown": state.burst_cooldown_until > time.time(),
        }

    # ---------- Response analysis ----------
    def detect_soft_block(self, site_name: Optional[str], response) -> Optional[str]:
        """Inspect a response for signs of blocking beyond status codes with advanced validation."""

        if response is None:
            return None

        profile = self._get_profile(site_name)
        state = self._get_state(site_name)

        # Check status codes first
        if response.status_code in profile.block_status_codes:
            return f"status:{response.status_code}"

        # Check for suspiciously small responses (likely block/challenge pages)
        content_length = len(response.content) if hasattr(response, 'content') else 0
        if content_length > 0 and content_length < 2000:
            # Very small responses are often challenge pages
            if content_length < 500:
                # Check if it's a valid HTML structure or just a redirect/challenge
                text_sample = response.text[:500].lower() if hasattr(response, 'text') else ""
                # If it's not obviously valid content, it might be a block
                if any(indicator in text_sample for indicator in ['redirect', 'location.href', '<meta http-equiv']):
                    pass  # Valid redirect, not a block
                elif content_length < 200 and 'html' not in text_sample[:50]:
                    return f"response_too_small:{content_length}"
        
        # Check for suspicious response size compared to expected
        if state.expected_min_response_size > 0 and content_length < state.expected_min_response_size * 0.1:
            # Response is less than 10% of expected size - likely blocked
            if content_length < 3000:
                return f"response_size_mismatch:{content_length}"
        
        # Update expected size on successful requests
        if content_length > 1000:
            # Update with moving average
            state.expected_min_response_size = int(
                (state.expected_min_response_size * 0.7) + (content_length * 0.3)
            )

        # Content analysis - check for block indicators
        if isinstance(response.text, str):
            snippet = response.text[: profile.sample_html_bytes].lower()
        else:
            snippet = ""

        # Enhanced keyword detection
        for keyword in profile.block_keywords:
            if keyword.lower() in snippet:
                return f"keyword:{keyword}"
        
        # Check for common challenge/block patterns
        block_patterns = [
            r'<title[^>]*>.*?(?:block|challenge|verify|captcha|cloudflare|ddos).*?</title>',
            r'challenge-platform',
            r'cf-browser-verification',
            r'cf-ray',
            r'distil',
            r'incapsula',
            r'__cf_chl_',
            r'data-ray',
            r'challenge\.js',
            r'checking.*browser',
            r'just.*moment',
            r'enable.*javascript',
        ]
        
        import re
        for pattern in block_patterns:
            if re.search(pattern, snippet, re.IGNORECASE):
                return f"pattern_match:{pattern}"

        return None

    def suggest_retry_delay(self, site_name: Optional[str], attempt: int) -> float:
        """Return seconds to sleep before a retry after a failure with exponential backoff."""

        profile = self._get_profile(site_name)
        # Exponential backoff with jitter
        base = profile.min_delay * (2 ** min(attempt, 4))
        jitter = random.uniform(0.7, 1.3)
        return base * jitter
    
    def _load_proxies_from_env(self) -> None:
        """Load proxy list from environment variable if set."""
        proxy_env = os.environ.get("SCRAPER_PROXIES", "")
        if proxy_env:
            self._proxies = [p.strip() for p in proxy_env.split(",") if p.strip()]
            if self._proxies:
                print(f"Loaded {len(self._proxies)} proxies from environment")
                # Initialize health tracking for each proxy
                for proxy in self._proxies:
                    self._proxy_health[proxy] = ProxyHealth(proxy_url=proxy)
    
    def add_proxies(self, proxies: List[str]) -> int:
        """Add proxies to the pool. Returns number added."""
        added = 0
        with self._proxy_lock:
            for proxy in proxies:
                proxy = proxy.strip()
                if proxy and proxy not in self._proxies:
                    self._proxies.append(proxy)
                    self._proxy_health[proxy] = ProxyHealth(proxy_url=proxy)
                    added += 1
        return added
    
    def remove_proxy(self, proxy: str) -> bool:
        """Remove a proxy from the pool."""
        with self._proxy_lock:
            if proxy in self._proxies:
                self._proxies.remove(proxy)
                self._proxy_health.pop(proxy, None)
                return True
            return False
    
    def get_proxy(self, site_name: Optional[str]) -> Optional[str]:
        """Get best healthy proxy for a site. Returns None if no proxies configured."""
        with self._proxy_lock:
            if not self._proxies:
                return None
            
            # First try site-specific preferences
            site_key = site_name or "default"
            if site_key in self._site_proxy_preferences:
                for proxy in self._site_proxy_preferences[site_key]:
                    if proxy in self._proxy_health and self._proxy_health[proxy].is_healthy:
                        return proxy
            
            # Find best healthy proxy by success rate
            healthy_proxies = [
                (proxy, self._proxy_health.get(proxy))
                for proxy in self._proxies
                if proxy in self._proxy_health and self._proxy_health[proxy].is_healthy
            ]
            
            if healthy_proxies:
                # Sort by success rate, pick from top 3 randomly
                healthy_proxies.sort(key=lambda x: x[1].success_rate, reverse=True)
                top_proxies = healthy_proxies[:min(3, len(healthy_proxies))]
                return random.choice(top_proxies)[0]
            
            # Fallback to round-robin if no healthy proxies
            idx = self._current_proxy_idx[site_key] % len(self._proxies)
            proxy = self._proxies[idx]
            self._current_proxy_idx[site_key] += 1
            return proxy
    
    def rotate_proxy(self, site_name: Optional[str]) -> None:
        """Force rotate to next proxy for a site."""
        with self._proxy_lock:
            key = site_name or "default"
            self._current_proxy_idx[key] = (self._current_proxy_idx[key] + 1) % max(len(self._proxies), 1)
    
    def mark_proxy_success(self, proxy: str, response_time: float) -> None:
        """Record successful request for proxy health tracking."""
        with self._proxy_lock:
            if proxy in self._proxy_health:
                self._proxy_health[proxy].record_success(response_time)
    
    def mark_proxy_failure(self, proxy: str, is_block: bool = False) -> None:
        """Record failed request for proxy health tracking."""
        with self._proxy_lock:
            if proxy in self._proxy_health:
                self._proxy_health[proxy].record_failure(is_block)
    
    def get_proxy_stats(self) -> Dict[str, Any]:
        """Get statistics for all proxies."""
        with self._proxy_lock:
            return {
                "total_proxies": len(self._proxies),
                "healthy_proxies": sum(1 for p in self._proxy_health.values() if p.is_healthy),
                "proxies": [
                    {
                        "url": p.proxy_url[:20] + "..." if len(p.proxy_url) > 20 else p.proxy_url,
                        "success_rate": round(p.success_rate * 100, 1),
                        "total_requests": p.total_requests,
                        "is_healthy": p.is_healthy,
                        "avg_response_time": round(p.avg_response_time, 2),
                    }
                    for p in self._proxy_health.values()
                ]
            }
    
    def set_site_proxy_preference(self, site_name: str, proxies: List[str]) -> None:
        """Set preferred proxies for a specific site."""
        with self._proxy_lock:
            self._site_proxy_preferences[site_name] = [
                p for p in proxies if p in self._proxies
            ]


# Singleton manager used throughout the scrapers
_manager = AntiBlockManager()


# =====================
# Public convenience functions
# =====================

def pre_request_wait(site_name: Optional[str]) -> float:
    return _manager.pre_request_wait(site_name)


def record_request_start(site_name: Optional[str]) -> None:
    _manager.record_request_start(site_name)


def record_success(site_name: Optional[str]) -> None:
    _manager.record_success(site_name)


def record_failure(site_name: Optional[str]) -> None:
    _manager.record_failure(site_name)


def record_block(site_name: Optional[str], signal: str, cooldown_hint: Optional[float] = None) -> None:
    _manager.record_block(site_name, signal, cooldown_hint)


def build_headers(
    site_name: Optional[str],
    referer: Optional[str] = None,
    origin: Optional[str] = None,
    base_headers: Optional[Mapping[str, str]] = None,
    session_id: Optional[str] = None,
) -> Dict[str, str]:
    return _manager.build_headers(site_name, referer, origin, base_headers, session_id)


def get_proxy(site_name: Optional[str]) -> Optional[str]:
    """Get next proxy in rotation for a site."""
    return _manager.get_proxy(site_name)


def rotate_proxy(site_name: Optional[str]) -> None:
    """Force rotate to next proxy for a site."""
    return _manager.rotate_proxy(site_name)


def enrich_headers(site_name: Optional[str], headers: MutableMapping[str, str]) -> Dict[str, str]:
    return _manager.enrich_headers(site_name, headers)


def detect_soft_block(site_name: Optional[str], response) -> Optional[str]:
    return _manager.detect_soft_block(site_name, response)


def suggest_retry_delay(site_name: Optional[str], attempt: int) -> float:
    return _manager.suggest_retry_delay(site_name, attempt)


def build_mobile_headers(
    site_name: Optional[str],
    referer: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Dict[str, str]:
    return _manager.build_mobile_headers(site_name, referer, session_id)


def get_site_stats(site_name: Optional[str]) -> Dict[str, Any]:
    return _manager.get_site_stats(site_name)


def get_proxy_stats() -> Dict[str, Any]:
    return _manager.get_proxy_stats()


def add_proxies(proxies: List[str]) -> int:
    return _manager.add_proxies(proxies)


def mark_proxy_success(proxy: str, response_time: float) -> None:
    _manager.mark_proxy_success(proxy, response_time)


def mark_proxy_failure(proxy: str, is_block: bool = False) -> None:
    _manager.mark_proxy_failure(proxy, is_block)


def randomize_params_order(params: Dict[str, Any]) -> str:
    """Shuffle URL parameters to avoid fingerprinting by param order."""
    items = list(params.items())
    random.shuffle(items)
    return urlencode(items)


def add_request_jitter(site_name: Optional[str] = None) -> float:
    """Returns a random delay with occasional longer pauses for human-like behavior."""
    profile = _manager._get_profile(site_name)
    
    # Base jitter - increased for more human-like behavior
    base = random.uniform(0.3, 1.0)
    
    # 10% chance of a longer pause (2-5 seconds) - simulates reading
    if random.random() < 0.10:
        base += random.uniform(2.0, 5.0)
    
    # 3% chance of a much longer pause (8-15 seconds) - simulates distraction
    if random.random() < 0.03:
        base += random.uniform(8.0, 15.0)
    
    return base


def simulate_reading_time(site_name: Optional[str] = None) -> float:
    """Simulate time spent reading/viewing a page before the next action."""
    profile = _manager._get_profile(site_name)
    
    # Get reading time from profile or use defaults
    reading_range = getattr(profile, 'reading_time', (1.0, 3.0))
    base_time = random.uniform(*reading_range)
    
    # Add occasional longer reading times
    if random.random() < 0.15:
        base_time += random.uniform(2.0, 6.0)
    
    return base_time


def get_progressive_delay(site_name: Optional[str], base_delay: float) -> float:
    """
    Get a progressively longer delay based on recent failure rate.
    This helps avoid blocks by slowing down when we detect issues.
    """
    state = _manager._get_state(site_name)
    
    # Calculate recent failure rate
    recent_blocks = len([ts for ts in state.recent_blocks if time.time() - ts < 600])
    
    # Progressive multiplier based on recent blocks
    if recent_blocks == 0:
        multiplier = 1.0
    elif recent_blocks == 1:
        multiplier = 1.5
    elif recent_blocks == 2:
        multiplier = 2.5
    elif recent_blocks == 3:
        multiplier = 4.0
    else:
        multiplier = 6.0  # Max slowdown
    
    # Also consider consecutive failures
    if state.consecutive_failures >= 3:
        multiplier *= 1.5
    
    return base_delay * multiplier


def get_all_site_stats() -> Dict[str, Dict[str, Any]]:
    """Get statistics for all known sites."""
    known_sites = ["ebay", "craigslist", "mercari", "ksl", "poshmark", "facebook"]
    return {site: get_site_stats(site) for site in known_sites}


__all__ = [
    "build_headers",
    "build_mobile_headers",
    "detect_soft_block",
    "enrich_headers",
    "pre_request_wait",
    "record_block",
    "record_failure",
    "record_request_start",
    "record_success",
    "suggest_retry_delay",
    "get_proxy",
    "rotate_proxy",
    "add_proxies",
    "mark_proxy_success",
    "mark_proxy_failure",
    "get_proxy_stats",
    "get_site_stats",
    "get_all_site_stats",
    "randomize_params_order",
    "add_request_jitter",
    "simulate_reading_time",
    "get_progressive_delay",
]

