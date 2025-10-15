"""
Subscription Middleware and Decorators
Enforces subscription limits and feature access
"""

from functools import wraps
from flask import flash, redirect, url_for, jsonify, request
from flask_login import current_user
import db_enhanced
from subscriptions import SubscriptionManager
from utils import logger


def require_subscription_tier(required_tier):
    """
    Decorator to require a specific subscription tier or higher
    Tiers hierarchy: free < standard < pro
    """
    tier_hierarchy = {'free': 0, 'standard': 1, 'pro': 2}
    
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                flash("Please log in to access this feature", "error")
                return redirect(url_for('login'))
            
            # Admins bypass all subscription checks
            if hasattr(current_user, 'role') and current_user.role == 'admin':
                return f(*args, **kwargs)
            
            # Get user's subscription
            subscription = db_enhanced.get_user_subscription(current_user.id)
            user_tier = subscription.get('tier', 'free')
            
            # Check tier hierarchy
            user_level = tier_hierarchy.get(user_tier, 0)
            required_level = tier_hierarchy.get(required_tier, 0)
            
            if user_level < required_level:
                logger.warning(f"User {current_user.id} attempted to access {required_tier} feature with {user_tier} tier")
                
                # Check if this is an API request
                if request.path.startswith('/api/'):
                    return jsonify({
                        "error": "Upgrade required",
                        "message": f"This feature requires a {required_tier} subscription",
                        "current_tier": user_tier,
                        "required_tier": required_tier
                    }), 403
                
                flash(f"This feature requires a {required_tier} subscription. Please upgrade your plan.", "error")
                return redirect(url_for('subscription_plans'))
            
            return f(*args, **kwargs)
        
        return decorated_function
    return decorator


def require_feature(feature_name):
    """
    Decorator to check if user's subscription includes a specific feature
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                flash("Please log in to access this feature", "error")
                return redirect(url_for('login'))
            
            # Admins bypass all subscription checks
            if hasattr(current_user, 'role') and current_user.role == 'admin':
                return f(*args, **kwargs)
            
            # Get user's subscription
            subscription = db_enhanced.get_user_subscription(current_user.id)
            user_tier = subscription.get('tier', 'free')
            
            # Check if feature is available
            if not SubscriptionManager.can_use_feature(user_tier, feature_name):
                logger.warning(f"User {current_user.id} attempted to access {feature_name} feature not in {user_tier} tier")
                
                # Check if this is an API request
                if request.path.startswith('/api/'):
                    return jsonify({
                        "error": "Feature not available",
                        "message": f"The {feature_name} feature is not available in your current plan",
                        "current_tier": user_tier
                    }), 403
                
                flash(f"The {feature_name} feature is not available in your current plan. Please upgrade.", "error")
                return redirect(url_for('subscription_plans'))
            
            return f(*args, **kwargs)
        
        return decorated_function
    return decorator


def check_keyword_limit():
    """
    Decorator to check if user is within their keyword limit
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return f(*args, **kwargs)
            
            # Admins bypass all subscription checks
            if hasattr(current_user, 'role') and current_user.role == 'admin':
                return f(*args, **kwargs)
            
            # Get user's subscription
            subscription = db_enhanced.get_user_subscription(current_user.id)
            user_tier = subscription.get('tier', 'free')
            
            # Get keywords from form
            keywords_str = request.form.get('keywords', '')
            if keywords_str:
                keywords = [k.strip() for k in keywords_str.split(',') if k.strip()]
                keyword_count = len(keywords)
                
                # Validate keyword count
                is_valid, error_msg = SubscriptionManager.validate_keyword_count(user_tier, keyword_count)
                
                if not is_valid:
                    logger.warning(f"User {current_user.id} exceeded keyword limit: {keyword_count} keywords with {user_tier} tier")
                    
                    # Check if this is an API request
                    if request.path.startswith('/api/'):
                        return jsonify({
                            "error": "Keyword limit exceeded",
                            "message": error_msg,
                            "current_tier": user_tier,
                            "keyword_count": keyword_count,
                            "max_keywords": SubscriptionManager.get_keyword_limit(user_tier)
                        }), 400
                    
                    flash(error_msg, "error")
                    return redirect(url_for('settings'))
            
            return f(*args, **kwargs)
        
        return decorated_function
    return decorator


