"""Utilities for keeping scrapers resilient without relying on third-party services.

This module centralizes anti-blocking strategies that can be shared by all scrapers,
including:

- Realistic, rotating browser fingerprints (headers, sec-ch hints, Accept-Language)
- Adaptive cooldown tracking after blocks, rate limits, or network failures
- Soft block detection via response analysis
- Dynamic request spacing with jitter to mimic human browsing patterns

These helpers operate entirely locally—no external proxy providers or SaaS dependencies
are required. Individual scrapers can opt-in by using the public functions exported
here. The module keeps a lightweight in-memory state so that behavior adapts over
time within the current process.
"""

from __future__ import annotations

import math
import random
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Iterable, List, Mapping, MutableMapping, Optional, Tuple
from urllib.parse import urlparse

# =====================
# HEADER/FINGERPRINT POOLS
# =====================

_USER_AGENTS: Tuple[str, ...] = (
    # Modern Chrome (Windows/Mac/Linux)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
)

_ACCEPT_LANGUAGES: Tuple[str, ...] = (
    "en-US,en;q=0.9",
    "en-US,en;q=0.8,en-GB;q=0.7",
    "en-US,en;q=0.7,es;q=0.4",
    "en-US,en;q=0.8,fr;q=0.4",
    "en-US,en;q=0.75,es-419;q=0.5",
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
        ),
        default_referers=(
            "https://www.ebay.com/",
            "https://www.ebay.com/deals",
            "https://www.ebay.com/b/Auto-Parts-and-Vehicles/6000/bn_1865334",
        ),
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


class AntiBlockManager:
    """Thread-safe manager for anti-blocking state and utilities."""

    def __init__(self):
        self._states: Dict[str, SiteState] = defaultdict(SiteState)
        self._lock = threading.Lock()

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
    ) -> Dict[str, str]:
        """Return headers representing a plausible browser request."""

        profile = self._get_profile(site_name)
        headers: Dict[str, str] = {
            "User-Agent": random.choice(_USER_AGENTS),
            "Accept": random.choice(_ACCEPT_HEADERS),
            "Accept-Language": random.choice(_ACCEPT_LANGUAGES),
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "DNT": random.choice(("1", "0")),
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-User": "?1",
            "Cache-Control": random.choice(_CACHE_CONTROL_VALUES),
            "sec-ch-ua": self._random_sec_ch_ua(),
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": random.choice(_SEC_CH_UA_PLATFORMS),
        }

        headers["Sec-Fetch-Site"] = self._infer_sec_fetch_site(referer, origin)

        if referer:
            headers["Referer"] = referer
        elif profile.default_referers:
            headers["Referer"] = random.choice(profile.default_referers)

        if origin:
            headers["Origin"] = origin

        if base_headers:
            merged = dict(base_headers)
            merged.update({k: v for k, v in headers.items() if k not in merged})
            headers = merged

        self._get_state(site_name).last_headers = headers
        return headers

    def enrich_headers(self, site_name: Optional[str], headers: MutableMapping[str, str]) -> Dict[str, str]:
        """Fill in any missing fingerprint headers for an existing headers dict."""

        new_headers = self.build_headers(site_name, base_headers=headers)
        # Preserve explicit overrides from caller
        for key, value in list(headers.items()):
            new_headers[key] = value
        return new_headers

    def _random_sec_ch_ua(self) -> str:
        brands = [
            '"Not_A Brand";v="{}"'.format(random.randint(8, 99)),
            '"Chromium";v="{}"'.format(random.randint(110, 122)),
            '"Google Chrome";v="{}"'.format(random.randint(110, 122)),
        ]
        random.shuffle(brands)
        return ", ".join(brands)

    # ---------- Response analysis ----------
    def detect_soft_block(self, site_name: Optional[str], response) -> Optional[str]:
        """Inspect a response for signs of blocking beyond status codes."""

        if response is None:
            return None

        profile = self._get_profile(site_name)

        if response.status_code in profile.block_status_codes:
            return f"status:{response.status_code}"

        # Only sample a limited portion to avoid heavy memory usage
        if isinstance(response.text, str):
            snippet = response.text[: profile.sample_html_bytes].lower()
        else:
            snippet = ""

        for keyword in profile.block_keywords:
            if keyword in snippet:
                return f"keyword:{keyword}"

        return None

    def suggest_retry_delay(self, site_name: Optional[str], attempt: int) -> float:
        """Return seconds to sleep before a retry after a failure."""

        profile = self._get_profile(site_name)
        base = profile.min_delay * (2 ** min(attempt, 3))
        jitter = random.uniform(0.5, 1.5)
        return base * jitter


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
) -> Dict[str, str]:
    return _manager.build_headers(site_name, referer, origin, base_headers)


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
]

