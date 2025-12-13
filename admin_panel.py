# admin_panel.py - Admin dashboard routes for managing users and monitoring system
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from functools import wraps
from datetime import datetime, timedelta, date
import json
import db_enhanced
from utils import logger, get_chrome_diagnostics
from rate_limiter import reset_user_rate_limits
from cache_manager import get_cache, cache_user_data, cache_set
from security_middleware import get_security_stats

# Import scraper metrics
try:
    from scrapers.metrics import get_metrics_summary, get_performance_status, get_recent_runs
except ImportError:
    logger.warning("Could not import scraper metrics module")
    get_metrics_summary = None
    get_performance_status = None
    get_recent_runs = None

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

_KNOWN_TIMESTAMP_FORMATS = (
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d"
)


def _format_timestamp(value, mode='datetime_minutes'):
    """Normalize datetime-like values into formatted strings for templates."""
    if not value:
        return None

    def _format_datetime(dt: datetime) -> str:
        if mode == 'date':
            return dt.date().isoformat()
        if mode == 'datetime':
            return dt.isoformat(sep=' ', timespec='seconds')
        if mode == 'datetime_minutes':
            return dt.replace(second=0, microsecond=0).isoformat(sep=' ', timespec='minutes')
        return dt.isoformat(sep=' ', timespec='seconds')

    if isinstance(value, datetime):
        return _format_datetime(value)

    if isinstance(value, date):
        if mode == 'date':
            return value.isoformat()
        return _format_datetime(datetime.combine(value, datetime.min.time()))

    if isinstance(value, str):
        value_str = value.strip()
        for fmt in _KNOWN_TIMESTAMP_FORMATS:
            try:
                parsed = datetime.strptime(value_str, fmt)
            except ValueError:
                continue
            return _format_datetime(parsed)

        if mode == 'date':
            return value_str[:10]
        if mode == 'datetime_minutes':
            without_microseconds = value_str.split('.', 1)[0]
            return without_microseconds[:16] if len(without_microseconds) >= 16 else without_microseconds
        if mode == 'datetime':
            return value_str.split('.', 1)[0]
        return value_str

    try:
        numeric_value = float(value)
        return _format_datetime(datetime.fromtimestamp(numeric_value))
    except (TypeError, ValueError, OSError):
        return str(value)


def _normalize_user_row(row):
    """Return a tuple suitable for template rendering with formatted timestamps."""
    row_list = list(row)
    if len(row_list) > 6:
        row_list[6] = _format_timestamp(row_list[6], mode='date')
    if len(row_list) > 7:
        row_list[7] = _format_timestamp(row_list[7], mode='datetime_minutes')
    return tuple(row_list)


def _normalize_activity_records(records, timestamp_index, mode='datetime_minutes'):
    """Normalize activity records ensuring timestamp indexes are formatted."""
    normalized = []
    for record in records or []:
        record_list = list(record)
        if len(record_list) > timestamp_index:
            record_list[timestamp_index] = _format_timestamp(record_list[timestamp_index], mode=mode)
        normalized.append(tuple(record_list))
    return normalized


def _format_subscription_record(record):
    """Normalize subscription dictionary values for safe template rendering."""
    if not record:
        return {}
    formatted = dict(record)
    formatted['current_period_end'] = _format_timestamp(record.get('current_period_end'), mode='datetime_minutes')
    formatted['created_at'] = _format_timestamp(record.get('created_at'), mode='datetime_minutes')
    return formatted


def _format_scraper_metrics(metrics):
    """Normalize scraper metrics dictionaries, especially last_run timestamps."""
    if not metrics:
        return {}

    formatted = dict(metrics)
    last_run = formatted.get('last_run')
    if last_run:
        formatted_last_run = dict(last_run)
        formatted_last_run['timestamp'] = _format_timestamp(last_run.get('timestamp'), mode='datetime_minutes')
        formatted_last_run['start_time'] = _format_timestamp(last_run.get('start_time'), mode='datetime_minutes')
        formatted_last_run['end_time'] = _format_timestamp(last_run.get('end_time'), mode='datetime_minutes')
        formatted['last_run'] = formatted_last_run
        formatted['last_run_display'] = formatted_last_run.get('timestamp')
    else:
        formatted['last_run'] = None
        formatted['last_run_display'] = None

    return formatted


