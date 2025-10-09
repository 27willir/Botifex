# rate_limiter.py - Rate limiting middleware for handling high-traffic scenarios
from functools import wraps
from flask import request, jsonify, g
from flask_login import current_user
from datetime import datetime
from utils import logger
import db_enhanced


# Rate limit configurations (requests per minute)
RATE_LIMITS = {
    'api': 60,           # 60 requests per minute for API endpoints
    'scraper': 10,       # 10 scraper start/stop per minute
    'settings': 30,      # 30 settings updates per minute
    'login': 5,          # 5 login attempts per minute
    'register': 3,       # 3 registration attempts per minute
}


def get_rate_limit_key(endpoint_type):
    """Generate rate limit key based on user and endpoint type"""
    if current_user.is_authenticated:
        return f"{current_user.id}:{endpoint_type}"
    else:
        # Use IP address for unauthenticated users
        return f"{request.remote_addr}:{endpoint_type}"


def rate_limit(endpoint_type, max_requests=None, window_minutes=1):
    """
    Rate limiting decorator
    
    Usage:
        @rate_limit('api')
        def my_api_endpoint():
            ...
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Determine max requests
            requests_limit = max_requests if max_requests is not None else RATE_LIMITS.get(endpoint_type, 60)
            
            # Get username for rate limiting
            if current_user.is_authenticated:
                username = current_user.id
            else:
                username = request.remote_addr  # Use IP for non-authenticated users
            
            # Check rate limit
            is_allowed, remaining = db_enhanced.check_rate_limit(
                username, 
                endpoint_type, 
                requests_limit, 
                window_minutes
            )
            
            if not is_allowed:
                logger.warning(f"Rate limit exceeded for {username} on {endpoint_type}")
                return jsonify({
                    'error': 'Rate limit exceeded',
                    'message': f'Too many requests. Please try again in {window_minutes} minute(s).',
                    'retry_after': window_minutes * 60
                }), 429
            
            # Store remaining requests in Flask's g object for potential use in response
            g.rate_limit_remaining = remaining
            
            return f(*args, **kwargs)
        
        return decorated_function
    return decorator


def add_rate_limit_headers(response):
    """Add rate limit headers to response"""
    if hasattr(g, 'rate_limit_remaining'):
        response.headers['X-RateLimit-Remaining'] = str(g.rate_limit_remaining)
    return response


# Admin functions

def reset_user_rate_limits(username):
    """Reset all rate limits for a user (admin function)"""
    try:
        db_enhanced.reset_rate_limit(username)
        logger.info(f"Admin reset rate limits for user: {username}")
        return True
    except Exception as e:
        logger.error(f"Error resetting rate limits for {username}: {e}")
        return False


def get_rate_limit_status(username, endpoint_type):
    """Get current rate limit status for a user"""
    try:
        # This would need a new DB function to query current status
        # For now, return a placeholder
        return {
            'username': username,
            'endpoint': endpoint_type,
            'status': 'active'
        }
    except Exception as e:
        logger.error(f"Error getting rate limit status: {e}")
        return None
