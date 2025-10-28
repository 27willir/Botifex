# admin_panel.py - Admin dashboard routes for managing users and monitoring system
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from functools import wraps
from datetime import datetime, timedelta
import db_enhanced
from utils import logger
from rate_limiter import reset_user_rate_limits
from cache_manager import get_cache, cache_clear
from security_middleware import get_security_stats

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

# Debug route to check user role
@admin_bp.route('/check-role')
@login_required
def check_role():
    """Debug route to check user's role"""
    # Get fresh user data from database
    user_data = db_enhanced.get_user_by_username(current_user.id)
    
    debug_info = {
        'current_user_id': current_user.id,
        'current_user_has_role_attr': hasattr(current_user, 'role'),
        'current_user_role': getattr(current_user, 'role', 'NO ROLE ATTRIBUTE'),
        'db_user_data': str(user_data) if user_data else 'NO USER DATA',
        'db_role': user_data[4] if user_data else 'NO USER DATA',
        'cache_cleared': True,
        'message': 'If roles mismatch, please log out and log back in to refresh your session.'
    }
    
    # Clear user cache so next request loads fresh data
    cache_key = f"user:{current_user.id}"
    cache_clear(cache_key)
    logger.info(f"Cleared cache for user {current_user.id}. Session role: {getattr(current_user, 'role', 'NONE')}, DB role: {user_data[4] if user_data else 'NONE'}")
    
    return jsonify(debug_info)


