#!/usr/bin/env python3
"""
Price Alert Worker
Monitors new listings and triggers price alerts
"""

import sys
import time
from pathlib import Path
from datetime import datetime, timedelta

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import db_enhanced
from notifications import notify_new_listing
from websocket_manager import notify_price_alert_triggered
from utils import logger


def check_price_alerts():
    """Check all active price alerts against recent listings"""
    try:
        # Get all active price alerts
        alerts = db_enhanced.get_active_price_alerts()
        
        if not alerts:
            logger.debug("No active price alerts to check")
            return
        
        logger.info(f"Checking {len(alerts)} active price alerts...")
        
        # Get recent listings (last hour)
        recent_listings = db_enhanced.get_listings(limit=100)
        
        for alert in alerts:
            try:
                alert_id = alert['id']
                username = alert['username']
                keywords = alert['keywords'].split(',') if alert['keywords'] else []
                threshold_price = alert['threshold_price']
                alert_type = alert['alert_type']
                last_triggered = alert['last_triggered']
                
                # Rate limiting: don't trigger same alert more than once per hour
                if last_triggered:
                    last_triggered_dt = datetime.fromisoformat(last_triggered)
                    if (datetime.now() - last_triggered_dt).seconds < 3600:
                        continue
                
                # Check each recent listing
                for listing in recent_listings:
                    title = listing.get('title', '').lower()
                    price = listing.get('price')
                    
                    # Check if listing matches keywords
                    if not any(kw.strip().lower() in title for kw in keywords):
                        continue
                    
                    # Check price threshold
                    triggered = False
                    if alert_type == 'under' and price and price < threshold_price:
                        triggered = True
                    elif alert_type == 'over' and price and price > threshold_price:
                        triggered = True
                    
                    if triggered:
                        logger.info(f"🚨 Price alert triggered for {username}: {listing.get('title')} @ ${price}")
                        
                        # Update last triggered
                        db_enhanced.update_price_alert_triggered(alert_id)
                        
                        # Get user notification preferences
                        user = db_enhanced.get_user_by_username(username)
                        if user:
                            email = user[1]
                            notifications = db_enhanced.get_notification_preferences(username)
                            
                            # Send notification
                            notify_new_listing(
                                user_email=email,
                                user_phone=notifications.get('phone_number'),
                                email_enabled=notifications.get('email_notifications', False),
                                sms_enabled=notifications.get('sms_notifications', False),
                                listing_title=listing.get('title'),
                                listing_price=price,
                                listing_url=listing.get('link'),
                                listing_source=listing.get('source')
                            )
                        
                        # Send WebSocket notification
                        try:
                            notify_price_alert_triggered(username, {
                                'keywords': ', '.join(keywords),
                                'threshold_price': threshold_price,
                                'listing': listing
                            })
                        except:
                            pass  # WebSocket might not be available
                        
                        # Only trigger once per alert check
                        break
            
            except Exception as e:
                logger.error(f"Error checking alert {alert_id}: {e}")
                continue
        
        logger.info("✅ Price alert check completed")
    
    except Exception as e:
        logger.error(f"Error in price alert worker: {e}")


def main():
    """Main worker loop"""
    print("🚨 Price Alert Worker Started")
    print("=" * 80)
    print("📅 Check Interval: Every 5 minutes")
    print("🔄 Status: Running...")
    print("   Press Ctrl+C to stop\n")
    
    try:
        while True:
            check_price_alerts()
            
            # Wait 5 minutes before next check
            time.sleep(300)
    
    except KeyboardInterrupt:
        print("\n\n🛑 Price alert worker stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error in price alert worker: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