def _format_settings_for_display(settings: dict | None):
    """Prepare user settings for admin display with light normalization."""
    if not settings:
        return []

    display_entries = []
    for key in sorted(settings.keys()):
        raw_value = settings.get(key)
        parsed_value = raw_value
        is_preformatted = False

        if isinstance(raw_value, (dict, list)):
            parsed_value = raw_value
        elif isinstance(raw_value, str):
            candidate = raw_value.strip()
            if candidate:
                try:
                    parsed_candidate = json.loads(candidate)
                    parsed_value = parsed_candidate
                except (json.JSONDecodeError, TypeError):
                    lowered = candidate.lower()
                    if lowered in {"true", "false"}:
                        parsed_value = lowered == "true"
                    else:
                        try:
                            parsed_value = int(candidate)
                        except ValueError:
                            try:
                                parsed_value = float(candidate)
                            except ValueError:
                                parsed_value = raw_value
            else:
                parsed_value = ""

        if isinstance(parsed_value, (dict, list)):
            display_value = json.dumps(parsed_value, indent=2, sort_keys=True)
            is_preformatted = True
        elif isinstance(parsed_value, bool):
            display_value = "Yes" if parsed_value else "No"
        elif parsed_value is None:
            display_value = "—"
        else:
            display_value = str(parsed_value)
            if "\n" in display_value or len(display_value) > 80:
                is_preformatted = True

        display_entries.append(
            {
                "key": key,
                "value": display_value,
                "is_preformatted": is_preformatted,
            }
        )

    return display_entries

# Debug route to check user role
@admin_bp.route('/check-role')
@login_required
def check_role():
    """Debug route to check user's role"""
    # Get fresh user data from database
    user_data = db_enhanced.get_user_by_username(current_user.id)
    
    db_role = user_data.get('role') if user_data else None

    debug_info = {
        'current_user_id': current_user.id,
        'current_user_has_role_attr': hasattr(current_user, 'role'),
        'current_user_role': getattr(current_user, 'role', 'NO ROLE ATTRIBUTE'),
        'db_user_data': str(user_data) if user_data else 'NO USER DATA',
        'db_role': db_role if db_role is not None else 'NO USER DATA',
        'cache_cleared': True,
        'message': 'If roles mismatch, please log out and log back in to refresh your session.'
    }
    
    # Clear any cached user data so next request loads fresh role from DB
    cache_user_data(current_user.id)
    logger.info(
        f"Cleared cache for user {current_user.id}. "
        f"Session role: {getattr(current_user, 'role', 'NONE')}, "
        f"DB role: {db_role if db_role is not None else 'NONE'}"
    )
    
    return jsonify(debug_info)


