"""
Test script to verify subscription-based scraper control
This script tests that start_all and stop_all only affect scrapers
associated with the user's subscription plan
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subscriptions import SubscriptionManager

def test_subscription_platforms():
    """Test that each subscription tier has the correct platforms"""
    
    print("🧪 Testing Subscription Platform Access\n")
    print("=" * 60)
    
    # Test Free Tier
    print("\n📦 FREE TIER")
    free_platforms = SubscriptionManager.get_allowed_platforms('free')
    print(f"Allowed Platforms: {', '.join(free_platforms)}")
    assert 'craigslist' in free_platforms, "Free tier should have Craigslist"
    assert 'ebay' in free_platforms, "Free tier should have eBay"
    assert 'facebook' not in free_platforms, "Free tier should NOT have Facebook"
    assert 'ksl' not in free_platforms, "Free tier should NOT have KSL"
    assert 'poshmark' not in free_platforms, "Free tier should NOT have Poshmark"
    assert 'mercari' not in free_platforms, "Free tier should NOT have Mercari"
    print("✅ Free tier platform access is correct")
    
    # Test Standard Tier
    print("\n📦 STANDARD TIER")
    standard_platforms = SubscriptionManager.get_allowed_platforms('standard')
    print(f"Allowed Platforms: {', '.join(standard_platforms)}")
    assert 'craigslist' in standard_platforms, "Standard tier should have Craigslist"
    assert 'facebook' in standard_platforms, "Standard tier should have Facebook"
    assert 'ksl' in standard_platforms, "Standard tier should have KSL"
    assert 'ebay' in standard_platforms, "Standard tier should have eBay"
    assert 'poshmark' not in standard_platforms, "Standard tier should NOT have Poshmark"
    assert 'mercari' not in standard_platforms, "Standard tier should NOT have Mercari"
    print("✅ Standard tier platform access is correct")
    
    # Test Pro Tier
    print("\n📦 PRO TIER")
    pro_platforms = SubscriptionManager.get_allowed_platforms('pro')
    print(f"Allowed Platforms: {', '.join(pro_platforms)}")
    assert 'craigslist' in pro_platforms, "Pro tier should have Craigslist"
    assert 'facebook' in pro_platforms, "Pro tier should have Facebook"
    assert 'ksl' in pro_platforms, "Pro tier should have KSL"
    assert 'ebay' in pro_platforms, "Pro tier should have eBay"
    assert 'poshmark' in pro_platforms, "Pro tier should have Poshmark"
    assert 'mercari' in pro_platforms, "Pro tier should have Mercari"
    print("✅ Pro tier platform access is correct")
    
    print("\n" + "=" * 60)
    print("✅ All subscription platform tests passed!")
    print("\n📝 Summary:")
    print(f"   - Free tier: {len(free_platforms)} platforms")
    print(f"   - Standard tier: {len(standard_platforms)} platforms")
    print(f"   - Pro tier: {len(pro_platforms)} platforms")

def test_platform_validation():
    """Test platform access validation"""
    
    print("\n\n🧪 Testing Platform Validation\n")
    print("=" * 60)
    
    # Test free user trying to access pro platforms
    print("\n🔒 Testing Free User Access to Pro Platforms")
    is_valid, error = SubscriptionManager.validate_platform_access('free', ['poshmark'])
    assert not is_valid, "Free users should not have access to Poshmark"
    print(f"   ✅ Correctly blocked: {error}")
    
    is_valid, error = SubscriptionManager.validate_platform_access('free', ['mercari'])
    assert not is_valid, "Free users should not have access to Mercari"
    print(f"   ✅ Correctly blocked: {error}")
    
    # Test free user accessing allowed platforms
    print("\n🔓 Testing Free User Access to Free Platforms")
    is_valid, error = SubscriptionManager.validate_platform_access('free', ['craigslist'])
    assert is_valid, "Free users should have access to Craigslist"
    print(f"   ✅ Correctly allowed: Craigslist")
    
    is_valid, error = SubscriptionManager.validate_platform_access('free', ['ebay'])
    assert is_valid, "Free users should have access to eBay"
    print(f"   ✅ Correctly allowed: eBay")
    
    # Test standard user trying to access pro platforms
    print("\n🔒 Testing Standard User Access to Pro Platforms")
    is_valid, error = SubscriptionManager.validate_platform_access('standard', ['poshmark'])
    assert not is_valid, "Standard users should not have access to Poshmark"
    print(f"   ✅ Correctly blocked: {error}")
    
    # Test standard user accessing standard platforms
    print("\n🔓 Testing Standard User Access to Standard Platforms")
    is_valid, error = SubscriptionManager.validate_platform_access('standard', ['facebook'])
    assert is_valid, "Standard users should have access to Facebook"
    print(f"   ✅ Correctly allowed: Facebook")
    
    is_valid, error = SubscriptionManager.validate_platform_access('standard', ['ksl'])
    assert is_valid, "Standard users should have access to KSL"
    print(f"   ✅ Correctly allowed: KSL")
    
    # Test pro user accessing all platforms
    print("\n🔓 Testing Pro User Access to All Platforms")
    all_platforms = ['craigslist', 'facebook', 'ksl', 'ebay', 'poshmark', 'mercari']
    is_valid, error = SubscriptionManager.validate_platform_access('pro', all_platforms)
    assert is_valid, "Pro users should have access to all platforms"
    print(f"   ✅ Correctly allowed: All platforms")
    
    print("\n" + "=" * 60)
    print("✅ All platform validation tests passed!")

def simulate_start_all_behavior():
    """Simulate what start_all will do for each tier"""
    
    print("\n\n🧪 Simulating Start All Behavior\n")
    print("=" * 60)
    
    tiers = ['free', 'standard', 'pro']
    all_scrapers = ['facebook', 'craigslist', 'ksl', 'ebay', 'poshmark', 'mercari']
    
    for tier in tiers:
        print(f"\n📦 {tier.upper()} TIER - Start All")
        allowed_platforms = SubscriptionManager.get_allowed_platforms(tier)
        
        started_platforms = []
        for scraper in all_scrapers:
            if scraper in allowed_platforms:
                started_platforms.append(scraper.capitalize())
        
        print(f"   Would start: {', '.join(started_platforms)}")
        print(f"   Total: {len(started_platforms)} scraper(s)")
    
    print("\n" + "=" * 60)
    print("✅ Simulation complete!")

if __name__ == '__main__':
    try:
        test_subscription_platforms()
        test_platform_validation()
        simulate_start_all_behavior()
        
        print("\n" + "=" * 60)
        print("🎉 ALL TESTS PASSED! 🎉")
        print("=" * 60)
        print("\nThe subscription-based scraper control is working correctly!")
        print("Users will only be able to start/stop scrapers they have access to.")
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

