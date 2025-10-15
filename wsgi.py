"""
WSGI Entry Point for Production Deployment
This file is used by gunicorn to start the application
"""
import os
from app import app, socketio

# Export the WSGI application
# For Flask-SocketIO with gunicorn, we use the socketio object
application = socketio

