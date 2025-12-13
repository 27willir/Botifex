"""WAF/Anti-Bot Challenge Bypass Module.

This module handles bypassing Web Application Firewalls and anti-bot systems:
- Cloudflare (including Turnstile challenges)
- DataDome
- PerimeterX
- Imperva/Incapsula
- Generic CAPTCHA detection

The primary approach is to use stealth browser automation to solve challenges
automatically when possible, and to detect when human intervention is required.

Usage:
    from scrapers.waf_bypass import bypass_challenge, detect_waf_type
    
    # Check if response is a challenge page
    waf_type = detect_waf_type(response)
    
    if waf_type:
        # Attempt to bypass
        result = await bypass_challenge(url, waf_type)
        if result.success:
            html_content = result.content
            cookies = result.cookies
"""

from __future__ import annotations

import asyncio
import random
import time
import re
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Tuple

from utils import logger


class WAFType(Enum):
    """Types of WAF/anti-bot systems."""
    CLOUDFLARE = "cloudflare"
    CLOUDFLARE_TURNSTILE = "cloudflare_turnstile"
    DATADOME = "datadome"
    PERIMETERX = "perimeterx"
    IMPERVA = "imperva"
    AKAMAI = "akamai"
    GENERIC_CAPTCHA = "generic_captcha"
    RATE_LIMIT = "rate_limit"
    UNKNOWN = "unknown"


@dataclass
class WAFDetectionResult:
    """Result of WAF detection."""
    detected: bool
    waf_type: Optional[WAFType] = None
    confidence: float = 0.0
    indicators: List[str] = None
    requires_js: bool = False
    requires_human: bool = False
    cooldown_hint: int = 60  # Suggested wait time
    
    def __post_init__(self):
        if self.indicators is None:
            self.indicators = []


@dataclass
class BypassResult:
    """Result of bypass attempt."""
    success: bool
    content: Optional[str] = None
    cookies: Optional[List[Dict]] = None
    waf_type: Optional[WAFType] = None
    method_used: Optional[str] = None
    response_time: float = 0.0
    error: Optional[str] = None


# ======================
# WAF DETECTION PATTERNS
# ======================

WAF_PATTERNS = {
    WAFType.CLOUDFLARE: {
        "html_patterns": [
            r"cf-browser-verification",
            r"__cf_chl_",
            r"cf-ray",
            r"data-ray",
            r"challenge-platform",
            r"checking your browser",
            r"just a moment",
            r"cloudflare",
            r"please wait.*while we verify",
            r"enable javascript and cookies",
            r"ddos-protection",
        ],
        "headers": [
            ("cf-ray", None),
            ("cf-cache-status", None),
            ("server", "cloudflare"),
        ],
        "title_patterns": [
            r"just a moment",
            r"attention required",
            r"cloudflare",
        ],
    },
    
    WAFType.CLOUDFLARE_TURNSTILE: {
        "html_patterns": [
            r"turnstile",
            r"cf-turnstile",
            r"challenges\.cloudflare\.com/turnstile",
        ],
        "headers": [],
        "title_patterns": [],
    },
    
    WAFType.DATADOME: {
        "html_patterns": [
            r"datadome",
            r"dd\.js",
            r"dd-cid",
            r"datadome\.co",
            r"captcha\.datadome",
        ],
        "headers": [
            ("x-datadome", None),
            ("set-cookie", r"datadome="),
        ],
        "title_patterns": [],
    },
    
    WAFType.PERIMETERX: {
        "html_patterns": [
            r"px-captcha",
            r"_pxhd",
            r"perimeterx",
            r"px-block",
            r"human\.px-cdn",
            r"captcha\.px-cdn",
        ],
        "headers": [
            ("x-px-", None),
        ],
        "title_patterns": [],
    },
    
    WAFType.IMPERVA: {
        "html_patterns": [
            r"incapsula",
            r"imperva",
            r"_incap_",
            r"visid_incap",
            r"incap_ses",
        ],
        "headers": [
            ("x-iinfo", None),
            ("x-cdn", r"incapsula"),
        ],
        "title_patterns": [],
    },
    
    WAFType.AKAMAI: {
        "html_patterns": [
            r"akamai",
            r"_abck",
            r"bm_sz",
            r"ak_bmsc",
        ],
        "headers": [
            ("akamai-grn", None),
        ],
        "title_patterns": [],
    },
    
    WAFType.GENERIC_CAPTCHA: {
        "html_patterns": [
            r"recaptcha",
            r"hcaptcha",
            r"funcaptcha",
            r"arkose",
            r"g-recaptcha",
            r"h-captcha",
            r"captcha",
            r"prove you.*human",
            r"verify.*human",
            r"are you a robot",
            r"not a robot",
        ],
        "headers": [],
        "title_patterns": [
            r"captcha",
            r"verify",
        ],
    },
    
    WAFType.RATE_LIMIT: {
        "html_patterns": [
            r"rate limit",
            r"too many requests",
            r"slow down",
            r"try again later",
        ],
        "headers": [
            ("retry-after", None),
        ],
        "title_patterns": [],
    },
}


