#!/usr/bin/env python3
"""
Rate Limit Reset Script
This script allows you to reset rate limits for troubleshooting purposes.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db_enhanced import reset_rate_limit, get_pool
from utils import logger

def reset_all_rate_limits():
    """Reset all rate limits in the database"""
    try:
        with get_pool().get_connection() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM rate_limits")
            conn.commit()
            logger.info("All rate limits have been reset")
            return True
    except Exception as e:
        logger.error(f"Error resetting all rate limits: {e}")
        return False

def reset_user_rate_limits(username):
    """Reset rate limits for a specific user"""
    try:
        result = reset_rate_limit(username)
        if result:
            logger.info(f"Rate limits reset for user: {username}")
            return True
        else:
            logger.error(f"Failed to reset rate limits for user: {username}")
            return False
    except Exception as e:
        logger.error(f"Error resetting rate limits for {username}: {e}")
        return False

def show_rate_limit_status():
    """Show current rate limit status"""
    try:
        with get_pool().get_connection() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT username, endpoint, request_count, window_start 
                FROM rate_limits 
                ORDER BY window_start DESC
            """)
            results = c.fetchall()
            
            if not results:
                print("No active rate limits found.")
                return
            
            print("Current Rate Limits:")
            print("-" * 80)
            print(f"{'Username':<20} {'Endpoint':<15} {'Count':<8} {'Window Start':<20}")
            print("-" * 80)
            
            for username, endpoint, count, window_start in results:
                print(f"{username:<20} {endpoint:<15} {count:<8} {window_start:<20}")
                
    except Exception as e:
        logger.error(f"Error showing rate limit status: {e}")

def main():
    """Main function with interactive menu"""
    print("Rate Limit Management Tool")
    print("=" * 40)
    
    while True:
        print("\nOptions:")
        print("1. Show current rate limits")
        print("2. Reset rate limits for specific user")
        print("3. Reset ALL rate limits")
        print("4. Exit")
        
        choice = input("\nEnter your choice (1-4): ").strip()
        
        if choice == "1":
            show_rate_limit_status()
            
        elif choice == "2":
            username = input("Enter username to reset: ").strip()
            if username:
                reset_user_rate_limits(username)
            else:
                print("Username cannot be empty")
                
        elif choice == "3":
            confirm = input("Are you sure you want to reset ALL rate limits? (yes/no): ").strip().lower()
            if confirm == "yes":
                reset_all_rate_limits()
            else:
                print("Operation cancelled")
                
        elif choice == "4":
            print("Goodbye!")
            break
            
        else:
            print("Invalid choice. Please enter 1-4.")

if __name__ == "__main__":
    main()
