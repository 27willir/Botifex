# scheduler.py
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time, random, traceback, threading
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from db import get_settings
from scrapers.facebook import check_facebook
from scrapers.craigslist import check_craigslist
from scrapers.ksl import check_ksl
from price_alert_worker import check_price_alerts

def make_driver():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--window-size=1200,800")
    driver = webdriver.Chrome(options=opts)
    return driver

def run_scrapers(driver, settings):
    # Facebook requires driver, Craigslist and KSL don't
    try:
        result = check_facebook(driver)
        print(f"✅ check_facebook finished:", result)
    except Exception as e:
        print(f"❌ Error in check_facebook: {e}")
        traceback.print_exc()
    
    time.sleep(random.uniform(2, 5))
    
    try:
        result = check_craigslist()
        print(f"✅ check_craigslist finished:", result)
    except Exception as e:
        print(f"❌ Error in check_craigslist: {e}")
        traceback.print_exc()
    
    time.sleep(random.uniform(2, 5))
    
    try:
        result = check_ksl()
        print(f"✅ check_ksl finished:", result)
    except Exception as e:
        print(f"❌ Error in check_ksl: {e}")
        traceback.print_exc()

def price_alert_checker():
    """Background thread that checks price alerts every 5 minutes"""
    print("🚨 Price Alert Checker Started (runs every 5 minutes)")
    while True:
        try:
            check_price_alerts()
        except Exception as e:
            print(f"❌ Error in price alert checker: {e}")
            traceback.print_exc()
        
        # Wait 5 minutes before next check
        time.sleep(300)

def start_scheduler():
    # Start price alert checker in background thread
    alert_thread = threading.Thread(target=price_alert_checker, daemon=True)
    alert_thread.start()
    print("✅ Price alert checker thread started")
    
    driver = None
    while True:
        try:
            settings = get_settings()
            interval = int(settings.get("interval") or 60)

            if driver is None:
                driver = make_driver()

            run_scrapers(driver, settings)

            # Randomized wait until next run
            wait_time = random.uniform(interval * 0.9, interval * 1.1)
            print(f"⏳ Waiting {wait_time:.1f}s until next run...")
            time.sleep(wait_time)

        except Exception as e:
            print("Scheduler error:", e)
            traceback.print_exc()
            try:
                if driver:
                    driver.quit()
            except Exception as cleanup_error:
                print(f"Error cleaning up driver: {cleanup_error}")
            driver = None
            time.sleep(10)
