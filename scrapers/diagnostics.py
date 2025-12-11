"""Scraper diagnostics utility for debugging blocking and parsing issues.

Run this to quickly diagnose why scrapers are failing:

    python -m scrapers.diagnostics [site_name]

This will test each scraper and report:
- Whether requests are being blocked
- Whether selectors are finding content
- Response details for debugging
"""

import sys
import time
import random
import re
from typing import Optional, Dict, Any, List

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError as e:
    print(f"Error: Missing dependency: {e}")
    sys.exit(1)

# Import scraper utilities
from scrapers import anti_blocking
from scrapers.common import (
    get_session, validate_response_structure, detect_block_type,
    EXPECTED_SELECTORS, BLOCK_INDICATORS
)


def test_site(site_name: str, test_url: str) -> Dict[str, Any]:
    """Test a single site and return diagnostic information."""
    results = {
        "site": site_name,
        "url": test_url,
        "success": False,
        "status_code": None,
        "response_size": 0,
        "response_time": 0,
        "is_blocked": False,
        "block_type": None,
        "selectors_found": [],
        "selectors_missing": [],
        "sample_classes": [],
        "errors": [],
    }
    
    try:
        # Get a fresh session
        session = get_session(site_name, force_new=True)
        
        # Build headers
        headers = anti_blocking.build_headers(site_name, referer=test_url)
        
        # Make request
        print(f"\n{'='*60}")
        print(f"Testing {site_name.upper()}: {test_url[:60]}...")
        print(f"{'='*60}")
        
        # Wait before request
        wait_time = anti_blocking.pre_request_wait(site_name)
        if wait_time > 0:
            print(f"  Waiting {wait_time:.1f}s before request...")
            time.sleep(wait_time)
        
        start_time = time.time()
        response = session.get(test_url, headers=headers, timeout=30)
        results["response_time"] = time.time() - start_time
        
        results["status_code"] = response.status_code
        results["response_size"] = len(response.content)
        
        print(f"  Status: {response.status_code}")
        print(f"  Size: {results['response_size']:,} bytes")
        print(f"  Time: {results['response_time']:.2f}s")
        
        # Check for blocks
        is_valid, reason = validate_response_structure(response, site_name)
        if not is_valid:
            results["is_blocked"] = True
            results["block_type"] = reason
            print(f"  ❌ BLOCKED: {reason}")
        else:
            print(f"  ✓ Response validated: {reason}")
        
        # More detailed block check
        block_info = detect_block_type(response, site_name)
        if block_info:
            results["is_blocked"] = True
            results["block_type"] = block_info.get("type", "unknown")
            print(f"  ❌ Block detected: {block_info}")
        
        # Parse HTML and check selectors
        text = response.text
        soup = BeautifulSoup(text, 'html.parser')
        
        # Check expected selectors
        expected = EXPECTED_SELECTORS.get(site_name, [])
        for selector in expected:
            try:
                found = soup.select(selector)
                if found:
                    results["selectors_found"].append(f"{selector} ({len(found)} found)")
                    print(f"  ✓ Selector '{selector}': {len(found)} matches")
                else:
                    results["selectors_missing"].append(selector)
                    print(f"  ✗ Selector '{selector}': NOT FOUND")
            except Exception as e:
                results["errors"].append(f"Selector error {selector}: {e}")
        
        # Extract sample class names
        classes_found = set()
        for match in re.findall(r'class=["\']([^"\']+)["\']', text[:10000]):
            classes_found.update(match.split())
        results["sample_classes"] = sorted(classes_found)[:30]
        print(f"  Sample classes: {results['sample_classes'][:10]}")
        
        # Check for common content indicators
        content_indicators = {
            "Has prices ($)": "$" in text,
            "Has links": "href" in text,
            "Has images": "<img" in text.lower(),
            "Has JSON-LD": "application/ld+json" in text,
        }
        print(f"  Content indicators:")
        for indicator, present in content_indicators.items():
            status = "✓" if present else "✗"
            print(f"    {status} {indicator}")
        
        # Show first 500 chars of response for debugging
        print(f"\n  First 500 chars of response:")
        print(f"  {'-'*40}")
        sample = text[:500].replace('\n', ' ').replace('\r', ' ')
        print(f"  {sample}")
        
        if not results["is_blocked"] and (results["selectors_found"] or results["response_size"] > 2000):
            results["success"] = True
            print(f"\n  ✓ SITE APPEARS ACCESSIBLE")
        else:
            print(f"\n  ❌ SITE MAY BE BLOCKED OR SELECTORS NEED UPDATE")
        
    except requests.exceptions.Timeout:
        results["errors"].append("Request timed out")
        print(f"  ❌ ERROR: Request timed out")
    except requests.exceptions.RequestException as e:
        results["errors"].append(str(e))
        print(f"  ❌ ERROR: {e}")
    except Exception as e:
        results["errors"].append(str(e))
        print(f"  ❌ UNEXPECTED ERROR: {e}")
    
    return results


# Test URLs for each site
TEST_URLS = {
    "ebay": "https://www.ebay.com/sch/i.html?_nkw=test&_sop=10&LH_ItemCondition=3000",
    "craigslist": "https://boise.craigslist.org/search/sss?query=car",
    "mercari": "https://www.mercari.com/search/?keyword=test",
    "ksl": "https://classifieds.ksl.com/search/?keyword=car",
    "poshmark": "https://poshmark.com/search?query=shoes",
    "facebook": "https://www.facebook.com/marketplace/category/vehicles",
}


def run_diagnostics(sites: Optional[List[str]] = None):
    """Run diagnostics on specified sites or all sites."""
    if sites is None:
        sites = list(TEST_URLS.keys())
    
    print("\n" + "="*60)
    print("SCRAPER DIAGNOSTICS")
    print("="*60)
    print(f"Testing {len(sites)} site(s): {', '.join(sites)}")
    
    all_results = []
    
    for site in sites:
        if site not in TEST_URLS:
            print(f"\n⚠️  Unknown site: {site}")
            continue
        
        result = test_site(site, TEST_URLS[site])
        all_results.append(result)
        
        # Small delay between tests
        time.sleep(random.uniform(2.0, 4.0))
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    for result in all_results:
        status = "✓ OK" if result["success"] else "❌ FAIL"
        block_info = f" (blocked: {result['block_type']})" if result["is_blocked"] else ""
        print(f"  {result['site'].upper():12} {status}{block_info}")
    
    successful = sum(1 for r in all_results if r["success"])
    print(f"\nResult: {successful}/{len(all_results)} sites accessible")
    
    if successful < len(all_results):
        print("\nRecommendations:")
        print("  1. Wait 5-10 minutes and try again (rate limiting)")
        print("  2. Check if a VPN or proxy is needed")
        print("  3. Some sites may require browser-based scraping")
        print("  4. Check anti_blocking.py for updated fingerprints")
    
    return all_results


if __name__ == "__main__":
    sites = sys.argv[1:] if len(sys.argv) > 1 else None
    run_diagnostics(sites)

