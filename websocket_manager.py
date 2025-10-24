"""
WebSocket Manager for Real-Time Notifications
Handles real-time updates for listings, alerts, and system status
"""

from flask_socketio import SocketIO, emit, join_room, leave_room, rooms
from flask_login import current_user
from utils import logger
from datetime import datetime

# Initialize SocketIO (will be configured in app.py)
socketio = None


def init_socketio(app):
    """Initialize SocketIO with the Flask app"""
    global socketio
    # Use threading mode for compatibility with Python 3.13
    # This avoids issues with gevent/eventlet compatibility
    socketio = SocketIO(
        app,
        cors_allowed_origins="*",
        logger=False,
        engineio_logger=False,
        async_mode='threading'
    )
    
    # Register event handlers
    register_events()
    
    logger.info("[OK] WebSocket server initialized")
    return socketio


def register_events():
    """Register WebSocket event handlers"""
    
    @socketio.on('connect')
    def handle_connect():
        """Handle client connection"""
        if current_user.is_authenticated:
            # Join user-specific room for targeted notifications
            join_room(f"user_{current_user.id}")
            logger.info(f"WebSocket: User {current_user.id} connected")
            
            emit('connection_status', {
                'status': 'connected',
                'username': current_user.id,
                'timestamp': datetime.now().isoformat()
            })
        else:
            emit('connection_status', {
                'status': 'connected',
                'authenticated': False
            })
    
    @socketio.on('disconnect')
    def handle_disconnect():
        """Handle client disconnection"""
        if current_user.is_authenticated:
            logger.info(f"WebSocket: User {current_user.id} disconnected")
            leave_room(f"user_{current_user.id}")
    
    @socketio.on('subscribe_scraper_status')
    def handle_subscribe_scraper_status():
        """Subscribe to scraper status updates"""
        if current_user.is_authenticated:
            join_room('scraper_status')
            logger.debug(f"User {current_user.id} subscribed to scraper status")
            emit('subscribed', {'channel': 'scraper_status'})
    
    @socketio.on('unsubscribe_scraper_status')
    def handle_unsubscribe_scraper_status():
        """Unsubscribe from scraper status updates"""
        if current_user.is_authenticated:
            leave_room('scraper_status')
            logger.debug(f"User {current_user.id} unsubscribed from scraper status")
            emit('unsubscribed', {'channel': 'scraper_status'})
    
    @socketio.on('ping')
    def handle_ping():
        """Handle ping for connection health check"""
        emit('pong', {'timestamp': datetime.now().isoformat()})


# ======================
# BROADCAST FUNCTIONS
# ======================

def broadcast_new_listing(listing_data):
    """Broadcast a new listing to all connected clients"""
    if socketio:
        try:
            socketio.emit('new_listing', {
                'id': listing_data.get('id'),
                'title': listing_data.get('title'),
                'price': listing_data.get('price'),
                'link': listing_data.get('link'),
                'source': listing_data.get('source'),
                'image_url': listing_data.get('image_url'),
                'created_at': listing_data.get('created_at')
            }, namespace='/', room=None)
            logger.debug(f"Broadcast new listing: {listing_data.get('title')}")
        except Exception as e:
            logger.error(f"Error broadcasting new listing: {e}")


def notify_user(username, notification_type, data):
    """Send notification to a specific user"""
    if socketio:
        try:
            room = f"user_{username}"
            socketio.emit('notification', {
                'type': notification_type,
                'data': data,
                'timestamp': datetime.now().isoformat()
            }, namespace='/', room=room)
            logger.debug(f"Notified user {username}: {notification_type}")
        except Exception as e:
            logger.error(f"Error notifying user: {e}")


def broadcast_scraper_status(status_data):
    """Broadcast scraper status changes"""
    if socketio:
        try:
            socketio.emit('scraper_status_update', {
                'facebook': status_data.get('facebook'),
                'craigslist': status_data.get('craigslist'),
                'ksl': status_data.get('ksl'),
                'timestamp': datetime.now().isoformat()
            }, namespace='/', room='scraper_status')
            logger.debug("Broadcast scraper status update")
        except Exception as e:
            logger.error(f"Error broadcasting scraper status: {e}")


def notify_price_alert_triggered(username, alert_data):
    """Notify user when price alert triggers"""
    notify_user(username, 'price_alert', {
        'keywords': alert_data.get('keywords'),
        'threshold_price': alert_data.get('threshold_price'),
        'listing': alert_data.get('listing'),
        'message': f"Price alert triggered for {alert_data.get('keywords')}"
    })


def notify_saved_search_results(username, search_name, results_count):
    """Notify user when saved search finds new results"""
    notify_user(username, 'saved_search', {
        'search_name': search_name,
        'results_count': results_count,
        'message': f"Your saved search '{search_name}' found {results_count} new listings"
    })


def broadcast_system_message(message, level='info'):
    """Broadcast system-wide message"""
    if socketio:
        try:
            socketio.emit('system_message', {
                'message': message,
                'level': level,
                'timestamp': datetime.now().isoformat()
            }, namespace='/')
            logger.info(f"Broadcast system message: {message}")
        except Exception as e:
            logger.error(f"Error broadcasting system message: {e}")


# ======================
# HELPER FUNCTIONS
# ======================

def get_connected_users():
    """Get count of connected users"""
    if socketio:
        # This is a simplified version - in production you'd track this properly
        return len([room for room in rooms() if room.startswith('user_')])
    return 0


__all__ = [
    'init_socketio',
    'socketio',
    'broadcast_new_listing',
    'notify_user',
    'broadcast_scraper_status',
    'notify_price_alert_triggered',
    'notify_saved_search_results',
    'broadcast_system_message',
    'get_connected_users',
]

