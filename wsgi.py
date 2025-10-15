"""
WSGI Entry Point for Production Deployment
This file is used by gunicorn to start the application
"""
import os

# Import the Flask app
from app import app

# Export the Flask app as the WSGI application
# Note: WebSocket functionality may not work with this setup
# For full WebSocket support, consider using a different deployment method
application = app

