"""Advanced anti-blocking utilities for resilient web scraping.

This module implements sophisticated bypass techniques including:

- Realistic, session-consistent browser fingerprints with extensive user agent rotation
- Advanced block detection via content analysis, response size validation, and keyword matching
- Adaptive cooldown tracking with intelligent backoff strategies
- Proxy support infrastructure for IP rotation
- Human-like timing patterns with variable jitter
- Session-based fingerprint consistency (same browser identity per session)

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
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Iterable, List, Mapping, MutableMapping, Optional, Tuple
from urllib.parse import urlparse
import os

# =====================
# HEADER/FINGERPRINT POOLS (EXTENSIVELY EXPANDED)
# =====================

# Comprehensive, current user agent pool (2024-2025 Chrome/Firefox/Edge/Safari)
_USER_AGENTS: Tuple[str, ...] = (
    # Chrome 131-135 (latest)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    # Chrome Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    # Chrome Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    # Edge (Chromium-based)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36 Edg/135.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36 Edg/134.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36 Edg/135.0.0.0",
    # Safari (macOS)
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    # Firefox (latest)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:135.0) Gecko/20100101 Firefox/135.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:134.0) Gecko/20100101 Firefox/134.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:135.0) Gecko/20100101 Firefox/135.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:135.0) Gecko/20100101 Firefox/135.0",
    # Older but still common (for diversity)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
)

_ACCEPT_LANGUAGES: Tuple[str, ...] = (
    "en-US,en;q=0.9",
    "en-US,en;q=0.9,es;q=0.8",
    "en-US,en;q=0.8,en-GB;q=0.7",
    "en-US,en;q=0.7,es;q=0.4",
    "en-US,en;q=0.8,fr;q=0.4",
    "en-US,en;q=0.75,es-419;q=0.5",
    "en-GB,en;q=0.9",
    "en-CA,en;q=0.9",
    "en-AU,en;q=0.9",
)

_ACCEPT_HEADERS: Tuple[str, ...] = (
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "text/html,application/xml;q=0.9,*/*;q=0.8",
)

_SEC_CH_UA_PLATFORMS: Tuple[str, ...] = (
    '"Windows"',
    '"macOS"',
    '"Linux"',
)

_CACHE_CONTROL_VALUES: Tuple[str, ...] = (
    "no-cache",
    "max-age=0",
    "no-store",
)


# =====================
# BLOCK/COOLDOWN PROFILES
# =====================

@dataclass
class SiteProfile:
    """Configuration for a site's anti-blocking behavior."""

    min_delay: float = 1.5
    max_delay: float = 4.5
    post_success_jitter: Tuple[float, float] = (0.4, 1.2)
    block_status_codes: Tuple[int, ...] = (403, 429)
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
    )
    soft_block_css_selectors: Tuple[str, ...] = ()
    cooldown_seconds: Tuple[float, float] = (45.0, 120.0)
    adaptive_multiplier: float = 1.8
    sample_html_bytes: int = 4096
    default_referers: Tuple[str, ...] = ()


_DEFAULT_PROFILE = SiteProfile()

