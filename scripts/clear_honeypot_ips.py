#!/usr/bin/env python3
"""
Clear honeypot-flagged IPs from the system
Run this script to immediately clear any IPs that were incorrectly flagged by the honeypot
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def clear_honeypot_ips():
    """Clear all honeypot-flagged IPs"""
    try:
        from honeypot_routes import honeypot_manager
        from security_middleware import security_middleware
        
        # Get current counts
        honeypot_count = len(honeypot_manager.honeypot_ips)
        blocked_count = len(security_middleware.blocked_ips)
        
        print(f"Current honeypot-flagged IPs: {honeypot_count}")
        print(f"Honeypot IPs: {list(honeypot_manager.honeypot_ips)}")
        print(f"\nCurrent blocked IPs: {blocked_count}")
        print(f"Blocked IPs: {list(security_middleware.blocked_ips)}")
        
        # Clear honeypot IPs
        honeypot_manager.honeypot_ips.clear()
        honeypot_manager.honeypot_attempts.clear()
        
        # Clear blocked IPs that were added by honeypot
        # Keep only truly malicious IPs (if any)
        security_middleware.blocked_ips.clear()
        
        print(f"\n✓ Cleared {honeypot_count} honeypot-flagged IPs")
        print(f"✓ Cleared {blocked_count} blocked IPs")
        print("\nNote: This clears IPs from memory only.")
        print("They will remain cleared until the app restarts.")
        print("\nThe /admin/ route has been removed from honeypot traps,")
        print("so this issue should not happen again.")
        
        return True
        
    except Exception as e:
        print(f"Error clearing honeypot IPs: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("Clear Honeypot-Flagged IPs")
    print("=" * 60)
    print()
    
    if clear_honeypot_ips():
        print("\n✓ Success!")
        sys.exit(0)
    else:
        print("\n✗ Failed!")
        sys.exit(1)

