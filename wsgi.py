"""
WSGI Entry Point for Production Deployment
This file is used by gunicorn to start the application
"""
import os

# Import the app module to ensure everything is initialized
from app import app, socketio

# Export the socketio object as the WSGI application
# Flask-SocketIO with gevent worker requires using the socketio object
application = socketio