def check_refresh_interval():
    """
    Decorator to check if refresh interval meets subscription requirements
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return f(*args, **kwargs)
            
            # Admins bypass all subscription checks
            if hasattr(current_user, 'role') and current_user.role == 'admin':
                return f(*args, **kwargs)
            
            # Get user's subscription
            subscription = db_enhanced.get_user_subscription(current_user.id)
            user_tier = subscription.get('tier', 'free')
            
            # Get interval from form (in minutes)
            interval_str = request.form.get('interval', '')
            if interval_str:
                try:
                    interval_minutes = int(interval_str)
                    interval_seconds = interval_minutes * 60
                    
                    # Validate refresh interval
                    is_valid, error_msg = SubscriptionManager.validate_refresh_interval(user_tier, interval_seconds)
                    
                    if not is_valid:
                        logger.warning(f"User {current_user.id} tried to set invalid interval: {interval_minutes} min with {user_tier} tier")
                        
                        # Check if this is an API request
                        if request.path.startswith('/api/'):
                            return jsonify({
                                "error": "Invalid refresh interval",
                                "message": error_msg,
                                "current_tier": user_tier,
                                "requested_interval": interval_minutes,
                                "min_interval_minutes": SubscriptionManager.get_refresh_interval(user_tier) // 60
                            }), 400
                        
                        flash(error_msg, "error")
                        return redirect(url_for('settings'))
                
                except ValueError:
                    pass  # Let the normal validation handle invalid values
            
            return f(*args, **kwargs)
        
        return decorated_function
    return decorator


def check_platform_access():
    """
    Decorator to check if platforms are allowed for user's subscription
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return f(*args, **kwargs)
            
            # Admins bypass all subscription checks
            if hasattr(current_user, 'role') and current_user.role == 'admin':
                return f(*args, **kwargs)
            
            # Get user's subscription
            subscription = db_enhanced.get_user_subscription(current_user.id)
            user_tier = subscription.get('tier', 'free')
            
            # Determine which platform is being accessed
            # Check URL path for platform name
            platform = None
            if 'site' in kwargs:
                platform = kwargs['site']
            elif len(args) > 0:
                platform = args[0]
            
            if platform:
                # Validate platform access
                is_valid, error_msg = SubscriptionManager.validate_platform_access(user_tier, [platform])
                
                if not is_valid:
                    logger.warning(f"User {current_user.id} attempted to access {platform} with {user_tier} tier")
                    
                    # Check if this is an API request
                    if request.path.startswith('/api/'):
                        return jsonify({
                            "error": "Platform not available",
                            "message": error_msg,
                            "current_tier": user_tier,
                            "platform": platform,
                            "allowed_platforms": SubscriptionManager.get_allowed_platforms(user_tier)
                        }), 403
                    
                    flash(error_msg, "error")
                    return redirect(url_for('index'))
            
            return f(*args, **kwargs)
        
        return decorated_function
    return decorator


def get_user_tier():
    """
    Helper function to get current user's subscription tier
    """
    if not current_user.is_authenticated:
        return 'free'
    
    # Admins get pro tier features
    if hasattr(current_user, 'role') and current_user.role == 'admin':
        return 'pro'
    
    subscription = db_enhanced.get_user_subscription(current_user.id)
    return subscription.get('tier', 'free')


def get_user_features():
    """
    Helper function to get current user's subscription features
    """
    tier = get_user_tier()
    features = SubscriptionManager.get_user_tier_features(tier)
    
    # Add Poshmark and Mercari feature flags (already in features dict, but ensure they're set)
    if 'poshmark' not in features:
        features['poshmark'] = (tier == 'pro')
    if 'mercari' not in features:
        features['mercari'] = (tier == 'pro')
    
    return features


def can_access_feature(feature_name):
    """
    Helper function to check if current user can access a feature
    """
    if not current_user.is_authenticated:
        return False
    
    # Admins can access all features
    if hasattr(current_user, 'role') and current_user.role == 'admin':
        return True
    
    tier = get_user_tier()
    return SubscriptionManager.can_use_feature(tier, feature_name)


def add_subscription_context():
    """
    Add subscription information to template context
    This should be called in a before_request handler or context processor
    """
    if current_user.is_authenticated:
        # Admins get pro tier features
        if hasattr(current_user, 'role') and current_user.role == 'admin':
            features = SubscriptionManager.get_user_tier_features('pro')
            return {
                'user_subscription': {'tier': 'pro', 'status': 'active'},
                'user_tier': 'pro',
                'user_features': features,
                'can_use_analytics': True,
                'can_use_selling': True,
                'max_keywords': features.get('max_keywords', 999),
                'min_refresh_interval': features.get('refresh_interval', 60) // 60,  # Convert to minutes
                'allowed_platforms': features.get('platforms', ['craigslist', 'facebook', 'ksl']),
                'is_admin': True
            }
        
        subscription = db_enhanced.get_user_subscription(current_user.id)
        tier = subscription.get('tier', 'free')
        features = SubscriptionManager.get_user_tier_features(tier)
        
        return {
            'user_subscription': subscription,
            'user_tier': tier,
            'user_features': features,
            'can_use_analytics': features.get('analytics', False),
            'can_use_selling': features.get('selling', False),
            'max_keywords': features.get('max_keywords', 2),
            'min_refresh_interval': features.get('refresh_interval', 600) // 60,  # Convert to minutes
            'allowed_platforms': features.get('platforms', ['craigslist']),
            'is_admin': False
        }
    
    return {
        'user_subscription': None,
        'user_tier': 'free',
        'user_features': SubscriptionManager.get_user_tier_features('free'),
        'can_use_analytics': False,
        'can_use_selling': False,
        'max_keywords': 2,
        'min_refresh_interval': 10,
        'allowed_platforms': ['craigslist']
    }