def admin_required(f):
    """Decorator to require admin role"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash("Please log in to access this page.", "error")
            return redirect(url_for("login"))
        
        # Check role from current_user object (already loaded by Flask-Login)
        if not hasattr(current_user, 'role'):
            logger.error(f"User {current_user.id} does not have role attribute")
            flash("Access denied. Admin privileges required.", "error")
            return redirect(url_for("dashboard"))
        
        if current_user.role != 'admin':
            logger.warning(f"User {current_user.id} attempted to access admin panel with role: {current_user.role}")
            flash("Access denied. Admin privileges required.", "error")
            return redirect(url_for("dashboard"))
        
        return f(*args, **kwargs)
    return decorated_function


@admin_bp.route('/')
@login_required
@admin_required
def dashboard():
    """Admin dashboard overview"""
    try:
        logger.info(f"Admin dashboard accessed by user: {current_user.id} with role: {current_user.role}")
        
        # Get system statistics
        user_count = db_enhanced.get_user_count()
        listing_count = db_enhanced.get_listing_count()
        
        # Get recent activity
        recent_activity = db_enhanced.get_recent_activity(limit=50)
        
        # Get cache stats
        cache_stats = get_cache().get_stats()
        
        # Get user list
        users = db_enhanced.get_all_users()
        
        stats = {
            'total_users': user_count,
            'total_listings': listing_count,
            'active_users': sum(1 for u in users if u[5]),  # active is at index 5
            'admin_users': sum(1 for u in users if u[4] == 'admin'),  # role is at index 4
            'cache_keys': cache_stats['active_keys'],
        }
        
        return render_template('admin/dashboard.html', 
                             stats=stats, 
                             recent_activity=recent_activity,
                             users=users[:20])  # Show first 20 users
    
    except Exception as e:
        logger.error(f"Error loading admin dashboard: {e}")
        flash("Error loading dashboard", "error")
        return redirect(url_for("index"))


@admin_bp.route('/users')
@login_required
@admin_required
def users():
    """User management page"""
    try:
        all_users = db_enhanced.get_all_users()
        return render_template('admin/users.html', users=all_users)
    except Exception as e:
        logger.error(f"Error loading users page: {e}")
        flash("Error loading users", "error")
        return redirect(url_for("admin.dashboard"))


@admin_bp.route('/user/<username>')
@login_required
@admin_required
def user_detail(username):
    """User detail and activity page"""
    try:
        user = db_enhanced.get_user_by_username(username)
        if not user:
            flash("User not found", "error")
            return redirect(url_for("admin.users"))
        
        # Get user activity
        activity = db_enhanced.get_user_activity(username, limit=100)
        
        # Get user settings
        settings = db_enhanced.get_settings(username)
        
        # Get user listings count
        listing_count = db_enhanced.get_listing_count(user_id=username)
        
        user_data = {
            'username': user[0],
            'email': user[1],
            'role': user[4],
            'active': user[5],
            'created_at': user[6],
            'last_login': user[7],
            'login_count': user[8],
            'listing_count': listing_count,
        }
        
        return render_template('admin/user_detail.html', 
                             user=user_data, 
                             activity=activity,
                             settings=settings)
    
    except Exception as e:
        logger.error(f"Error loading user detail: {e}")
        flash("Error loading user details", "error")
        return redirect(url_for("admin.users"))


@admin_bp.route('/user/<username>/update-role', methods=['POST'])
@login_required
@admin_required
def update_user_role(username):
    """Update user role"""
    try:
        new_role = request.form.get('role')
        if new_role not in ['user', 'admin']:
            flash("Invalid role", "error")
            return redirect(url_for("admin.user_detail", username=username))
        
        db_enhanced.update_user_role(username, new_role)
        db_enhanced.log_user_activity(
            current_user.id,
            'update_user_role',
            f"Changed role of {username} to {new_role}",
            request.remote_addr,
            request.headers.get('User-Agent')
        )
        
        flash(f"User role updated to {new_role}", "success")
        return redirect(url_for("admin.user_detail", username=username))
    
    except Exception as e:
        logger.error(f"Error updating user role: {e}")
        flash("Error updating user role", "error")
        return redirect(url_for("admin.user_detail", username=username))


@admin_bp.route('/user/<username>/deactivate', methods=['POST'])
@login_required
@admin_required
def deactivate_user(username):
    """Deactivate user account"""
    try:
        if username == current_user.id:
            flash("Cannot deactivate your own account", "error")
            return redirect(url_for("admin.user_detail", username=username))
        
        db_enhanced.deactivate_user(username)
        db_enhanced.log_user_activity(
            current_user.id,
            'deactivate_user',
            f"Deactivated user {username}",
            request.remote_addr,
            request.headers.get('User-Agent')
        )
        
        flash(f"User {username} has been deactivated", "success")
        return redirect(url_for("admin.users"))
    
    except Exception as e:
        logger.error(f"Error deactivating user: {e}")
        flash("Error deactivating user", "error")
        return redirect(url_for("admin.user_detail", username=username))


@admin_bp.route('/user/<username>/reset-rate-limit', methods=['POST'])
@login_required
@admin_required
def reset_rate_limit(username):
    """Reset rate limits for a user"""
    try:
        if reset_user_rate_limits(username):
            db_enhanced.log_user_activity(
                current_user.id,
                'reset_rate_limit',
                f"Reset rate limits for {username}",
                request.remote_addr,
                request.headers.get('User-Agent')
            )
            flash(f"Rate limits reset for {username}", "success")
        else:
            flash("Error resetting rate limits", "error")
        
        return redirect(url_for("admin.user_detail", username=username))
    
    except Exception as e:
        logger.error(f"Error resetting rate limits: {e}")
        flash("Error resetting rate limits", "error")
        return redirect(url_for("admin.user_detail", username=username))


@admin_bp.route('/activity')
@login_required
@admin_required
def activity():
    """System activity page"""
    try:
        days = request.args.get('days', 7, type=int)
        limit = request.args.get('limit', 200, type=int)
        
        recent_activity = db_enhanced.get_recent_activity(limit=limit)
        
        return render_template('admin/activity.html', 
                             activity=recent_activity,
                             days=days)
    
    except Exception as e:
        logger.error(f"Error loading activity page: {e}")
        flash("Error loading activity", "error")
        return redirect(url_for("admin.dashboard"))


@admin_bp.route('/cache')
@login_required
@admin_required
def cache_management():
    """Cache management page"""
    try:
        cache_stats = get_cache().get_stats()
        return render_template('admin/cache.html', stats=cache_stats)
    
    except Exception as e:
        logger.error(f"Error loading cache page: {e}")
        flash("Error loading cache management", "error")
        return redirect(url_for("admin.dashboard"))


@admin_bp.route('/cache/clear', methods=['POST'])
@login_required
@admin_required
def clear_cache():
    """Clear all cache"""
    try:
        get_cache().clear()
        db_enhanced.log_user_activity(
            current_user.id,
            'clear_cache',
            "Cleared all cache",
            request.remote_addr,
            request.headers.get('User-Agent')
        )
        flash("Cache cleared successfully", "success")
        return redirect(url_for("admin.cache_management"))
    
    except Exception as e:
        logger.error(f"Error clearing cache: {e}")
        flash("Error clearing cache", "error")
        return redirect(url_for("admin.cache_management"))


@admin_bp.route('/cache/cleanup', methods=['POST'])
@login_required
@admin_required
def cleanup_cache():
    """Cleanup expired cache entries"""
    try:
        count = get_cache().cleanup_expired()
        db_enhanced.log_user_activity(
            current_user.id,
            'cleanup_cache',
            f"Cleaned up {count} expired cache entries",
            request.remote_addr,
            request.headers.get('User-Agent')
        )
        flash(f"Cleaned up {count} expired cache entries", "success")
        return redirect(url_for("admin.cache_management"))
    
    except Exception as e:
        logger.error(f"Error cleaning up cache: {e}")
        flash("Error cleaning up cache", "error")
        return redirect(url_for("admin.cache_management"))


@admin_bp.route('/security')
@login_required
@admin_required
def security_monitoring():
    """Security monitoring page"""
    try:
        # Get security statistics
        security_stats = get_security_stats()
        
        # Get recent security events
        security_events = db_enhanced.get_security_events(limit=100, hours=24)
        
        return render_template('admin/security.html', 
                            stats=security_stats, 
                            events=security_events)
    
    except Exception as e:
        logger.error(f"Error loading security page: {e}")
        flash("Error loading security monitoring page", "error")
        return redirect(url_for("admin.dashboard"))


@admin_bp.route('/security/events')
@login_required
@admin_required
def security_events():
    """Get security events as JSON"""
    try:
        hours = request.args.get('hours', 24, type=int)
        limit = request.args.get('limit', 100, type=int)
        
        events = db_enhanced.get_security_events(limit=limit, hours=hours)
        
        return jsonify({
            'events': events,
            'count': len(events)
        })
    
    except Exception as e:
        logger.error(f"Error getting security events: {e}")
        return jsonify({'error': 'Failed to get security events'}), 500


# API endpoints for admin dashboard

@admin_bp.route('/api/stats')
@login_required
@admin_required
def api_stats():
    """Get system statistics"""
    try:
        user_count = db_enhanced.get_user_count()
        listing_count = db_enhanced.get_listing_count()
        cache_stats = get_cache().get_stats()
        
        return jsonify({
            'users': user_count,
            'listings': listing_count,
            'cache_keys': cache_stats['active_keys'],
            'cache_expired': cache_stats['expired_keys'],
        })
    
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/api/users')
@login_required
@admin_required
def api_users():
    """Get all users (API)"""
    try:
        users = db_enhanced.get_all_users()
        user_list = [{
            'username': u[0],
            'email': u[1],
            'role': u[4],
            'active': u[5],
            'created_at': str(u[6]),
            'last_login': str(u[7]) if u[7] else None,
            'login_count': u[8]
        } for u in users]
        
        return jsonify({'users': user_list})
    
    except Exception as e:
        logger.error(f"Error getting users: {e}")
        return jsonify({'error': str(e)}), 500


# ======================
# SUBSCRIPTION MANAGEMENT
# ======================

@admin_bp.route('/subscriptions')
@login_required
@admin_required
def subscriptions():
    """View all subscriptions"""
    try:
        # Get subscription statistics
        stats = db_enhanced.get_subscription_stats()
        
        # Get all subscriptions
        all_subscriptions = db_enhanced.get_all_subscriptions()
        
        # Calculate MRR (Monthly Recurring Revenue)
        mrr = (stats['standard_count'] * 19.99) + (stats['pro_count'] * 49.99)
        
        return render_template('admin/subscriptions.html',
                             stats=stats,
                             subscriptions=all_subscriptions,
                             mrr=mrr)
    
    except Exception as e:
        logger.error(f"Error loading subscriptions: {e}")
        flash("Error loading subscription data", "error")
        return redirect(url_for('admin.dashboard'))


@admin_bp.route('/api/subscription-stats')
@login_required
@admin_required
def api_subscription_stats():
    """Get subscription statistics (API)"""
    try:
        stats = db_enhanced.get_subscription_stats()
        mrr = (stats['standard_count'] * 19.99) + (stats['pro_count'] * 49.99)
        
        return jsonify({
            'stats': stats,
            'mrr': round(mrr, 2)
        })
    
    except Exception as e:
        logger.error(f"Error getting subscription stats: {e}")
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/user/<username>/update-subscription', methods=['POST'])
@login_required
@admin_required
def update_user_subscription(username):
    """Manually update a user's subscription (admin only)"""
    try:
        tier = request.form.get('tier', 'free')
        status = request.form.get('status', 'active')
        
        # Validate tier
        if tier not in ['free', 'standard', 'pro']:
            flash("Invalid subscription tier", "error")
            return redirect(url_for('admin.user_detail', username=username))
        
        # Update subscription
        db_enhanced.create_or_update_subscription(
            username=username,
            tier=tier,
            status=status
        )
        
        # Log the event
        db_enhanced.log_subscription_event(
            username=username,
            tier=tier,
            action='admin_update',
            details=f'Subscription updated by admin: {current_user.id}'
        )
        
        # Log admin activity
        db_enhanced.log_user_activity(
            current_user.id,
            'admin_update_subscription',
            f'Updated subscription for {username} to {tier}',
            request.remote_addr,
            request.headers.get('User-Agent')
        )
        
        flash(f"Subscription updated for {username} to {tier} tier", "success")
        return redirect(url_for('admin.user_detail', username=username))
    
    except Exception as e:
        logger.error(f"Error updating subscription: {e}")
        flash("Error updating subscription", "error")
        return redirect(url_for('admin.user_detail', username=username))