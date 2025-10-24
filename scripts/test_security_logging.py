#!/usr/bin/env python3
"""
Test security event logging functionality
This script tests that security events are properly logged to the database
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from utils import logger
import db_enhanced

def test_security_logging():
    """Test security event logging functionality"""
    print("Testing security event logging...")
    
    try:
        # Test data
        test_ip = "192.168.1.100"
        test_path = "/test/security/endpoint"
        test_agent = "Test Security Agent"
        test_reason = "Security logging test"
        
        # Log a test security event
        print(f"Logging test security event for IP: {test_ip}")
        success = db_enhanced.log_security_event(
            ip=test_ip,
            path=test_path,
            user_agent=test_agent,
            reason=test_reason,
            timestamp=datetime.now()
        )
        
        if success:
            print("✅ Security event logged successfully")
        else:
            print("❌ Failed to log security event")
            return False
        
        # Retrieve and verify the logged event
        print("Retrieving security events...")
        events = db_enhanced.get_security_events(limit=10, hours=1)
        
        if events:
            print(f"✅ Retrieved {len(events)} security events")
            
            # Find our test event
            test_event = None
            for event in events:
                if event['ip_address'] == test_ip and event['path'] == test_path:
                    test_event = event
                    break
            
            if test_event:
                print("✅ Test security event found in database")
                print(f"   IP: {test_event['ip_address']}")
                print(f"   Path: {test_event['path']}")
                print(f"   Reason: {test_event['reason']}")
                print(f"   Timestamp: {test_event['timestamp']}")
            else:
                print("❌ Test security event not found in database")
                return False
        else:
            print("❌ No security events retrieved")
            return False
        
        # Clean up test data
        print("Cleaning up test data...")
        # Note: We'll leave the test data for now to verify it's working
        
        return True
        
    except Exception as e:
        logger.error(f"Security logging test failed: {e}")
        print(f"❌ Test failed with error: {e}")
        return False

def test_security_middleware():
    """Test security middleware functionality"""
    print("\nTesting security middleware...")
    
    try:
        from security_middleware import security_middleware
        
        # Test suspicious request detection
        test_paths = [
            "/.env",
            "/wp-admin/setup-config.php",
            "/phpinfo.php",
            "/config.js"
        ]
        
        for path in test_paths:
            is_suspicious = security_middleware.is_suspicious_request(path)
            print(f"   {path}: {'🚨 Suspicious' if is_suspicious else '✅ Clean'}")
        
        # Test user agent detection
        test_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Go-http-client/1.1",
            "python-requests/2.28.1",
            "curl/7.68.0"
        ]
        
        print("\nUser Agent Tests:")
        for agent in test_agents:
            is_malicious = security_middleware.is_malicious_user_agent(agent)
            print(f"   {agent[:50]}...: {'🚨 Malicious' if is_malicious else '✅ Clean'}")
        
        return True
        
    except Exception as e:
        logger.error(f"Security middleware test failed: {e}")
        print(f"❌ Security middleware test failed: {e}")
        return False

if __name__ == "__main__":
    print("🔒 Security System Test Suite")
    print("=" * 50)
    
    # Test security logging
    logging_success = test_security_logging()
    
    # Test security middleware
    middleware_success = test_security_middleware()
    
    print("\n" + "=" * 50)
    print("📊 Test Results:")
    print(f"   Security Logging: {'✅ PASS' if logging_success else '❌ FAIL'}")
    print(f"   Security Middleware: {'✅ PASS' if middleware_success else '❌ FAIL'}")
    
    if logging_success and middleware_success:
        print("\n🎉 All security tests passed!")
        sys.exit(0)
    else:
        print("\n❌ Some security tests failed!")
        sys.exit(1)
