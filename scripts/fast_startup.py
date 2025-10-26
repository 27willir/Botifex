#!/usr/bin/env python3
"""
Fast startup script to reduce application initialization time
Addresses timeout issues by optimizing startup sequence
"""

import os
import sys
import time
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from utils import logger

def fast_startup():
    """Optimized startup sequence to reduce timeout issues"""
    start_time = time.time()
    
    try:
        logger.info("Starting fast application initialization...")
        
        # Set optimal environment variables
        os.environ.setdefault('WEB_CONCURRENCY', '2')
        os.environ.setdefault('GUNICORN_WORKER_CLASS', 'gevent')
        os.environ.setdefault('LOG_LEVEL', 'info')
        os.environ.setdefault('PYTHONUNBUFFERED', '1')
        
        # Import and initialize only essential components
        logger.info("Initializing core components...")
        
        # Initialize database with minimal setup
        from db_enhanced import init_db
        init_db()
        
        # Initialize security components
        from security import SecurityConfig
        SecurityConfig.get_secret_key()
        
        # Initialize error handling
        from error_handling import ErrorHandler
        ErrorHandler.initialize()
        
        # Initialize rate limiting
        from rate_limiter import initialize_rate_limiter
        initialize_rate_limiter()
        
        # Initialize cache
        from cache_manager import initialize_cache
        initialize_cache()
        
        elapsed = time.time() - start_time
        logger.info(f"Fast startup completed in {elapsed:.2f} seconds")
        
        return True
        
    except Exception as e:
        logger.error(f"Fast startup failed: {e}")
        return False

def initialize_rate_limiter():
    """Initialize rate limiter with minimal overhead"""
    try:
        from rate_limiter import RateLimiter
        # Initialize with minimal configuration
        RateLimiter.initialize()
    except Exception as e:
        logger.warning(f"Rate limiter initialization failed: {e}")

def initialize_cache():
    """Initialize cache with minimal overhead"""
    try:
        from cache_manager import CacheManager
        # Initialize with minimal configuration
        CacheManager.initialize()
    except Exception as e:
        logger.warning(f"Cache initialization failed: {e}")

if __name__ == "__main__":
    success = fast_startup()
    sys.exit(0 if success else 1)