_SITE_SPECIFIC_PROFILES: Dict[str, SiteProfile] = {
    "default": _DEFAULT_PROFILE,
    "ksl": SiteProfile(
        min_delay=2.5,
        max_delay=6.0,
        cooldown_seconds=(90.0, 240.0),
        block_keywords=(
            "ksl classified",
            "unusual activity",
            "slow down",
            "verify",
            "blocked",
            "access denied",
            "are you a robot",
            "403",
        ),
        default_referers=("https://classifieds.ksl.com/",),
    ),
    "mercari": SiteProfile(
        min_delay=3.0,
        max_delay=7.0,
        cooldown_seconds=(120.0, 300.0),
        block_keywords=(
            "mercari",
            "unusual traffic",
            "access denied",
            "please verify",
            "for security reasons",
            "are you a robot",
            "403",
            "bot detection",
        ),
        default_referers=("https://www.mercari.com/",),
    ),
    "ebay": SiteProfile(
        min_delay=4.0,
        max_delay=8.0,
        cooldown_seconds=(180.0, 480.0),
        adaptive_multiplier=2.2,
        block_keywords=_DEFAULT_PROFILE.block_keywords
        + (
            "pardon our interruption",
            "bot protection",
            "why did this happen",
            "verify you are human",
            "attention required",
            "something went wrong",
            "security challenge",
        ),
        default_referers=(
            "https://www.ebay.com/",
            "https://www.ebay.com/deals",
            "https://www.ebay.com/b/Auto-Parts-and-Vehicles/6000/bn_1865334",
        ),
    ),
    "facebook": SiteProfile(
        min_delay=3.0,
        max_delay=6.0,
        cooldown_seconds=(120.0, 300.0),
        adaptive_multiplier=2.0,
        block_keywords=_DEFAULT_PROFILE.block_keywords
        + (
            "facebook",
            "log in",
            "unusual activity",
            "security check",
            "confirm your identity",
        ),
        default_referers=("https://www.facebook.com/",),
    ),
    "craigslist": SiteProfile(
        min_delay=2.0,
        max_delay=5.0,
        cooldown_seconds=(60.0, 180.0),
        adaptive_multiplier=1.8,
        block_keywords=_DEFAULT_PROFILE.block_keywords
        + (
            "craigslist",
            "temporarily unavailable",
            "automated access",
        ),
        default_referers=("https://www.craigslist.org/",),
    ),
    "poshmark": SiteProfile(
        min_delay=3.5,
        max_delay=7.0,
        cooldown_seconds=(90.0, 240.0),
        adaptive_multiplier=2.0,
        block_keywords=_DEFAULT_PROFILE.block_keywords
        + (
            "poshmark",
            "access denied",
            "please verify",
        ),
        default_referers=("https://www.poshmark.com/",),
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


class AntiBlockManager:
    """Thread-safe manager for anti-blocking state and utilities."""

    def __init__(self):
        self._states: Dict[str, SiteState] = defaultdict(SiteState)
        self._lock = threading.Lock()
        self._proxies: List[str] = []
        self._proxy_lock = threading.Lock()
        self._current_proxy_idx: Dict[str, int] = defaultdict(int)
        
        # Load proxies from environment if available
        self._load_proxies_from_env()

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

        if state.cooldown_until > now:
            wait = max(wait, state.cooldown_until - now)

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

    def record_request_start(self, site_name: Optional[str]) -> None:
        state = self._get_state(site_name)
        state.last_request_ts = time.time()

    def record_success(self, site_name: Optional[str]) -> None:
        profile = self._get_profile(site_name)
        state = self._get_state(site_name)
        now = time.time()
        state.last_success_ts = now
        state.consecutive_failures = 0
        # Shrink cooldown sooner after a success
        if state.cooldown_until > 0 and state.cooldown_until - now > profile.min_delay:
            state.cooldown_until = now + profile.min_delay

    def record_failure(self, site_name: Optional[str]) -> None:
        state = self._get_state(site_name)
        state.consecutive_failures += 1

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
        
        # Use hash to deterministically select from pools (consistent per session)
        user_agent_idx = hash_int % len(_USER_AGENTS)
        accept_idx = (hash_int // len(_USER_AGENTS)) % len(_ACCEPT_HEADERS)
        lang_idx = (hash_int // (len(_USER_AGENTS) * len(_ACCEPT_HEADERS))) % len(_ACCEPT_LANGUAGES)
        platform_idx = (hash_int // (len(_USER_AGENTS) * len(_ACCEPT_HEADERS) * len(_ACCEPT_LANGUAGES))) % len(_SEC_CH_UA_PLATFORMS)
        
        # Add slight variation for freshness while maintaining consistency
        variation = int(time.time() // 3600)  # Changes hourly
        user_agent_idx = (user_agent_idx + variation) % len(_USER_AGENTS)
        
        headers: Dict[str, str] = {
            "User-Agent": _USER_AGENTS[user_agent_idx],
            "Accept": _ACCEPT_HEADERS[accept_idx],
            "Accept-Language": _ACCEPT_LANGUAGES[lang_idx],
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "DNT": "1" if (hash_int % 2) == 0 else "0",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-User": "?1",
            "Cache-Control": random.choice(_CACHE_CONTROL_VALUES),
            "sec-ch-ua": self._random_sec_ch_ua_consistent(fingerprint_hash),
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": _SEC_CH_UA_PLATFORMS[platform_idx],
            "Pragma": "no-cache",  # Additional header for realism
        }

        headers["Sec-Fetch-Site"] = self._infer_sec_fetch_site(referer, origin)

        if referer:
            headers["Referer"] = referer
        elif profile.default_referers:
            ref_idx = (hash_int // 100) % len(profile.default_referers) if profile.default_referers else 0
            headers["Referer"] = profile.default_referers[ref_idx]

        if origin:
            headers["Origin"] = origin

        if base_headers:
            merged = dict(base_headers)
            merged.update({k: v for k, v in headers.items() if k not in merged})
            headers = merged

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
    
    def get_proxy(self, site_name: Optional[str]) -> Optional[str]:
        """Get next proxy in rotation for a site. Returns None if no proxies configured."""
        with self._proxy_lock:
            if not self._proxies:
                return None
            idx = self._current_proxy_idx[site_name or "default"] % len(self._proxies)
            proxy = self._proxies[idx]
            self._current_proxy_idx[site_name or "default"] += 1
            return proxy
    
    def rotate_proxy(self, site_name: Optional[str]) -> None:
        """Force rotate to next proxy for a site."""
        with self._proxy_lock:
            key = site_name or "default"
            self._current_proxy_idx[key] = (self._current_proxy_idx[key] + 1) % max(len(self._proxies), 1)


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


__all__ = [
    "build_headers",
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
]

