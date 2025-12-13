#!/usr/bin/env python3
"""Setup script for the advanced scraping infrastructure.

This script:
1. Checks if required dependencies are installed
2. Installs Playwright browser if needed
3. Tests TLS fingerprint impersonation
4. Validates proxy configuration
5. Reports capabilities

Run this after pip install -r requirements.txt
"""

import sys
import os
import subprocess

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def print_header(text):
    print(f"\n{'='*60}")
    print(f"  {text}")
    print('='*60)


def print_status(name, available, details=None):
    status = "✓" if available else "✗"
    color = "\033[92m" if available else "\033[91m"
    reset = "\033[0m"
    print(f"  {color}{status}{reset} {name}")
    if details:
        print(f"      {details}")


def check_curl_cffi():
    """Check if curl_cffi is installed and working."""
    try:
        from curl_cffi import requests
        # Try to create a session with impersonation
        session = requests.Session(impersonate="chrome131")
        return True, "TLS fingerprint impersonation ready"
    except ImportError:
        return False, "Not installed. Run: pip install curl_cffi"
    except Exception as e:
        return False, f"Error: {e}"


def check_playwright():
    """Check if Playwright is installed and has browsers."""
    try:
        from playwright.sync_api import sync_playwright
        
        # Check if chromium is installed
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
                browser.close()
                return True, "Chromium browser ready"
            except Exception as e:
                if "Executable doesn't exist" in str(e):
                    return False, "Browser not installed. Run: playwright install chromium"
                return False, f"Error: {e}"
    except ImportError:
        return False, "Not installed. Run: pip install playwright"
    except Exception as e:
        return False, f"Error: {e}"


def check_proxies():
    """Check proxy configuration."""
    proxies = []
    
    # Check environment variables
    scraper_proxies = os.environ.get("SCRAPER_PROXIES", "")
    if scraper_proxies:
        proxies.extend([p.strip() for p in scraper_proxies.split(",") if p.strip()])
    
    brightdata = os.environ.get("BRIGHTDATA_PROXY", "")
    if brightdata:
        proxies.append("BrightData")
    
    smartproxy = os.environ.get("SMARTPROXY_PROXY", "")
    if smartproxy:
        proxies.append("SmartProxy")
    
    # Check .proxies.txt file
    proxy_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".proxies.txt")
    if os.path.exists(proxy_file):
        try:
            with open(proxy_file) as f:
                file_proxies = [l.strip() for l in f if l.strip() and not l.startswith("#")]
                proxies.extend(file_proxies)
        except Exception:
            pass
    
    if proxies:
        return True, f"{len(proxies)} proxy(ies) configured"
    return False, "No proxies configured. Set SCRAPER_PROXIES env or create .proxies.txt"


def check_infrastructure():
    """Check the full scraping infrastructure."""
    try:
        from scrapers import get_capabilities, initialize
        
        # Initialize and get capabilities
        caps = initialize()
        return caps
    except ImportError as e:
        print(f"  Error importing scrapers: {e}")
        return None
    except Exception as e:
        print(f"  Error checking infrastructure: {e}")
        return None


def install_playwright_browsers():
    """Install Playwright Chromium browser."""
    print("\nInstalling Playwright Chromium browser...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            print("  ✓ Chromium installed successfully")
            return True
        else:
            print(f"  ✗ Installation failed: {result.stderr}")
            return False
    except Exception as e:
        print(f"  ✗ Installation error: {e}")
        return False


def test_request():
    """Test a simple request with TLS fingerprint impersonation."""
    print("\nTesting TLS fingerprint impersonation...")
    try:
        from scrapers.stealth_client import stealth_get, is_curl_cffi_available
        
        if not is_curl_cffi_available():
            print("  ✗ curl_cffi not available, skipping test")
            return False
        
        # Test against a safe endpoint
        response = stealth_get(
            "https://httpbin.org/headers",
            "test",
            timeout=10
        )
        
        if response and response.status_code == 200:
            import json
            data = json.loads(response.text)
            ua = data.get("headers", {}).get("User-Agent", "Unknown")
            print(f"  ✓ Request successful")
            print(f"      User-Agent: {ua[:60]}...")
            return True
        else:
            print(f"  ✗ Request failed")
            return False
            
    except Exception as e:
        print(f"  ✗ Test error: {e}")
        return False


def main():
    print_header("Scraper Infrastructure Setup")
    
    # Check dependencies
    print("\n[1/5] Checking Dependencies...")
    
    curl_ok, curl_msg = check_curl_cffi()
    print_status("curl_cffi (TLS Fingerprinting)", curl_ok, curl_msg)
    
    playwright_ok, playwright_msg = check_playwright()
    print_status("Playwright (Browser Automation)", playwright_ok, playwright_msg)
    
    proxy_ok, proxy_msg = check_proxies()
    print_status("Proxy Configuration", proxy_ok, proxy_msg)
    
    # Offer to install Playwright browsers if missing
    if not playwright_ok and "not installed" in playwright_msg.lower():
        print("\n[2/5] Installing Playwright Browser...")
        response = input("  Install Chromium browser now? [Y/n]: ").strip().lower()
        if response in ("", "y", "yes"):
            install_playwright_browsers()
            playwright_ok, playwright_msg = check_playwright()
    else:
        print("\n[2/5] Playwright browser already installed")
    
    # Test infrastructure
    print("\n[3/5] Checking Scraper Infrastructure...")
    caps = check_infrastructure()
    
    # Test request
    print("\n[4/5] Testing Request...")
    if curl_ok:
        test_request()
    else:
        print("  Skipping (curl_cffi not available)")
    
    # Summary
    print_header("Setup Summary")
    
    all_ok = curl_ok and playwright_ok
    
    if caps:
        print("\nCapabilities:")
        print_status("TLS Fingerprint Impersonation", caps.get("curl_cffi_tls_impersonation", False))
        print_status("Browser Automation", caps.get("browser_automation", False))
        print_status("Smart Request Router", caps.get("smart_router", False))
        print_status("Proxy Manager", caps.get("proxy_manager", False))
        print_status("Proxies Configured", caps.get("proxies_configured", False))
        print_status("WAF Bypass", caps.get("waf_bypass", False))
    
    if all_ok:
        print("\n\033[92m✓ Scraper infrastructure is ready!\033[0m")
        print("\nNext steps:")
        print("  1. (Optional) Configure proxies for better success rates")
        print("  2. Run your scrapers - they will auto-use the best strategies")
    else:
        print("\n\033[93m⚠ Some components are missing\033[0m")
        print("\nTo fix:")
        if not curl_ok:
            print("  pip install curl_cffi")
        if not playwright_ok:
            print("  pip install playwright && playwright install chromium")
        if not proxy_ok:
            print("  Set SCRAPER_PROXIES environment variable or create .proxies.txt")
    
    print()
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())