# WAF cooldown suggestions
WAF_COOLDOWNS = {
    WAFType.CLOUDFLARE: 120,
    WAFType.CLOUDFLARE_TURNSTILE: 300,
    WAFType.DATADOME: 600,
    WAFType.PERIMETERX: 600,
    WAFType.IMPERVA: 300,
    WAFType.AKAMAI: 180,
    WAFType.GENERIC_CAPTCHA: 900,
    WAFType.RATE_LIMIT: 60,
    WAFType.UNKNOWN: 120,
}


# ======================
# WAF DETECTION
# ======================

def detect_waf_type(
    response: Any = None,
    html_content: str = None,
    headers: Dict[str, str] = None,
) -> WAFDetectionResult:
    """
    Detect what type of WAF/anti-bot system is blocking the request.
    
    Args:
        response: Response object (from requests or curl_cffi)
        html_content: HTML content to analyze
        headers: Response headers
        
    Returns:
        WAFDetectionResult with detection details
    """
    # Extract content and headers from response if provided
    if response is not None:
        if html_content is None:
            html_content = getattr(response, 'text', '')
        if headers is None:
            headers = dict(getattr(response, 'headers', {}))
    
    html_lower = (html_content or "").lower()[:10000]  # First 10KB
    
    # Normalize headers
    if headers:
        headers = {k.lower(): str(v).lower() for k, v in headers.items()}
    else:
        headers = {}
    
    best_match = None
    best_confidence = 0.0
    best_indicators = []
    
    for waf_type, patterns in WAF_PATTERNS.items():
        confidence = 0.0
        indicators = []
        
        # Check HTML patterns
        for pattern in patterns.get("html_patterns", []):
            if re.search(pattern, html_lower, re.IGNORECASE):
                confidence += 0.2
                indicators.append(f"html:{pattern}")
        
        # Check headers
        for header_name, header_pattern in patterns.get("headers", []):
            header_value = headers.get(header_name, "")
            if header_value:
                if header_pattern is None or re.search(header_pattern, header_value, re.IGNORECASE):
                    confidence += 0.3
                    indicators.append(f"header:{header_name}")
        
        # Check title patterns
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html_lower, re.IGNORECASE)
        if title_match:
            title = title_match.group(1)
            for pattern in patterns.get("title_patterns", []):
                if re.search(pattern, title, re.IGNORECASE):
                    confidence += 0.25
                    indicators.append(f"title:{pattern}")
        
        # Cap confidence at 1.0
        confidence = min(confidence, 1.0)
        
        if confidence > best_confidence:
            best_confidence = confidence
            best_match = waf_type
            best_indicators = indicators
    
    # Determine if detection is significant
    if best_confidence >= 0.3:
        # Determine requirements
        requires_js = best_match in (
            WAFType.CLOUDFLARE, WAFType.CLOUDFLARE_TURNSTILE,
            WAFType.DATADOME, WAFType.PERIMETERX, WAFType.IMPERVA,
        )
        requires_human = best_match in (
            WAFType.CLOUDFLARE_TURNSTILE, WAFType.GENERIC_CAPTCHA,
            WAFType.DATADOME, WAFType.PERIMETERX,
        )
        
        return WAFDetectionResult(
            detected=True,
            waf_type=best_match,
            confidence=best_confidence,
            indicators=best_indicators,
            requires_js=requires_js,
            requires_human=requires_human,
            cooldown_hint=WAF_COOLDOWNS.get(best_match, 120),
        )
    
    return WAFDetectionResult(detected=False)


