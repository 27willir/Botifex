"""Stealth HTTP Client with TLS Fingerprint Impersonation.

This module provides undetectable HTTP requests by:
- Using curl_cffi to impersonate real browser TLS fingerprints (JA3/JA4)
- Maintaining session consistency with proper cookie handling
- Rotating browser impersonation profiles intelligently
- Falling back gracefully when curl_cffi is unavailable

The key insight is that bot detection systems primarily identify scrapers through
TLS handshake fingerprints, not HTTP headers. curl_cffi solves this by using
libcurl with browser-identical TLS implementations.
"""

from __future__ import annotations

import random
import time
import threading
import hashlib
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse
from dataclasses import dataclass, field
from collections import deque

from utils import logger

# Try to import curl_cffi for TLS fingerprint impersonation
_CURL_CFFI_AVAILABLE = False
_curl_requests = None

try:
    from curl_cffi import requests as curl_requests
    from curl_cffi.requests import Session as CurlSession
    _curl_requests = curl_requests
    _CURL_CFFI_AVAILABLE = True
    logger.info("curl_cffi loaded - TLS fingerprint impersonation enabled")
except ImportError:
    logger.warning("curl_cffi not available - falling back to requests (detectable TLS fingerprint)")
    import requests as _fallback_requests

# Fallback to standard requests if curl_cffi unavailable
try:
    import requests as std_requests
except ImportError:
    std_requests = None


# ======================
# BROWSER IMPERSONATION PROFILES
# ======================
# These are the exact browser versions that curl_cffi can impersonate
# The TLS fingerprint will match these browsers exactly

@dataclass
class ImpersonationProfile:
    """Complete browser impersonation profile for curl_cffi."""
    name: str
    impersonate: str  # curl_cffi impersonate string
    user_agent: str
    sec_ch_ua: str
    sec_ch_ua_platform: str
    sec_ch_ua_mobile: str = "?0"
    accept_language: str = "en-US,en;q=0.9"
    platform: str = "Windows"
    is_mobile: bool = False
    # Weight for random selection (higher = more likely)
    weight: int = 10


# Current browser profiles that curl_cffi supports (December 2024)
# These MUST match curl_cffi's supported impersonation targets
# Check available: curl_cffi.requests.BrowserType
IMPERSONATION_PROFILES: Tuple[ImpersonationProfile, ...] = (
    # Chrome profiles (most common, heavily weighted)
    ImpersonationProfile(
        name="chrome_131_win",
        impersonate="chrome131",
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        sec_ch_ua='"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        sec_ch_ua_platform='"Windows"',
        accept_language="en-US,en;q=0.9",
        platform="Windows",
        weight=25,
    ),
    ImpersonationProfile(
        name="chrome_124_win",
        impersonate="chrome124",
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        sec_ch_ua='"Google Chrome";v="124", "Chromium";v="124", "Not_A Brand";v="24"',
        sec_ch_ua_platform='"Windows"',
        accept_language="en-US,en;q=0.9",
        platform="Windows",
        weight=15,
    ),
    ImpersonationProfile(
        name="chrome_120_win",
        impersonate="chrome120",
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        sec_ch_ua='"Google Chrome";v="120", "Chromium";v="120", "Not_A Brand";v="24"',
        sec_ch_ua_platform='"Windows"',
        accept_language="en-US,en;q=0.9",
        platform="Windows",
        weight=10,
    ),
    ImpersonationProfile(
        name="chrome_131_mac",
        impersonate="chrome131",
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        sec_ch_ua='"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        sec_ch_ua_platform='"macOS"',
        accept_language="en-US,en;q=0.9",
        platform="macOS",
        weight=15,
    ),
    # Edge profiles
    ImpersonationProfile(
        name="edge_99_win",
        impersonate="edge99",
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.51 Safari/537.36 Edg/99.0.0.0",
        sec_ch_ua='"Microsoft Edge";v="99", "Chromium";v="99", "Not_A Brand";v="24"',
        sec_ch_ua_platform='"Windows"',
        accept_language="en-US,en;q=0.9",
        platform="Windows",
        weight=8,
    ),
    # Firefox profiles (different TLS fingerprint)
    ImpersonationProfile(
        name="firefox_133",
        impersonate="firefox133",
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
        sec_ch_ua="",  # Firefox doesn't send sec-ch-ua
        sec_ch_ua_platform="",
        accept_language="en-US,en;q=0.5",
        platform="Windows",
        weight=10,
    ),
    ImpersonationProfile(
        name="firefox_135",
        impersonate="firefox135",
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:135.0) Gecko/20100101 Firefox/135.0",
        sec_ch_ua="",
        sec_ch_ua_platform="",
        accept_language="en-US,en;q=0.5",
        platform="Windows",
        weight=8,
    ),
    # Safari profiles
    ImpersonationProfile(
        name="safari_18_mac",
        impersonate="safari18_0",
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
        sec_ch_ua="",  # Safari doesn't send sec-ch-ua
        sec_ch_ua_platform="",
        accept_language="en-US,en;q=0.9",
        platform="macOS",
        weight=10,
    ),
    ImpersonationProfile(
        name="safari_17_mac",
        impersonate="safari17_0",
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
        sec_ch_ua="",
        sec_ch_ua_platform="",
        accept_language="en-US,en;q=0.9",
        platform="macOS",
        weight=8,
    ),
    # Mobile profiles for fallback
    ImpersonationProfile(
        name="chrome_mobile_131",
        impersonate="chrome131_android",
        user_agent="Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36",
        sec_ch_ua='"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        sec_ch_ua_platform='"Android"',
        sec_ch_ua_mobile="?1",
        accept_language="en-US,en;q=0.9",
        platform="Android",
        is_mobile=True,
        weight=8,
    ),
    ImpersonationProfile(
        name="safari_ios_18",
        impersonate="safari18_0_ios",
        user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
        sec_ch_ua="",
        sec_ch_ua_platform="",
        accept_language="en-US,en;q=0.9",
        platform="iOS",
        is_mobile=True,
        weight=8,
    ),
)

