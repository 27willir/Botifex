"""
Script to verify and set admin status for a user
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db_enhanced
from utils import logger

def verify_and_set_admin(username):
    """Verify user exists and set as admin"""
    try:
        # Initialize database
        db_enhanced.init_db()
        
        # Get user
        user = db_enhanced.get_user_by_username(username)
        if not user:
            print(f"[ERROR] User '{username}' not found!")
            return False
        
        print(f"[OK] User found: {username}")
        print(f"  Email: {user[1]}")
        print(f"  Current Role: {user[4]}")
        print(f"  Active: {user[5]}")
        
        # Check if already admin
        if user[4] == 'admin':
            print(f"[OK] User '{username}' is already an admin!")
            
            # Show subscription info
            subscription = db_enhanced.get_user_subscription(username)
            print(f"\nSubscription Info:")
            print(f"  Tier: {subscription.get('tier', 'free')}")
            print(f"  Status: {subscription.get('status', 'inactive')}")
            return True
        
        # Set as admin
        print(f"\n[INFO] Setting '{username}' as admin...")
        db_enhanced.update_user_role(username, 'admin')
        
        # Verify
        user = db_enhanced.get_user_by_username(username)
        if user[4] == 'admin':
            print(f"[OK] Successfully set '{username}' as admin!")
            print(f"\n[SUCCESS] Admin user is now set up!")
            print(f"   Username: {username}")
            print(f"   Role: admin")
            print(f"   All subscription features are now unlocked!")
            return True
        else:
            print(f"[ERROR] Failed to set admin role")
            return False
            
    except Exception as e:
        logger.error(f"Error verifying admin: {e}")
        print(f"[ERROR] Error: {e}")
        return False

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python verify_admin.py <username>")
        print("\nExample: python verify_admin.py RhevWilliams")
        sys.exit(1)
    
    username = sys.argv[1]
    success = verify_and_set_admin(username)
    sys.exit(0 if success else 1)

