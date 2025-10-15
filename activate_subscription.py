"""
Quick script to manually activate a subscription for testing
Run this after completing Stripe checkout to simulate webhook activation
"""

import sqlite3
from datetime import datetime, timedelta

def activate_subscription(username, tier='pro'):
    """Manually activate a subscription for a user"""
    conn = sqlite3.connect('superbot.db')
    cursor = conn.cursor()
    
    # Check if subscription exists
    cursor.execute('SELECT * FROM subscriptions WHERE username = ?', (username,))
    existing = cursor.fetchone()
    
    if existing:
        # Update existing subscription
        cursor.execute('''
            UPDATE subscriptions 
            SET tier = ?, status = 'active', updated_at = ?
            WHERE username = ?
        ''', (tier, datetime.now(), username))
        print(f"✅ Updated subscription for {username} to {tier} tier (active)")
    else:
        # Create new subscription
        cursor.execute('''
            INSERT INTO subscriptions (username, tier, status, created_at, updated_at)
            VALUES (?, ?, 'active', ?, ?)
        ''', (username, tier, datetime.now(), datetime.now()))
        print(f"✅ Created new subscription for {username} - {tier} tier (active)")
    
    # Log the event
    cursor.execute('''
        INSERT INTO subscription_history (username, tier, action, details, created_at)
        VALUES (?, ?, 'manual_activation', 'Manually activated via script', ?)
    ''', (username, tier, datetime.now()))
    
    conn.commit()
    conn.close()
    print(f"🎉 {username} now has access to {tier} features!")

if __name__ == '__main__':
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python activate_subscription.py <username> [tier]")
        print("Example: python activate_subscription.py Bob909 pro")
        sys.exit(1)
    
    username = sys.argv[1]
    tier = sys.argv[2] if len(sys.argv) > 2 else 'pro'
    
    activate_subscription(username, tier)