# Build weighted selection list
_PROFILE_WEIGHTS = []
for profile in IMPERSONATION_PROFILES:
    _PROFILE_WEIGHTS.extend([profile] * profile.weight)


def get_random_profile(mobile: bool = False, session_seed: Optional[str] = None) -> ImpersonationProfile:
    """Get a random impersonation profile.
    
    Args:
        mobile: If True, prefer mobile profiles
        session_seed: If provided, use consistent profile for session
        
    Returns:
        ImpersonationProfile for browser impersonation
    """
    if session_seed:
        # Use hash for deterministic but random-looking selection
        hash_int = int(hashlib.md5(session_seed.encode()).hexdigest()[:8], 16)
        if mobile:
            mobile_profiles = [p for p in IMPERSONATION_PROFILES if p.is_mobile]
            return mobile_profiles[hash_int % len(mobile_profiles)]
        return IMPERSONATION_PROFILES[hash_int % len(IMPERSONATION_PROFILES)]
    
    if mobile:
        mobile_profiles = [p for p in _PROFILE_WEIGHTS if p.is_mobile]
        return random.choice(mobile_profiles) if mobile_profiles else random.choice(_PROFILE_WEIGHTS)
    
    return random.choice(_PROFILE_WEIGHTS)


# ======================
# STEALTH SESSION MANAGER
# ======================

@dataclass
class SessionState:
    """Track state for a stealth session."""
    profile: ImpersonationProfile
    session: Any  # curl_cffi Session or requests Session
    created_at: float = field(default_factory=time.time)
    request_count: int = 0
    last_request_ts: float = 0.0
    consecutive_failures: int = 0
    total_successes: int = 0
    total_failures: int = 0