def is_challenge_page(response: Any) -> bool:
    """Quick check if response is a challenge page."""
    result = detect_waf_type(response)
    return result.detected


# ======================
# CHALLENGE BYPASS
# ======================

async def bypass_cloudflare(
    url: str,
    page: Any,
    max_wait: int = 30,
) -> Tuple[bool, Optional[str]]:
    """
    Wait for Cloudflare challenge to resolve.
    
    Cloudflare challenges typically auto-resolve after JavaScript execution.
    This waits for the challenge to complete.
    
    Args:
        url: Original URL
        page: Playwright page object
        max_wait: Maximum seconds to wait
        
    Returns:
        Tuple of (success, html_content)
    """
    start_time = time.time()
    
    while time.time() - start_time < max_wait:
        content = await page.content()
        content_lower = content.lower()
        
        # Check if challenge resolved
        challenge_indicators = [
            "checking your browser",
            "just a moment",
            "cf-browser-verification",
            "__cf_chl_",
        ]
        
        still_challenged = any(ind in content_lower for ind in challenge_indicators)
        
        if not still_challenged:
            # Challenge might be resolved
            # Verify we have actual content
            if len(content) > 5000 and "<body" in content_lower:
                logger.debug("Cloudflare challenge resolved successfully")
                return True, content
        
        # Wait a bit and check again
        await asyncio.sleep(1)
    
    logger.debug("Cloudflare challenge did not resolve in time")
    return False, None


async def bypass_datadome(
    url: str,
    page: Any,
    max_wait: int = 45,
) -> Tuple[bool, Optional[str]]:
    """
    Attempt to bypass DataDome protection.
    
    DataDome typically shows a CAPTCHA that cannot be auto-solved.
    This attempts to wait for any automatic resolution.
    
    Args:
        url: Original URL
        page: Playwright page object
        max_wait: Maximum seconds to wait
        
    Returns:
        Tuple of (success, html_content)
    """
    start_time = time.time()
    
    # DataDome often has a delay before showing CAPTCHA
    await asyncio.sleep(3)
    
    while time.time() - start_time < max_wait:
        content = await page.content()
        content_lower = content.lower()
        
        # Check for CAPTCHA (requires human)
        if "captcha" in content_lower or "geo.captcha" in content_lower:
            logger.debug("DataDome CAPTCHA detected - requires human intervention")
            return False, None
        
        # Check if protection resolved
        if "datadome" not in content_lower and len(content) > 5000:
            logger.debug("DataDome protection may have resolved")
            return True, content
        
        await asyncio.sleep(2)
    
    return False, None


