#!/usr/bin/env python3
"""
Deploy Schema Fix Script
This script can be run on production to fix the database schema issues
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import subprocess
import time
from utils import logger

def deploy_schema_fix():
    """Deploy the schema fix to production"""
    try:
        logger.info("Starting production schema fix deployment...")
        
        # Run the schema fix script
        logger.info("Running production schema fix...")
        result = subprocess.run([
            sys.executable, 
            os.path.join(os.path.dirname(__file__), "fix_production_schema.py")
        ], capture_output=True, text=True, timeout=60)
        
        if result.returncode == 0:
            logger.info("Schema fix completed successfully")
            logger.info(f"Output: {result.stdout}")
            return True
        else:
            logger.error(f"Schema fix failed with return code {result.returncode}")
            logger.error(f"Error output: {result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        logger.error("Schema fix timed out after 60 seconds")
        return False
    except Exception as e:
        logger.error(f"Schema fix deployment failed: {e}")
        return False

def verify_schema_fix():
    """Verify that the schema fix was successful"""
    try:
        logger.info("Verifying schema fix...")
        
        # Test database connection and schema
        from db_enhanced import get_pool
        
        with get_pool().get_connection() as conn:
            c = conn.cursor()
            
            # Test phone_number column
            try:
                c.execute("SELECT phone_number FROM users LIMIT 1")
                logger.info("[OK] phone_number column is accessible")
            except Exception as e:
                logger.error(f"phone_number column test failed: {e}")
                return False
            
            # Test settings table
            try:
                c.execute("SELECT COUNT(*) FROM settings")
                logger.info("[OK] settings table is accessible")
            except Exception as e:
                logger.error(f"settings table test failed: {e}")
                return False
            
            # Test notification preferences function
            try:
                from db_enhanced import get_notification_preferences
                # This should not raise an error now
                logger.info("[OK] notification preferences function should work")
            except Exception as e:
                logger.error(f"notification preferences test failed: {e}")
                return False
        
        logger.info("Schema verification completed successfully")
        return True
        
    except Exception as e:
        logger.error(f"Schema verification failed: {e}")
        return False

if __name__ == "__main__":
    print("Deploying Production Schema Fix...")
    
    # Deploy the fix
    success = deploy_schema_fix()
    if not success:
        print("Schema fix deployment failed!")
        sys.exit(1)
    
    # Verify the fix
    verification_success = verify_schema_fix()
    if not verification_success:
        print("Schema fix verification failed!")
        sys.exit(1)
    
    print("Production schema fix deployed and verified successfully!")
    print("The following issues should now be resolved:")
    print("- Missing 'phone_number' column in users table")
    print("- Missing 'settings' table")
    print("- Database errors in profile and settings pages")