def admin_required(f):
    """Decorator to require admin role"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash("Please log in to access this page.", "error")
            return redirect(url_for("login"))
        
        # Always revalidate role against the database to avoid stale session cache
        try:
            user_data = db_enhanced.get_user_by_username(current_user.id)
            db_role = user_data.get('role') if user_data else None
        except Exception as e:
            logger.error(f"Failed to fetch user role for {current_user.id}: {e}")
            flash("Access denied. Admin privileges required.", "error")
            return redirect(url_for("dashboard"))

        # If session role differs from DB, update the in-memory user and invalidate cache
        if hasattr(current_user, 'role') and db_role and current_user.role != db_role:
            logger.info(f"Updating session role for {current_user.id} from {current_user.role} to {db_role}")
            try:
                current_user.role = db_role
                cache_user_data(current_user.id)
            except Exception as e:
                logger.debug(f"Failed to update session role/cache for {current_user.id}: {e}")

        # Enforce admin-only access based on authoritative DB role
        if db_role != 'admin':
            session_role = getattr(current_user, 'role', 'UNKNOWN')
            logger.warning(
                f"User {current_user.id} attempted to access admin panel with role: {session_role} (db_role={db_role})"
            )
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
        recent_activity_raw = db_enhanced.get_recent_activity(limit=50)
        recent_activity = _normalize_activity_records(recent_activity_raw, timestamp_index=4)
        
        # Get cache stats
        cache_stats = get_cache().get_stats()
        
        # Get user list
        users_raw = db_enhanced.get_all_users()
        users = [_normalize_user_row(u) for u in users_raw]
        
        search_preferences = db_enhanced.get_search_preferences(limit=40)
        recent_saved_searches = db_enhanced.get_recent_saved_searches(limit=40)
        
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
                             users=users[:20],  # Show first 20 users
                             search_preferences=search_preferences,
                             saved_searches=recent_saved_searches)
    
    except Exception as e:
        logger.error(f"Error loading admin dashboard: {e}")
        flash("Error loading dashboard", "error")
        return redirect(url_for("dashboard"))


@admin_bp.route('/users')
@login_required
@admin_required
def users():
    """User management page"""
    try:
        all_users_raw = db_enhanced.get_all_users()
        all_users = [_normalize_user_row(u) for u in all_users_raw]
        return render_template('admin/users.html', users=all_users)
    except Exception as e:
        logger.error(f"Error loading users page: {e}")
        flash("Error loading users", "error")
        return redirect(url_for("admin.dashboard"))


@admin_bp.route('/emails')
@login_required
@admin_required
def email_directory():
    """Email directory for newsletters and announcements."""
    try:
        raw_rows = db_enhanced.get_all_user_emails()
        emails = [
            {
                'username': row[0],
                'email': row[1],
                'verified': bool(row[2]),
                'email_notifications': bool(row[3]),
                'active': bool(row[4]),
                'created_at': _format_timestamp(row[5], mode='date'),
            }
            for row in raw_rows
        ]

        stats = {
            'total': len(emails),
            'verified': sum(1 for entry in emails if entry['verified']),
            'subscribed': sum(1 for entry in emails if entry['email_notifications']),
            'active': sum(1 for entry in emails if entry['active']),
        }

        return render_template('admin/emails.html', emails=emails, stats=stats)
    except Exception as e:
        logger.error(f"Error loading email directory: {e}")
        flash("Error loading email directory", "error")
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
        activity_raw = db_enhanced.get_user_activity(username, limit=100)
        activity = _normalize_activity_records(activity_raw, timestamp_index=3)
        
        # Get user settings
        settings = db_enhanced.get_settings(username)
        settings_items = _format_settings_for_display(settings)

        # Get subscription details
        subscription_raw = db_enhanced.get_user_subscription(username)
        subscription = _format_subscription_record(subscription_raw)

        subscription_history = db_enhanced.get_subscription_history(username, limit=50)
        for event in subscription_history:
            if event.get('created_at'):
                event['created_at'] = _format_timestamp(event['created_at'], mode='datetime_minutes')
        
        # Get user listings count
        listing_count = db_enhanced.get_listing_count(user_id=username)
        
        user_data = {
            'username': user.get('username'),
            'email': user.get('email'),
            'role': user.get('role'),
            'active': user.get('active'),
            'created_at': _format_timestamp(user.get('created_at'), mode='datetime_minutes'),
            'last_login': _format_timestamp(user.get('last_login'), mode='datetime_minutes'),
            'login_count': user.get('login_count'),
            'listing_count': listing_count,
            'subscription_tier': subscription.get('tier', 'free'),
            'subscription_status': subscription.get('status', 'inactive'),
        }
        
        return render_template('admin/user_detail.html', 
                             user=user_data, 
                             activity=activity,
                             settings=settings,
                             settings_items=settings_items,
                             subscription=subscription,
                             subscription_history=subscription_history)
    
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
        # Invalidate cached user data so role change takes effect immediately
        try:
            cache_user_data(username)
        except Exception as e:
            logger.debug(f"Failed to invalidate cache for {username} after role update: {e}")
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
        
        recent_activity_raw = db_enhanced.get_recent_activity(limit=limit)
        recent_activity = _normalize_activity_records(recent_activity_raw, timestamp_index=4)
        
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


@admin_bp.route('/security/clear-honeypot-ip/<ip>', methods=['POST'])
@login_required
@admin_required
def clear_honeypot_ip(ip):
    """Clear a specific IP from honeypot blocked list"""
    try:
        from honeypot_routes import honeypot_manager
        if honeypot_manager.clear_honeypot_ip(ip):
            db_enhanced.log_user_activity(
                current_user.id,
                'clear_honeypot_ip',
                f"Cleared honeypot flag for IP: {ip}",
                request.remote_addr,
                request.headers.get('User-Agent')
            )
            flash(f"Cleared honeypot flag for IP {ip}", "success")
        else:
            flash(f"IP {ip} was not in honeypot list", "error")
        
        return redirect(url_for("admin.security_monitoring"))
    
    except Exception as e:
        logger.error(f"Error clearing honeypot IP: {e}")
        flash("Error clearing honeypot IP", "error")
        return redirect(url_for("admin.security_monitoring"))


@admin_bp.route('/security/clear-all-honeypot-ips', methods=['POST'])
@login_required
@admin_required
def clear_all_honeypot_ips():
    """Clear all honeypot-flagged IPs"""
    try:
        from honeypot_routes import honeypot_manager
        count = honeypot_manager.clear_all_honeypot_ips()
        
        db_enhanced.log_user_activity(
            current_user.id,
            'clear_all_honeypot_ips',
            f"Cleared all honeypot flags ({count} IPs)",
            request.remote_addr,
            request.headers.get('User-Agent')
        )
        
        flash(f"Cleared honeypot flags for {count} IPs", "success")
        return redirect(url_for("admin.security_monitoring"))
    
    except Exception as e:
        logger.error(f"Error clearing all honeypot IPs: {e}")
        flash("Error clearing honeypot IPs", "error")
        return redirect(url_for("admin.security_monitoring"))


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
        raw_subscriptions = db_enhanced.get_all_subscriptions()
        all_subscriptions = [_format_subscription_record(sub) for sub in raw_subscriptions]
        
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
        cache_set(f"settings:{username}", None, ttl=0)
        
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


@admin_bp.route('/user/<username>/upgrade-1-month', methods=['POST'])
@login_required
@admin_required
def upgrade_user_1_month(username):
    """Grant a user 1 month of premium subscription (admin only)"""
    try:
        tier = request.form.get('tier', 'standard')
        
        # Validate tier
        if tier not in ['standard', 'pro']:
            flash("Invalid subscription tier for upgrade", "error")
            return redirect(url_for('admin.user_detail', username=username))
        
        # Calculate period dates (1 month from now)
        now = datetime.now()
        period_end = now + timedelta(days=30)
        
        # Update subscription with 1 month period
        db_enhanced.create_or_update_subscription(
            username=username,
            tier=tier,
            status='active',
            current_period_start=now,
            current_period_end=period_end,
            cancel_at_period_end=True  # Won't auto-renew since it's a manual grant
        )
        cache_set(f"settings:{username}", None, ttl=0)
        
        # Log the subscription event
        db_enhanced.log_subscription_event(
            username=username,
            tier=tier,
            action='admin_grant_1_month',
            details=f'1-month {tier} subscription granted by admin: {current_user.id}. Expires: {period_end.strftime("%Y-%m-%d %H:%M")}'
        )
        
        # Log admin activity
        db_enhanced.log_user_activity(
            current_user.id,
            'admin_grant_subscription',
            f'Granted 1-month {tier} subscription to {username} (expires {period_end.strftime("%Y-%m-%d")})',
            request.remote_addr,
            request.headers.get('User-Agent')
        )
        
        flash(f"Granted 1 month of {tier.upper()} subscription to {username} (expires {period_end.strftime('%Y-%m-%d')})", "success")
        return redirect(url_for('admin.user_detail', username=username))
    
    except Exception as e:
        logger.error(f"Error granting 1-month subscription: {e}")
        flash("Error granting subscription", "error")
        return redirect(url_for('admin.user_detail', username=username))


# ======================
# SCRAPER HEALTH MONITORING
# ======================

@admin_bp.route('/scrapers')
@login_required
@admin_required
def scrapers_health():
    """Scraper health monitoring page"""
    try:
        if not get_metrics_summary:
            flash("Scraper metrics module not available", "error")
            return redirect(url_for('admin.dashboard'))
        
        # Get metrics for all scrapers
        scrapers = ['craigslist', 'ebay', 'facebook', 'ksl', 'mercari', 'poshmark']
        scraper_data = []
        
        for scraper_name in scrapers:
            try:
                metrics_raw = get_metrics_summary(scraper_name, hours=24)
                metrics = _format_scraper_metrics(metrics_raw)
                status = get_performance_status(scraper_name)
                
                scraper_data.append({
                    'name': scraper_name,
                    'status': status,
                    'metrics': metrics,
                    'last_run_display': metrics.get('last_run_display')
                })
            except Exception as e:
                logger.error(f"Error getting metrics for {scraper_name}: {e}")
                scraper_data.append({
                    'name': scraper_name,
                    'status': 'unknown',
                    'metrics': None,
                    'last_run_display': None
                })
        
        return render_template('admin/scrapers.html', scrapers=scraper_data)
    
    except Exception as e:
        logger.error(f"Error loading scraper health page: {e}")
        flash("Error loading scraper health", "error")
        return redirect(url_for('admin.dashboard'))


@admin_bp.route('/api/scraper-health')
@login_required
@admin_required
def api_scraper_health():
    """Get scraper health data (API)"""
    try:
        if not get_metrics_summary:
            return jsonify({'error': 'Metrics module not available'}), 500
        
        scrapers = ['craigslist', 'ebay', 'facebook', 'ksl', 'mercari', 'poshmark']
        health_data = {}
        
        for scraper_name in scrapers:
            try:
                metrics_raw = get_metrics_summary(scraper_name, hours=24)
                metrics = _format_scraper_metrics(metrics_raw)
                status = get_performance_status(scraper_name)
                
                health_data[scraper_name] = {
                    'status': status,
                    'total_runs': metrics['total_runs'] if metrics else 0,
                    'success_rate': metrics['success_rate'] if metrics else 0,
                    'total_listings': metrics['total_listings'] if metrics else 0,
                    'avg_duration': metrics['avg_duration'] if metrics else 0,
                    'last_run': metrics.get('last_run') if metrics else None,
                    'last_run_display': metrics.get('last_run_display') if metrics else None
                }
            except Exception as e:
                logger.error(f"Error getting health for {scraper_name}: {e}")
                health_data[scraper_name] = {
                    'status': 'error',
                    'error': str(e)
                }
        
        webdriver_diag = get_chrome_diagnostics()
        webdriver_diag['status'] = (
            'ok' if webdriver_diag.get('binary_found') and webdriver_diag.get('chromedriver_found') else 'warning'
        )
        health_data['webdriver'] = webdriver_diag

        return jsonify(health_data)
    
    except Exception as e:
        logger.error(f"Error getting scraper health: {e}")
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/api/scraper-details/<scraper_name>')
@login_required
@admin_required
def api_scraper_details(scraper_name):
    """Get detailed metrics for a specific scraper"""
    try:
        if not get_metrics_summary or not get_recent_runs:
            return jsonify({'error': 'Metrics module not available'}), 500
        
        # Get metrics for different time periods
        metrics_24h_raw = get_metrics_summary(scraper_name, hours=24)
        metrics_1h_raw = get_metrics_summary(scraper_name, hours=1)
        metrics_24h = _format_scraper_metrics(metrics_24h_raw)
        metrics_1h = _format_scraper_metrics(metrics_1h_raw)
        recent_runs = get_recent_runs(scraper_name, limit=20)
        status = get_performance_status(scraper_name)
        
        return jsonify({
            'scraper': scraper_name,
            'status': status,
            'metrics_24h': metrics_24h,
            'metrics_1h': metrics_1h,
            'recent_runs': recent_runs
        })
    
    except Exception as e:
        logger.error(f"Error getting details for {scraper_name}: {e}")
        return jsonify({'error': str(e)}), 500


# ======================
# CRM MANAGEMENT
# ======================

@admin_bp.route('/crm')
@login_required
@admin_required
def crm():
    """CRM - Customer Relationship Management dashboard"""
    try:
        # Get search/filter parameters
        search_query = request.args.get('search', '').strip()
        plan_filter = request.args.get('plan', '')
        sort_by = request.args.get('sort', 'created_at')
        sort_order = request.args.get('order', 'desc')
        
        # Get all CRM contacts
        contacts = db_enhanced.get_crm_contacts(limit=1000, offset=0)
        
        # Apply filters
        if search_query:
            search_lower = search_query.lower()
            contacts = [
                c for c in contacts
                if (c.get('email', '').lower().find(search_lower) >= 0 or
                    c.get('username', '').lower().find(search_lower) >= 0 or
                    (c.get('first_name', '') or '').lower().find(search_lower) >= 0 or
                    (c.get('last_name', '') or '').lower().find(search_lower) >= 0)
            ]
        
        if plan_filter:
            contacts = [c for c in contacts if c.get('plan_tier') == plan_filter]
        
        # Sort
        reverse = sort_order.lower() == 'desc'
        if sort_by == 'created_at':
            contacts.sort(key=lambda x: x.get('created_at') or '', reverse=reverse)
        elif sort_by == 'email':
            contacts.sort(key=lambda x: (x.get('email') or '').lower(), reverse=reverse)
        elif sort_by == 'plan_tier':
            contacts.sort(key=lambda x: x.get('plan_tier') or '', reverse=reverse)
        elif sort_by == 'searches':
            contacts.sort(key=lambda x: x.get('searches_made', 0), reverse=reverse)
        
        # Get statistics
        stats = {
            'total': len(contacts),
            'free': sum(1 for c in contacts if c.get('plan_tier') == 'free' or not c.get('plan_tier')),
            'standard': sum(1 for c in contacts if c.get('plan_tier') == 'standard'),
            'pro': sum(1 for c in contacts if c.get('plan_tier') == 'pro'),
            'active_searches': sum(c.get('searches_made', 0) for c in contacts),
            'total_alerts': sum(c.get('alerts_created', 0) for c in contacts),
        }
        
        # Format timestamps
        for contact in contacts:
            if contact.get('created_at'):
                contact['created_at'] = _format_timestamp(contact['created_at'], mode='datetime_minutes')
            if contact.get('signup_date'):
                contact['signup_date'] = _format_timestamp(contact['signup_date'], mode='date')
            if contact.get('last_payment_at'):
                contact['last_payment_at'] = _format_timestamp(contact['last_payment_at'], mode='datetime_minutes')
        
        return render_template('admin/crm.html',
                             contacts=contacts,
                             stats=stats,
                             search_query=search_query,
                             plan_filter=plan_filter,
                             sort_by=sort_by,
                             sort_order=sort_order)
    
    except Exception as e:
        logger.error(f"Error loading CRM page: {e}")
        flash("Error loading CRM dashboard", "error")
        return redirect(url_for('admin.dashboard'))


@admin_bp.route('/crm/<path:email>')
@login_required
@admin_required
def crm_contact_detail(email):
    """CRM contact detail page"""
    try:
        # Decode URL-encoded email if needed
        from urllib.parse import unquote
        email = unquote(email)
        
        # Get CRM contact
        contact = db_enhanced.upsert_crm_contact(email)
        
        if not contact:
            flash("Contact not found", "error")
            return redirect(url_for('admin.crm'))
        
        # Get user data if username exists
        user_data = None
        if contact.get('username'):
            user_data = db_enhanced.get_user_by_username(contact['username'])
            if user_data:
                user_data['created_at'] = _format_timestamp(user_data.get('created_at'), mode='datetime_minutes')
                user_data['last_login'] = _format_timestamp(user_data.get('last_login'), mode='datetime_minutes')
        
        # Get subscription data
        subscription = None
        if contact.get('username'):
            subscription = db_enhanced.get_user_subscription(contact['username'])
            if subscription:
                subscription = _format_subscription_record(subscription)
        
        # Get subscription history
        subscription_history = []
        if contact.get('username'):
            subscription_history = db_enhanced.get_subscription_history(contact['username'], limit=50)
            for event in subscription_history:
                if event.get('created_at'):
                    event['created_at'] = _format_timestamp(event['created_at'], mode='datetime_minutes')
        
        # Get user activity
        activity = []
        if contact.get('username'):
            activity_raw = db_enhanced.get_user_activity(contact['username'], limit=100)
            activity = _normalize_activity_records(activity_raw, timestamp_index=3)
        
        # Get user listings count
        listing_count = 0
        if contact.get('username'):
            listing_count = db_enhanced.get_listing_count(user_id=contact['username'])
        
        # Get saved searches count
        saved_searches = []
        if contact.get('username'):
            saved_searches = db_enhanced.get_saved_searches(contact['username'])
        
        # Get price alerts
        price_alerts = []
        if contact.get('username'):
            price_alerts = db_enhanced.get_price_alerts(contact['username'])
        
        # Format contact timestamps
        if contact.get('created_at'):
            contact['created_at'] = _format_timestamp(contact['created_at'], mode='datetime_minutes')
        if contact.get('updated_at'):
            contact['updated_at'] = _format_timestamp(contact['updated_at'], mode='datetime_minutes')
        if contact.get('signup_date'):
            contact['signup_date'] = _format_timestamp(contact['signup_date'], mode='date')
        if contact.get('last_payment_at'):
            contact['last_payment_at'] = _format_timestamp(contact['last_payment_at'], mode='datetime_minutes')
        
        return render_template('admin/crm_detail.html',
                             contact=contact,
                             user=user_data,
                             subscription=subscription,
                             subscription_history=subscription_history,
                             activity=activity,
                             listing_count=listing_count,
                             saved_searches=saved_searches,
                             price_alerts=price_alerts)
    
    except Exception as e:
        logger.error(f"Error loading CRM contact detail: {e}")
        flash("Error loading contact details", "error")
        return redirect(url_for('admin.crm'))


@admin_bp.route('/crm/<path:email>/update', methods=['POST'])
@login_required
@admin_required
def crm_update_contact(email):
    """Update CRM contact information"""
    try:
        # Decode URL-encoded email if needed
        from urllib.parse import unquote
        email = unquote(email)
        first_name = request.form.get('first_name', '').strip() or None
        last_name = request.form.get('last_name', '').strip() or None
        phone = request.form.get('phone', '').strip() or None
        zip_code = request.form.get('zip_code', '').strip() or None
        
        contact = db_enhanced.update_crm_contact(
            email,
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            zip_code=zip_code
        )
        
        if not contact:
            flash("Contact not found", "error")
            return redirect(url_for('admin.crm'))
        
        db_enhanced.log_user_activity(
            current_user.id,
            'crm_update_contact',
            f"Updated CRM contact: {email}",
            request.remote_addr,
            request.headers.get('User-Agent')
        )
        
        flash("Contact updated successfully", "success")
        return redirect(url_for('admin.crm_contact_detail', email=email))
    
    except Exception as e:
        logger.error(f"Error updating CRM contact: {e}")
        flash("Error updating contact", "error")
        return redirect(url_for('admin.crm_contact_detail', email=email))


# ======================
# VISITOR ANALYTICS
# ======================

@admin_bp.route('/visitors')
@login_required
@admin_required
def visitor_analytics():
    """Landing page visitor analytics dashboard"""
    try:
        hours = request.args.get('hours', 72, type=int)
        if hours not in [24, 48, 72, 168]:  # 1, 2, 3, or 7 days
            hours = 72
        
        # Get visitor statistics
        stats = db_enhanced.get_visitor_stats(hours=hours)
        
        # Get visitor sessions
        sessions = db_enhanced.get_visitor_sessions(hours=hours, limit=500)
        
        # Format timestamps for display
        for session in sessions:
            if session.get('started_at'):
                session['started_at_display'] = _format_timestamp(session['started_at'], mode='datetime_minutes')
            if session.get('last_heartbeat'):
                session['last_heartbeat_display'] = _format_timestamp(session['last_heartbeat'], mode='datetime_minutes')
            # Format duration
            duration_secs = session.get('duration_seconds', 0)
            if duration_secs >= 3600:
                session['duration_display'] = f"{duration_secs // 3600}h {(duration_secs % 3600) // 60}m"
            elif duration_secs >= 60:
                session['duration_display'] = f"{duration_secs // 60}m {duration_secs % 60}s"
            else:
                session['duration_display'] = f"{duration_secs}s"
        
        # Get hourly data for chart
        hourly_data = db_enhanced.get_visitor_hourly_counts(hours=hours)
        
        return render_template('admin/visitors.html',
                             stats=stats,
                             sessions=sessions,
                             hourly_data=json.dumps(hourly_data),
                             selected_hours=hours)
    
    except Exception as e:
        logger.error(f"Error loading visitor analytics: {e}")
        flash("Error loading visitor analytics", "error")
        return redirect(url_for('admin.dashboard'))


@admin_bp.route('/api/visitor-stats')
@login_required
@admin_required
def api_visitor_stats():
    """Get visitor statistics (API)"""
    try:
        hours = request.args.get('hours', 72, type=int)
        stats = db_enhanced.get_visitor_stats(hours=hours)
        hourly_data = db_enhanced.get_visitor_hourly_counts(hours=hours)
        
        return jsonify({
            'stats': stats,
            'hourly_data': hourly_data
        })
    
    except Exception as e:
        logger.error(f"Error getting visitor stats: {e}")
        return jsonify({'error': str(e)}), 500