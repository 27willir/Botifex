#!/usr/bin/env python3
"""
Create Admin User Script
Creates a new admin user or promotes an existing user to admin
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db_enhanced
from security import SecurityConfig
from utils import logger


def create_admin(username, email, password):
    """Create a new admin user"""
    try:
        # Initialize database if needed
        db_enhanced.init_db()
        
        # Validate inputs
        is_valid_username, username_error = SecurityConfig.validate_username(username)
        if not is_valid_username:
            print(f"[ERROR] {username_error}")
            return False
        
        is_valid_email, email_error = SecurityConfig.validate_email(email)
        if not is_valid_email:
            print(f"[ERROR] {email_error}")
            return False
        
        is_valid_password, password_error = SecurityConfig.validate_password(password)
        if not is_valid_password:
            print(f"[ERROR] {password_error}")
            return False
        
        # Hash password
        hashed = SecurityConfig.hash_password(password)
        
        # Create user with admin role
        success = db_enhanced.create_user_db(username, email, hashed, role='admin')
        
        if success:
            print(f"[OK] Admin user '{username}' created successfully!")
            print(f"   Email: {email}")
            print(f"   Role: admin")
            logger.info(f"Admin user created: {username}")
            return True
        else:
            print(f"[ERROR] Failed to create admin user (username or email may already exist)")
            return False
    
    except Exception as e:
        print(f"[ERROR] Error creating admin user: {e}")
        logger.error(f"Error creating admin user: {e}")
        return False


def promote_to_admin(username):
    """Promote an existing user to admin"""
    try:
        # Check if user exists
        user = db_enhanced.get_user_by_username(username)
        if not user:
            print(f"[ERROR] User '{username}' not found")
            return False
        
        # Update role to admin
        db_enhanced.update_user_role(username, 'admin')
        print(f"[OK] User '{username}' promoted to admin!")
        logger.info(f"User promoted to admin: {username}")
        return True
    
    except Exception as e:
        print(f"[ERROR] Error promoting user: {e}")
        logger.error(f"Error promoting user: {e}")
        return False


def main():
    """Main function"""
    print("=" * 60)
    print("Admin User Management")
    print("=" * 60)
    print()
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  Create new admin:")
        print("    python create_admin.py <username> <email> <password>")
        print()
        print("  Promote existing user:")
        print("    python create_admin.py --promote <username>")
        print()
        print("Examples:")
        print("  python create_admin.py admin admin@example.com SecurePass123!")
        print("  python create_admin.py --promote john_doe")
        sys.exit(1)
    
    if sys.argv[1] == "--promote":
        # Promote existing user
        if len(sys.argv) != 3:
            print("[ERROR] Error: --promote requires username")
            print("Usage: python create_admin.py --promote <username>")
            sys.exit(1)
        
        username = sys.argv[2]
        promote_to_admin(username)
    
    else:
        # Create new admin user
        if len(sys.argv) != 4:
            print("[ERROR] Error: Creating new admin requires username, email, and password")
            print("Usage: python create_admin.py <username> <email> <password>")
            sys.exit(1)
        
        username = sys.argv[1]
        email = sys.argv[2]
        password = sys.argv[3]
        
        create_admin(username, email, password)


if __name__ == "__main__":
    main()

