#!/usr/bin/env python3
"""
Test script to verify scraper stability and memory usage.
This script tests the improved threading and driver management.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import threading
import psutil
from scraper_thread import start_scraper, stop_scraper, running, stop_all_scrapers, get_scraper_status

def get_memory_usage():
    """Get current memory usage in MB."""
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / 1024 / 1024

def test_scraper_lifecycle():
    """Test starting and stopping scrapers."""
    print("🧪 Testing scraper lifecycle...")
    
    # Test starting scrapers
    sites = ["facebook", "craigslist", "ksl"]
    for site in sites:
        print(f"Starting {site} scraper...")
        result = start_scraper(site)
        assert result, f"Failed to start {site} scraper"
        
        # Check if it's running
        time.sleep(1)
        assert running(site), f"{site} scraper is not running"
        print(f"✅ {site} scraper started successfully")
    
    # Test status check
    status = get_scraper_status()
    assert all(status.values()), "Not all scrapers are running"
    print("✅ All scrapers are running")
    
    # Let them run for a few seconds
    print("⏳ Letting scrapers run for 5 seconds...")
    time.sleep(5)
    
    # Test stopping scrapers
    for site in sites:
        print(f"Stopping {site} scraper...")
        result = stop_scraper(site)
        assert result, f"Failed to stop {site} scraper"
        
        # Check if it's stopped
        time.sleep(1)
        assert not running(site), f"{site} scraper is still running"
        print(f"✅ {site} scraper stopped successfully")
    
    print("✅ Scraper lifecycle test passed")

def test_memory_usage():
    """Test memory usage during scraper operation."""
    print("🧪 Testing memory usage...")
    
    initial_memory = get_memory_usage()
    print(f"Initial memory usage: {initial_memory:.2f} MB")
    
    # Start all scrapers
    sites = ["facebook", "craigslist", "ksl"]
    for site in sites:
        start_scraper(site)
    
    # Let them run for a bit
    time.sleep(10)
    
    peak_memory = get_memory_usage()
    print(f"Peak memory usage: {peak_memory:.2f} MB")
    
    # Stop all scrapers
    stop_all_scrapers()
    time.sleep(2)
    
    final_memory = get_memory_usage()
    print(f"Final memory usage: {final_memory:.2f} MB")
    
    # Memory should not have grown excessively
    memory_growth = final_memory - initial_memory
    print(f"Memory growth: {memory_growth:.2f} MB")
    
    if memory_growth > 100:  # More than 100MB growth is concerning
        print(f"⚠️ Warning: High memory growth detected: {memory_growth:.2f} MB")
    else:
        print("✅ Memory usage is within acceptable limits")
    
    return memory_growth < 100

def test_error_handling():
    """Test error handling in scrapers."""
    print("🧪 Testing error handling...")
    
    # Start scrapers
    sites = ["facebook", "craigslist", "ksl"]
    for site in sites:
        start_scraper(site)
    
    # Let them run and handle any errors
    time.sleep(5)
    
    # Check if they're still running despite potential errors
    status = get_scraper_status()
    running_count = sum(status.values())
    print(f"Scrapers still running: {running_count}/{len(sites)}")
    
    # Stop all
    stop_all_scrapers()
    
    print("✅ Error handling test completed")

def main():
    """Run all stability tests."""
    print("🚀 Starting scraper stability tests...")
    print(f"Initial memory: {get_memory_usage():.2f} MB")
    
    try:
        # Test 1: Lifecycle
        test_scraper_lifecycle()
        
        # Test 2: Memory usage
        memory_ok = test_memory_usage()
        
        # Test 3: Error handling
        test_error_handling()
        
        print("\n🎉 All stability tests completed!")
        
        if memory_ok:
            print("✅ Memory usage is stable")
        else:
            print("⚠️ Memory usage needs attention")
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        # Cleanup on failure
        stop_all_scrapers()
        raise
    finally:
        # Final cleanup
        stop_all_scrapers()
        print(f"Final memory: {get_memory_usage():.2f} MB")

if __name__ == "__main__":
    main()
