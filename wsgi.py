"""
WSGI Entry Point for Production Deployment
This file is used by gunicorn to start the application
"""
import os

# Import the Flask app
from app import app

# Export the Flask app as the WSGI application
# This is the callable application that gunicorn expects
application = app

# For WebSocket support with gunicorn, use gevent worker class
# The gunicorn_config.py is already configured for this

