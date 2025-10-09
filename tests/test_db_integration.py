#!/usr/bin/env python3
"""
Test script to verify database integration is working correctly.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import init_db, get_settings, update_setting, save_listing, get_listings, create_user_db, get_user_by_username
from werkzeug.security import generate_password_hash

def test_database_integration():
    """Test all database functions"""
    print("🧪 Testing Database Integration...")
    
    # Initialize database
    print("1. Initializing database...")
    init_db()
    print("✅ Database initialized")
    
    # Test settings
    print("\n2. Testing settings...")
    update_setting("test_key", "test_value")
    settings = get_settings()
    assert settings.get("test_key") == "test_value", "Settings not working"
    print("✅ Settings working")
    
    # Test user management
    print("\n3. Testing user management...")
    test_username = "test_user"
    test_email = "test@example.com"
    test_password = "test_password"
    
    # Create user
    success = create_user_db(test_username, test_email, generate_password_hash(test_password))
    assert success, "Failed to create user"
    print("✅ User creation working")
    
    # Get user
    user = get_user_by_username(test_username)
    assert user is not None, "Failed to retrieve user"
    assert user[0] == test_username, "Username mismatch"
    print("✅ User retrieval working")
    
    # Test user-specific settings
    print("\n4. Testing user-specific settings...")
    update_setting("user_key", "user_value", test_username)
    user_settings = get_settings(test_username)
    assert user_settings.get("user_key") == "user_value", "User settings not working"
    print("✅ User-specific settings working")
    
    # Test listings
    print("\n5. Testing listings...")
    save_listing("Test Listing", 5000, "https://example.com/test", "https://example.com/image.jpg", "test")
    listings = get_listings(10)
    assert len(listings) > 0, "No listings found"
    assert listings[0][0] == "Test Listing", "Listing title mismatch"
    print("✅ Listings working")
    
    print("\n🎉 All database integration tests passed!")
    return True

if __name__ == "__main__":
    try:
        test_database_integration()
    except Exception as e:
        print(f"❌ Test failed: {e}")
        sys.exit(1)

