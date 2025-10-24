#!/usr/bin/env python3
"""
Initialize security tables in the database
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db_enhanced import init_db
from utils import logger

def main():
    """Initialize security tables"""
    try:
        logger.info("Initializing security tables...")
        
        # Initialize database (this will create the security_events table)
        init_db()
        
        logger.info("✅ Security tables initialized successfully")
        print("✅ Security tables initialized successfully")
        
    except Exception as e:
        logger.error(f"❌ Error initializing security tables: {e}")
        print(f"❌ Error initializing security tables: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
