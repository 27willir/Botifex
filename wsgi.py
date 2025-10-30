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

# Import the Flask app
from app import app

# Export the Flask app as the WSGI application
# This is the callable application that gunicorn expects
application = app

# For WebSocket support with gunicorn, use gevent worker class
# The gunicorn_config.py is already configured for this