async def bypass_challenge(
    url: str,
    waf_type: WAFType = None,
    site_name: str = None,
    max_retries: int = 2,
) -> BypassResult:
    """
    Attempt to bypass a WAF challenge using browser automation.
    
    This function uses stealth browser automation to navigate to the URL
    and attempt to solve any challenges automatically.
    
    Args:
        url: URL to access
        waf_type: Type of WAF detected (optional)
        site_name: Site name for fingerprint consistency
        max_retries: Maximum bypass attempts
        
    Returns:
        BypassResult with success status and content
    """
    try:
        from scrapers.browser_fallback import (
            fetch_with_browser,
            is_browser_available,
            _browser_pool,
        )
    except ImportError:
        return BypassResult(
            success=False,
            waf_type=waf_type,
            error="Browser automation not available",
        )
    
    if not is_browser_available():
        return BypassResult(
            success=False,
            waf_type=waf_type,
            error="Browser not available",
        )
    
    start_time = time.time()
    
    for attempt in range(max_retries):
        page = None
        try:
            # Get stealth browser context
            context, fingerprint = await _browser_pool.get_context(
                site_name or "waf_bypass",
                mobile=(attempt >= 1),  # Try mobile on retry
                force_new=(attempt > 0),
            )
            
            if not context:
                continue
            
            # Create new page
            page = await context.new_page()
            
            # Navigate to URL with longer timeout for challenges
            logger.debug(f"WAF bypass: Navigating to {url[:60]}... (attempt {attempt + 1})")
            
            response = await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=60000,
            )
            
            if not response:
                continue
            
            # Wait for any initial loading
            await asyncio.sleep(2)
            
            # Check what we got
            content = await page.content()
            detection = detect_waf_type(html_content=content)
            
            if not detection.detected:
                # No WAF detected, we're through!
                cookies = await context.cookies()
                
                return BypassResult(
                    success=True,
                    content=content,
                    cookies=cookies,
                    waf_type=waf_type,
                    method_used="browser",
                    response_time=time.time() - start_time,
                )
            
            # Handle specific WAF types
            actual_waf = detection.waf_type
            
            if actual_waf == WAFType.CLOUDFLARE:
                success, resolved_content = await bypass_cloudflare(url, page)
                if success:
                    cookies = await context.cookies()
                    return BypassResult(
                        success=True,
                        content=resolved_content,
                        cookies=cookies,
                        waf_type=actual_waf,
                        method_used="cloudflare_wait",
                        response_time=time.time() - start_time,
                    )
            
            elif actual_waf == WAFType.DATADOME:
                success, resolved_content = await bypass_datadome(url, page)
                if success:
                    cookies = await context.cookies()
                    return BypassResult(
                        success=True,
                        content=resolved_content,
                        cookies=cookies,
                        waf_type=actual_waf,
                        method_used="datadome_wait",
                        response_time=time.time() - start_time,
                    )
            
            else:
                # Generic wait for other WAF types
                await asyncio.sleep(5)
                content = await page.content()
                
                # Check if resolved
                detection = detect_waf_type(html_content=content)
                if not detection.detected:
                    cookies = await context.cookies()
                    return BypassResult(
                        success=True,
                        content=content,
                        cookies=cookies,
                        waf_type=actual_waf,
                        method_used="generic_wait",
                        response_time=time.time() - start_time,
                    )
            
            # Challenge not resolved, try again with delay
            await asyncio.sleep(random.uniform(3, 6))
            
        except Exception as e:
            logger.debug(f"WAF bypass attempt {attempt + 1} failed: {e}")
            continue
            
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass
    
    return BypassResult(
        success=False,
        waf_type=waf_type,
        method_used="browser",
        response_time=time.time() - start_time,
        error="All bypass attempts failed",
    )


def bypass_challenge_sync(
    url: str,
    waf_type: WAFType = None,
    site_name: str = None,
    max_retries: int = 2,
) -> BypassResult:
    """Synchronous wrapper for bypass_challenge."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return loop.run_until_complete(
        bypass_challenge(url, waf_type, site_name, max_retries)
    )


# ======================
# RESPONSE VALIDATION
# ======================

def validate_response(
    response: Any,
    site_name: str = None,
    html_content: str = None,
) -> Tuple[bool, Optional[WAFDetectionResult]]:
    """
    Validate that a response is not a WAF challenge.
    
    Args:
        response: Response object
        site_name: Site name for context
        html_content: Optional pre-extracted HTML
        
    Returns:
        Tuple of (is_valid, waf_detection if blocked)
    """
    # Check status codes
    status = getattr(response, 'status_code', 200)
    if status in (403, 429, 503):
        # Likely blocked
        detection = detect_waf_type(response)
        if detection.detected:
            return False, detection
        
        # Generic block
        if status == 429:
            return False, WAFDetectionResult(
                detected=True,
                waf_type=WAFType.RATE_LIMIT,
                confidence=1.0,
                indicators=["status:429"],
                cooldown_hint=int(response.headers.get('retry-after', 60)),
            )
        
        return False, WAFDetectionResult(
            detected=True,
            waf_type=WAFType.UNKNOWN,
            confidence=0.5,
            indicators=[f"status:{status}"],
        )
    
    # Check content for WAF
    detection = detect_waf_type(response, html_content=html_content)
    if detection.detected:
        return False, detection
    
    return True, None


__all__ = [
    "detect_waf_type",
    "is_challenge_page",
    "bypass_challenge",
    "bypass_challenge_sync",
    "validate_response",
    "WAFType",
    "WAFDetectionResult",
    "BypassResult",
]

