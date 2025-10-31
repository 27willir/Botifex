"""
WSGI Entry Point for Production Deployment
This file is used by gunicorn to start the application
"""
# CRITICAL: Monkey-patch must be FIRST before any other imports
# This fixes the SSL/gevent import order issue
try:
    from gevent import monkey
    monkey.patch_all()
except ImportError:
    # gevent not available, continue without patching
    pass

import os
import sys

# Fix urllib3 connection pool cleanup issues with gevent
# The issue: urllib3's finalizers try to access gevent's thread-local hub during
# shutdown when it's no longer available, causing AttributeError exceptions
try:
    import urllib3
    from urllib3 import connectionpool
    
    # Disable urllib3 warnings
    urllib3.disable_warnings()
    
    # Store reference to the original _close_pool_connections method
    _original_close_pool_connections = connectionpool.HTTPConnectionPool._close_pool_connections
    
    def _gevent_safe_close_pool_connections(self, pool):
        """
        Safely close pool connections, catching gevent hub errors during shutdown.
        This prevents "AttributeError: '_Threadlocal' object has no attribute 'Hub'"
        errors that occur when urllib3 tries to clean up during gevent shutdown.
        """
        try:
            # Try to check if gevent hub is still available
            from gevent import getcurrent
            getcurrent()  # This will raise AttributeError if hub is gone
            # Hub is available, proceed with normal cleanup
            _original_close_pool_connections(self, pool)
        except (AttributeError, RuntimeError):
            # Gevent hub is not available or already torn down
            # Safely drain the pool without gevent synchronization
            try:
                # Use a simple loop without gevent's queue notifications
                while True:
                    conn = pool.get(block=False)
                    if conn:
                        try:
                            conn.close()
                        except Exception:
                            pass  # Ignore errors during shutdown
            except Exception:
                # Queue is empty or other error, that's fine
                pass
        except Exception:
            # Any other error, ignore during shutdown
            pass
    
    # Replace the method with our gevent-safe version
    connectionpool.HTTPConnectionPool._close_pool_connections = _gevent_safe_close_pool_connections
    
except (ImportError, Exception):
    # If urllib3 is not available or patching fails, continue normally
    pass

# Import the Flask app
from app import app

# Export the Flask app as the WSGI application
# This is the callable application that gunicorn expects
application = app

# For WebSocket support with gunicorn, use gevent worker class
# The gunicorn_config.py is already configured for this