class StealthSessionManager:
    """Manages stealth HTTP sessions with browser impersonation.
    
    Key features:
    - Session-consistent browser fingerprints (TLS + headers)
    - Automatic session rotation on failures
    - Cookie persistence across requests
    - Intelligent profile selection
    """
    
    def __init__(self):
        self._sessions: Dict[str, SessionState] = {}
        self._lock = threading.Lock()
        self._max_session_age = 1800  # 30 minutes
        self._max_requests_per_session = 100
        self._max_consecutive_failures = 3
    
    def _session_key(self, site_name: str, user_id: Optional[str] = None) -> str:
        """Generate session key for caching."""
        user_part = user_id or "global"
        return f"{site_name}:{user_part}"
    
    def _create_session(
        self,
        profile: ImpersonationProfile,
        proxy: Optional[str] = None,
    ) -> Any:
        """Create a new stealth session with browser impersonation."""
        if _CURL_CFFI_AVAILABLE:
            try:
                # Create curl_cffi session with browser impersonation
                session = _curl_requests.Session(impersonate=profile.impersonate)
                
                # Set default headers matching the impersonation profile
                session.headers.update({
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                    "Accept-Language": profile.accept_language,
                    "Accept-Encoding": "gzip, deflate, br",
                    "Connection": "keep-alive",
                    "Upgrade-Insecure-Requests": "1",
                    "Cache-Control": "max-age=0",
                })
                
                # Add sec-ch-ua headers for Chromium browsers
                if profile.sec_ch_ua:
                    session.headers.update({
                        "sec-ch-ua": profile.sec_ch_ua,
                        "sec-ch-ua-mobile": profile.sec_ch_ua_mobile,
                        "sec-ch-ua-platform": profile.sec_ch_ua_platform,
                    })
                
                # Set proxy if provided
                if proxy:
                    session.proxies = {
                        "http": proxy,
                        "https": proxy,
                    }
                
                logger.debug(f"Created curl_cffi session with {profile.impersonate} impersonation")
                return session
                
            except Exception as e:
                logger.warning(f"Failed to create curl_cffi session: {e}, falling back to requests")
        
        # Fallback to standard requests (detectable but functional)
        if std_requests:
            session = std_requests.Session()
            session.headers.update({
                "User-Agent": profile.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": profile.accept_language,
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
            })
            if profile.sec_ch_ua:
                session.headers.update({
                    "sec-ch-ua": profile.sec_ch_ua,
                    "sec-ch-ua-mobile": profile.sec_ch_ua_mobile,
                    "sec-ch-ua-platform": profile.sec_ch_ua_platform,
                })
            if proxy:
                session.proxies = {"http": proxy, "https": proxy}
            return session
        
        raise RuntimeError("No HTTP client available (neither curl_cffi nor requests)")
    
    def get_session(
        self,
        site_name: str,
        user_id: Optional[str] = None,
        mobile: bool = False,
        proxy: Optional[str] = None,
        force_new: bool = False,
    ) -> Tuple[Any, ImpersonationProfile]:
        """Get or create a stealth session for a site.
        
        Args:
            site_name: Name of the target site
            user_id: Optional user ID for session isolation
            mobile: Whether to use mobile profile
            proxy: Optional proxy URL
            force_new: Force creation of new session
            
        Returns:
            Tuple of (session, profile)
        """
        key = self._session_key(site_name, user_id)
        now = time.time()
        
        with self._lock:
            # Check for existing valid session
            if not force_new and key in self._sessions:
                state = self._sessions[key]
                
                # Check if session is still valid
                session_age = now - state.created_at
                if (session_age < self._max_session_age and
                    state.request_count < self._max_requests_per_session and
                    state.consecutive_failures < self._max_consecutive_failures):
                    return state.session, state.profile
                
                # Session expired or failed too many times
                try:
                    state.session.close()
                except Exception:
                    pass
                del self._sessions[key]
            
            # Create new session
            session_seed = f"{site_name}:{user_id}:{int(now)}"
            profile = get_random_profile(mobile=mobile, session_seed=session_seed)
            session = self._create_session(profile, proxy)
            
            self._sessions[key] = SessionState(
                profile=profile,
                session=session,
                created_at=now,
            )
            
            return session, profile
    
    def record_request(self, site_name: str, user_id: Optional[str] = None) -> None:
        """Record that a request was made."""
        key = self._session_key(site_name, user_id)
        with self._lock:
            if key in self._sessions:
                state = self._sessions[key]
                state.request_count += 1
                state.last_request_ts = time.time()
    
    def record_success(self, site_name: str, user_id: Optional[str] = None) -> None:
        """Record a successful request."""
        key = self._session_key(site_name, user_id)
        with self._lock:
            if key in self._sessions:
                state = self._sessions[key]
                state.consecutive_failures = 0
                state.total_successes += 1
    
    def record_failure(self, site_name: str, user_id: Optional[str] = None) -> None:
        """Record a failed request."""
        key = self._session_key(site_name, user_id)
        with self._lock:
            if key in self._sessions:
                state = self._sessions[key]
                state.consecutive_failures += 1
                state.total_failures += 1
    
    def invalidate_session(self, site_name: str, user_id: Optional[str] = None) -> None:
        """Force session to be recreated on next request."""
        key = self._session_key(site_name, user_id)
        with self._lock:
            if key in self._sessions:
                try:
                    self._sessions[key].session.close()
                except Exception:
                    pass
                del self._sessions[key]
    
    def get_stats(self, site_name: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        """Get session statistics."""
        key = self._session_key(site_name, user_id)
        with self._lock:
            if key not in self._sessions:
                return {"exists": False}
            
            state = self._sessions[key]
            return {
                "exists": True,
                "profile": state.profile.name,
                "impersonate": state.profile.impersonate,
                "age_seconds": time.time() - state.created_at,
                "request_count": state.request_count,
                "consecutive_failures": state.consecutive_failures,
                "total_successes": state.total_successes,
                "total_failures": state.total_failures,
            }


# Global session manager instance
_session_manager = StealthSessionManager()


# ======================
# STEALTH REQUEST FUNCTIONS
# ======================

def stealth_get(
    url: str,
    site_name: str,
    user_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    proxy: Optional[str] = None,
    timeout: int = 30,
    mobile: bool = False,
    allow_redirects: bool = True,
    **kwargs,
) -> Optional[Any]:
    """Make a stealth GET request with browser impersonation.
    
    This function uses curl_cffi to make requests with real browser TLS fingerprints,
    making them indistinguishable from actual browser traffic.
    
    Args:
        url: URL to request
        site_name: Name of the target site (for session management)
        user_id: Optional user ID for session isolation
        headers: Additional headers to include
        proxy: Optional proxy URL
        timeout: Request timeout in seconds
        mobile: Use mobile browser profile
        allow_redirects: Follow redirects
        **kwargs: Additional arguments passed to session.get()
        
    Returns:
        Response object or None on failure
    """
    session, profile = _session_manager.get_session(
        site_name,
        user_id=user_id,
        mobile=mobile,
        proxy=proxy,
    )
    
    # Build request headers
    request_headers = {
        "User-Agent": profile.user_agent,
    }
    
    # Add sec-fetch headers for navigation requests
    parsed = urlparse(url)
    request_headers.update({
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    })
    
    # Merge custom headers
    if headers:
        request_headers.update(headers)
    
    try:
        _session_manager.record_request(site_name, user_id)
        
        response = session.get(
            url,
            headers=request_headers,
            timeout=timeout,
            allow_redirects=allow_redirects,
            **kwargs,
        )
        
        # Check for success
        if response.status_code < 400:
            _session_manager.record_success(site_name, user_id)
        else:
            _session_manager.record_failure(site_name, user_id)
        
        return response
        
    except Exception as e:
        logger.debug(f"Stealth request failed: {e}")
        _session_manager.record_failure(site_name, user_id)
        return None


def stealth_post(
    url: str,
    site_name: str,
    user_id: Optional[str] = None,
    data: Optional[Dict] = None,
    json_data: Optional[Dict] = None,
    headers: Optional[Dict[str, str]] = None,
    proxy: Optional[str] = None,
    timeout: int = 30,
    mobile: bool = False,
    **kwargs,
) -> Optional[Any]:
    """Make a stealth POST request with browser impersonation.
    
    Args:
        url: URL to request
        site_name: Name of the target site
        user_id: Optional user ID
        data: Form data to post
        json_data: JSON data to post
        headers: Additional headers
        proxy: Optional proxy URL
        timeout: Request timeout
        mobile: Use mobile profile
        **kwargs: Additional arguments
        
    Returns:
        Response object or None on failure
    """
    session, profile = _session_manager.get_session(
        site_name,
        user_id=user_id,
        mobile=mobile,
        proxy=proxy,
    )
    
    request_headers = {
        "User-Agent": profile.user_agent,
    }
    
    if json_data:
        request_headers["Content-Type"] = "application/json"
        request_headers["Accept"] = "application/json"
    
    if headers:
        request_headers.update(headers)
    
    try:
        _session_manager.record_request(site_name, user_id)
        
        if json_data:
            response = session.post(
                url,
                json=json_data,
                headers=request_headers,
                timeout=timeout,
                **kwargs,
            )
        else:
            response = session.post(
                url,
                data=data,
                headers=request_headers,
                timeout=timeout,
                **kwargs,
            )
        
        if response.status_code < 400:
            _session_manager.record_success(site_name, user_id)
        else:
            _session_manager.record_failure(site_name, user_id)
        
        return response
        
    except Exception as e:
        logger.debug(f"Stealth POST request failed: {e}")
        _session_manager.record_failure(site_name, user_id)
        return None


def get_session_stats(site_name: str, user_id: Optional[str] = None) -> Dict[str, Any]:
    """Get statistics for a stealth session."""
    return _session_manager.get_stats(site_name, user_id)


def invalidate_session(site_name: str, user_id: Optional[str] = None) -> None:
    """Invalidate a session to force recreation on next request."""
    _session_manager.invalidate_session(site_name, user_id)


def is_curl_cffi_available() -> bool:
    """Check if curl_cffi is available for TLS fingerprint impersonation."""
    return _CURL_CFFI_AVAILABLE


def get_available_impersonations() -> List[str]:
    """Get list of available browser impersonation profiles."""
    return [p.name for p in IMPERSONATION_PROFILES]


__all__ = [
    "stealth_get",
    "stealth_post",
    "get_session_stats",
    "invalidate_session",
    "is_curl_cffi_available",
    "get_available_impersonations",
    "get_random_profile",
    "ImpersonationProfile",
    "IMPERSONATION_PROFILES",
]

