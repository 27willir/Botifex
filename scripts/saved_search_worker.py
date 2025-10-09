#!/usr/bin/env python3
"""
Saved Search Worker
Runs saved searches periodically and notifies users of new results
"""

import sys
import time
from pathlib import Path
from datetime import datetime, timedelta

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import db_enhanced
from notifications import notify_new_listing
from websocket_manager import notify_saved_search_results
from utils import logger


def run_saved_searches():
    """Run all saved searches and check for new results"""
    try:
        # Get all users with saved searches
        all_users = db_enhanced.get_all_users()
        
        total_searches_run = 0
        total_results_found = 0
        
        for user in all_users:
            username = user[0]
            
            # Get user's saved searches
            searches = db_enhanced.get_saved_searches(username)
            
            for search in searches:
                try:
                    search_id = search['id']
                    search_name = search['name']
                    notify_new = search['notify_new']
                    last_run = search['last_run']
                    
                    # Rate limiting: don't run same search more than once per hour
                    if last_run:
                        last_run_dt = datetime.fromisoformat(last_run)
                        if (datetime.now() - last_run_dt).seconds < 3600:
                            continue
                    
                    # Get search parameters
                    keywords = search['keywords'].split(',') if search['keywords'] else []
                    min_price = search['min_price']
                    max_price = search['max_price']
                    sources = search['sources'].split(',') if search['sources'] else []
                    
                    # Get recent listings
                    recent_listings = db_enhanced.get_listings(limit=50)
                    
                    # Filter listings based on search criteria
                    matching_listings = []
                    
                    for listing in recent_listings:
                        title = listing.get('title', '').lower()
                        price = listing.get('price')
                        source = listing.get('source')
                        
                        # Check keywords
                        if keywords and not any(kw.strip().lower() in title for kw in keywords):
                            continue
                        
                        # Check price range
                        if min_price and price and price < min_price:
                            continue
                        if max_price and price and price > max_price:
                            continue
                        
                        # Check sources
                        if sources and source not in sources:
                            continue
                        
                        # Check if listing is new (created after last run)
                        if last_run:
                            listing_date = datetime.fromisoformat(listing.get('created_at'))
                            if listing_date <= last_run_dt:
                                continue
                        
                        matching_listings.append(listing)
                    
                    total_searches_run += 1
                    
                    if matching_listings:
                        total_results_found += len(matching_listings)
                        
                        logger.info(f"💾 Saved search '{search_name}' for {username}: {len(matching_listings)} new results")
                        
                        # Send notification if enabled
                        if notify_new:
                            # Get user data
                            user_data = db_enhanced.get_user_by_username(username)
                            if user_data:
                                email = user_data[1]
                                notifications = db_enhanced.get_notification_preferences(username)
                                
                                # Send notification for first matching listing
                                first_listing = matching_listings[0]
                                notify_new_listing(
                                    user_email=email,
                                    user_phone=notifications.get('phone_number'),
                                    email_enabled=notifications.get('email_notifications', False),
                                    sms_enabled=notifications.get('sms_notifications', False),
                                    listing_title=first_listing.get('title'),
                                    listing_price=first_listing.get('price'),
                                    listing_url=first_listing.get('link'),
                                    listing_source=first_listing.get('source')
                                )
                            
                            # Send WebSocket notification
                            try:
                                notify_saved_search_results(username, search_name, len(matching_listings))
                            except:
                                pass  # WebSocket might not be available
                    
                    # Update last run timestamp
                    db_enhanced.update_saved_search_last_run(search_id)
                
                except Exception as e:
                    logger.error(f"Error running saved search {search_id}: {e}")
                    continue
        
        logger.info(f"✅ Saved search check completed: {total_searches_run} searches, {total_results_found} results")
    
    except Exception as e:
        logger.error(f"Error in saved search worker: {e}")


def main():
    """Main worker loop"""
    print("💾 Saved Search Worker Started")
    print("=" * 80)
    print("📅 Check Interval: Every 15 minutes")
    print("🔄 Status: Running...")
    print("   Press Ctrl+C to stop\n")
    
    try:
        while True:
            run_saved_searches()
            
            # Wait 15 minutes before next check
            time.sleep(900)
    
    except KeyboardInterrupt:
        print("\n\n🛑 Saved search worker stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error in saved search worker: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

