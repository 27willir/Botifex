from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, abort, g
from flask_wtf.csrf import CSRFProtect
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_session import Session  # type: ignore[import]
from pathlib import Path
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from collections import namedtuple
from scraper_thread import (
    start_facebook, stop_facebook, is_facebook_running,
    start_craigslist, stop_craigslist, is_craigslist_running,
    start_ksl, stop_ksl, is_ksl_running,
    start_ebay, stop_ebay, is_ebay_running,
    start_poshmark, stop_poshmark, is_poshmark_running,
    start_mercari, stop_mercari, is_mercari_running,
    get_scraper_health
)
# Import enhanced database module
import db_enhanced
from security import SecurityConfig
from error_handling import ErrorHandler, log_errors, safe_execute, DatabaseError
from error_recovery import start_error_recovery, stop_error_recovery, handle_error, get_system_status
from utils import logger, get_chrome_diagnostics
from observability import log_event, log_alert, log_http_request, log_http_response
# Import new modules
from rate_limiter import rate_limit, add_rate_limit_headers
from cache_manager import cache_get, cache_set, cache_clear, cache_user_data, get_cache
from admin_panel import admin_bp
from security_middleware import security_before_request, security_after_request, get_security_stats
from honeypot_routes import create_honeypot_routes, get_honeypot_stats
from typing import Any, Dict, List, Optional, Sequence, Tuple
# Import subscription modules
from subscriptions import SubscriptionManager, StripeManager, get_all_tiers, format_price
from subscription_middleware import (
    require_subscription_tier, require_feature, check_keyword_limit, 
    check_refresh_interval, check_platform_access, add_subscription_context
)
from email_verification import (
    generate_verification_token, generate_password_reset_token,
    send_verification_email, send_password_reset_email, is_email_configured
)
from notifications import send_welcome_email
import json
import os
import secrets
import time
import jwt
from dotenv import load_dotenv
from datetime import datetime, timedelta
from io import StringIO
import csv

# Define named tuples for database row access
UserRow = namedtuple(
    'UserRow',
    [
        'id',
        'username',
        'email',
        'password',
        'role',
        'verified',
        'active',
        'created_at',
        'last_login',
        'login_count',
        'phone_number',
        'email_notifications',
        'sms_notifications',
        'tos_agreed',
        'tos_agreed_at',
    ],
)
ListingRow = namedtuple('ListingRow', ['id', 'title', 'price', 'link', 'image_url', 'source', 'created_at'])


def _user_data_to_row(user_data: Any) -> Optional[UserRow]:
    """
    Normalize raw database user data (dict, sequence, or UserRow) into a UserRow.
    Returns None when the structure cannot be coerced safely.
    """
    if not user_data:
        return None

    if isinstance(user_data, UserRow):
        return user_data

    if isinstance(user_data, dict):
        # Populate every expected field; missing keys default to None.
        return UserRow(**{field: user_data.get(field) for field in UserRow._fields})

    try:
        sequence = list(user_data)
    except TypeError as exc:
        logger.error(f"Unable to interpret user data structure ({type(user_data)}): {exc}")
        return None

    field_count = len(UserRow._fields)
    if len(sequence) < field_count:
        sequence.extend([None] * (field_count - len(sequence)))
    elif len(sequence) > field_count:
        logger.debug(
            "Received user data sequence with %d entries; truncating to %d fields",
            len(sequence),
            field_count,
        )
        sequence = sequence[:field_count]

    try:
        return UserRow._make(sequence)
    except (TypeError, ValueError) as exc:
        logger.error(f"Failed to normalize user data sequence: {exc}")
        return None

# Load environment variables
load_dotenv()

app = Flask(__name__)
# Trust proxy headers for real client IP and scheme
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
app.secret_key = SecurityConfig.get_secret_key()

# Configure Flask-Session for server-side sessions (works across multiple workers)
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = './flask_session'
app.config['SESSION_PERMANENT'] = True
app.config['SESSION_USE_SIGNER'] = True
app.config['SESSION_KEY_PREFIX'] = 'superbot_session:'
Session(app)

# Real-time configuration
app.config['REALTIME_REDIS_URL'] = os.getenv('REALTIME_REDIS_URL') or os.getenv('REDIS_URL')
app.config['REALTIME_JWT_SECRET'] = SecurityConfig.get_realtime_jwt_secret()
app.config['REALTIME_JWT_TTL_SECONDS'] = int(os.getenv('REALTIME_JWT_TTL_SECONDS', '300'))
app.config['REALTIME_JWT_AUDIENCE'] = os.getenv('REALTIME_JWT_AUDIENCE', 'superbot-realtime')
app.config['REALTIME_JWT_ISSUER'] = os.getenv('REALTIME_JWT_ISSUER', 'superbot')

# Profile media configuration
app.config.setdefault('MAX_CONTENT_LENGTH', 8 * 1024 * 1024)  # 8 MB upload limit
PROFILE_MEDIA_ROOT = Path(app.root_path) / 'static' / 'uploads' / 'profiles'
PROFILE_MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
ALLOWED_PROFILE_MEDIA_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

# Initialize WebSocket support
from websocket_manager import (
    init_socketio,
    broadcast_dm_message,
    broadcast_dm_reaction,
    broadcast_dm_read_receipt,
    reserve_channel_message_slot,
    SlowModeViolation,
    get_realtime_health,
)
socketio = init_socketio(app)

DM_QUICK_REPLY_TEMPLATES = [
    {
        "template_key": "interested",
        "label": "Interested!",
        "body": "Hey! I'm interested in this.",
    },
    {
        "template_key": "available",
        "label": "Is this available?",
        "body": "Hi there! Is this still available?",
    },
    {
        "template_key": "thanks",
        "label": "Thanks!",
        "body": "Thanks for the update — appreciate it!",
    },
]

# Initialize Swagger documentation
from swagger_config import init_swagger
swagger = init_swagger(app)

# Configure session security
SecurityConfig.setup_session_security(app)

# Initialize CSRF protection
csrf = CSRFProtect(app)

# Register admin blueprint
app.register_blueprint(admin_bp)

# Create honeypot routes to catch malicious bots
create_honeypot_routes(app)

# Initialize production database on startup with timeout protection
def init_production_database():
    """Initialize production database with all required tables"""
    try:
        # Use optimized startup to reduce timeout issues
        from scripts.optimize_startup import optimize_database
        optimize_database()
        logger.info("Production database initialization completed")
    except Exception as e:
        logger.error(f"Failed to initialize production database: {e}")
        # Fallback to basic initialization
        try:
            db_enhanced.init_db()
            logger.info("Fallback database initialization completed")
        except Exception as fallback_error:
            logger.error(f"Fallback database initialization failed: {fallback_error}")

# Run database initialization with timeout protection
init_production_database()

# Security middleware - must be first
@app.before_request
def before_request():
    return security_before_request()


@app.before_request
def observability_request_context():
    if request.path.startswith("/static") or request.path in {"/favicon.ico", "/robots.txt"}:
        g.skip_observability = True
        return None

    g.skip_observability = False
    g.request_start_time = time.time()
    g.request_id = request.headers.get("X-Request-ID") or secrets.token_hex(8)
    user_agent = request.headers.get("User-Agent")
    current_username = current_user.id if current_user.is_authenticated else None
    log_http_request(
        request_id=g.request_id,
        method=request.method,
        path=request.path,
        query=request.query_string.decode("utf-8", errors="ignore") if request.query_string else None,
        remote_addr=request.headers.get("X-Forwarded-For", request.remote_addr),
        user=current_username,
        user_agent=user_agent,
    )

# Add rate limit headers to all responses
@app.after_request
def after_request(response):
    response = add_rate_limit_headers(response)
    response = security_after_request(response)

    if getattr(g, "skip_observability", False):
        return response

    try:
        if getattr(g, "request_id", None):
            response.headers.setdefault("X-Request-ID", g.request_id)
            duration_ms = int((time.time() - g.request_start_time) * 1000)
            route_rule = request.url_rule.rule if request.url_rule else None
            current_username = current_user.id if current_user.is_authenticated else None
            log_http_response(
                request_id=g.request_id,
                method=request.method,
                path=request.path,
                route=route_rule,
                status_code=response.status_code,
                duration_ms=duration_ms,
                content_length=response.calculate_content_length(),
                user=current_username,
            )
    except Exception as obs_exc:
        logger.debug(f"Observability after_request failed: {obs_exc}")
    return response


@app.teardown_request
def observability_teardown(exc):
    if exc is None or getattr(g, "skip_observability", False):
        return
    request_id = getattr(g, "request_id", None)
    current_username = current_user.id if current_user.is_authenticated else None
    log_alert(
        "http.request.error",
        str(exc),
        severity="error",
        request_id=request_id,
        method=request.method if request else None,
        path=request.path if request else None,
        user=current_username,
    )

# Add subscription context to all templates
@app.context_processor
def inject_subscription_context():
    """Inject subscription information into all templates"""
    return add_subscription_context()

# ======================
# FLASK-LOGIN SETUP
# ======================
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

class User(UserMixin):
    def __init__(self, username, password_hash, role='user'):
        self.id = username
        self.password_hash = password_hash
        self.role = role

def check_suspicious_login_activity(username, ip_address):
    """Check for suspicious login patterns"""
    try:
        # Get recent failed login attempts for this username or IP
        recent_attempts = db_enhanced.get_recent_failed_logins(username, ip_address, hours=1)
        
        if len(recent_attempts) >= 5:  # 5 failed attempts in 1 hour
            logger.warning(f"Suspicious login activity detected: {len(recent_attempts)} failed attempts for {username} from {ip_address}")
            return True
        return False
    except Exception as e:
        logger.error(f"Error checking suspicious login activity: {e}")
        return False

@log_errors()
def create_user(username, password, email):
    """Create a new user using database with security validation"""
    try:
        # Validate username
        is_valid_username, username_error = SecurityConfig.validate_username(username)
        if not is_valid_username:
            logger.warning(f"Invalid username during registration: {username_error}")
            return False, username_error
        
        # Validate email
        is_valid_email, email_error = SecurityConfig.validate_email(email)
        if not is_valid_email:
            logger.warning(f"Invalid email during registration: {email_error}")
            return False, email_error
        
        # Validate password strength
        is_valid_password, password_error = SecurityConfig.validate_password(password)
        if not is_valid_password:
            logger.warning(f"Weak password during registration: {password_error}")
            return False, password_error
        
        # Sanitize inputs
        username = SecurityConfig.sanitize_input(username)
        email = SecurityConfig.sanitize_input(email)
        
        # Check if user already exists
        existing_user = ErrorHandler.handle_database_error(db_enhanced.get_user_by_username, username)
        if existing_user:
            logger.warning(f"Registration attempt with existing username: {username}")
            return False, "Username already exists"
        
        # Check if email already exists
        existing_email = ErrorHandler.handle_database_error(db_enhanced.get_user_by_email, email)
        if existing_email:
            logger.warning(f"Registration attempt with existing email: {email}")
            return False, "Email already registered"
        
        # Hash password securely
        hashed = SecurityConfig.hash_password(password)
        success = ErrorHandler.handle_database_error(db_enhanced.create_user_db, username, email, hashed)
        if success:
            logger.info(f"User created successfully: {username}")
            # Log the registration
            db_enhanced.log_user_activity(username, 'register', 'User registered', request.remote_addr, request.headers.get('User-Agent'))
            return True, "User created successfully"
        else:
            logger.error(f"Failed to create user in database: {username}")
            return False, "Failed to create user"
    
    except Exception as e:
        logger.error(f"Unexpected error during user creation: {e}")
        return False, "An unexpected error occurred during registration"

@login_manager.user_loader
@log_errors()
def load_user(user_id):
    try:
        # Try cache first
        cache_key = f"user:{user_id}"
        cached_user = cache_get(cache_key)
        if cached_user:
            return cached_user
        
        user_data = ErrorHandler.handle_database_error(db_enhanced.get_user_by_username, user_id)
        user_row = _user_data_to_row(user_data)
        if user_row:
            user = User(user_row.username, user_row.password, user_row.role)
            # Cache user object for 5 minutes
            cache_set(cache_key, user, ttl=300)
            return user
        if user_data:
            logger.error(
                "Invalid user data structure for %s: type=%s keys=%s",
                user_id,
                type(user_data),
                list(user_data.keys()) if isinstance(user_data, dict) else None,
            )
        return None
    except Exception as e:
        logger.error(f"Error loading user {user_id}: {e}")
        return None


# ======================
# SETTINGS MANAGEMENT
# ======================

def _get_subscription_interval_seconds(tier):
    """Return refresh interval in seconds for a subscription tier."""
    try:
        interval_seconds = SubscriptionManager.get_refresh_interval(tier)
        return max(1, interval_seconds)
    except Exception as e:
        logger.warning(f"Failed to resolve interval for tier {tier}: {e}")
        return 60


def _apply_subscription_interval(settings):
    """
    Ensure the settings dict reflects the correct interval for the current user's subscription.
    Returns a new dict instance to avoid mutating cached references unexpectedly.
    """
    settings = dict(settings)
    
    try:
        if getattr(current_user, "is_authenticated", False):
            subscription = db_enhanced.get_user_subscription(current_user.id)
            tier = subscription.get('tier', 'free')
        else:
            tier = 'free'
        
        settings['interval'] = str(_get_subscription_interval_seconds(tier))
    except Exception as e:
        logger.warning(f"Failed to apply subscription interval to settings: {e}")
        settings.setdefault('interval', '60')
    
    return settings


@log_errors()
def get_user_settings():
    """Get settings for the current user from database with caching"""
    try:
        if not current_user.is_authenticated:
            logger.debug("Getting default settings for unauthenticated user")
            return get_default_settings()
        
        cache_key = f"settings:{current_user.id}"
        cached_settings = cache_get(cache_key)
        if cached_settings:
            settings = _apply_subscription_interval(cached_settings)
            cache_set(cache_key, settings, ttl=300)
            return settings
        
        settings = ErrorHandler.handle_database_error(db_enhanced.get_settings, current_user.id)
        
        default_settings = get_default_settings()
        for key, value in default_settings.items():
            if key not in settings:
                settings[key] = value
                logger.debug(f"Using default value for missing setting: {key}")
        
        settings = _apply_subscription_interval(settings)
        
        cache_set(cache_key, settings, ttl=300)
        return settings
    except Exception as e:
        logger.error(f"Error getting user settings: {e}")
        return get_default_settings()

def get_default_settings():
    """Get default settings"""
    return {
        "keywords": "Firebird,Camaro,Corvette",
        "min_price": "1000",
        "max_price": "30000",
        "interval": str(_get_subscription_interval_seconds('free')),
        "location": "boise",
        "radius": "50"
    }

@log_errors()
def update_user_setting(key, value):
    """Update a setting for the current user"""
    try:
        if current_user.is_authenticated:
            ErrorHandler.handle_database_error(db_enhanced.update_setting, key, value, current_user.id)
            # Invalidate cache
            cache_key = f"settings:{current_user.id}"
            cache_set(cache_key, None, ttl=0)
            logger.debug(f"Updated setting {key} for user {current_user.id}")
        else:
            # For unauthenticated users, update global settings
            ErrorHandler.handle_database_error(db_enhanced.update_setting, key, value, None)
            logger.debug(f"Updated global setting {key}")
    except Exception as e:
        logger.error(f"Error updating setting {key}: {e}")
        raise

# ======================
# LISTINGS STORAGE
# ======================

def get_listings_from_db(limit=200):
    """Get listings from database with caching"""
    user_id = current_user.id if current_user.is_authenticated else None
    cache_key = f"listings:{user_id if user_id else 'global'}:{limit}"
    cached_listings = cache_get(cache_key)
    if cached_listings:
        return cached_listings
    
    listings = db_enhanced.get_listings(limit, user_id)
    for item in listings or []:
        if item.get('premium_placement'):
            try:
                db_enhanced.increment_listing_premium_impression(item['id'])
            except Exception:
                logger.debug("Failed to log premium impression for listing %s", item.get('id'))
    # Cache for 2 minutes
    cache_set(cache_key, listings, ttl=120)
    return listings


def _bounded_int(value, default, *, minimum=None, maximum=None):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    if minimum is not None and number < minimum:
        number = minimum
    if maximum is not None and number > maximum:
        number = maximum
    return number


def _server_moderation_permissions(server: Dict[str, Any], username: str) -> Tuple[bool, Dict[str, Any], Dict[str, Any]]:
    membership = server.get("viewer_membership") or {}
    permissions = db_enhanced.get_user_server_permissions(server["id"], username)
    role_name = (membership.get("role_name") or "").lower()
    is_owner = role_name == "owner"
    can_moderate = bool(
        is_owner
        or permissions.get("manage_server")
        or permissions.get("moderate_members")
        or permissions.get("ban_members")
    )
    return can_moderate, membership, permissions


def _coerce_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if value in (None, ""):
        return None
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return None
        if candidate.endswith("Z"):
            candidate = candidate[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
                try:
                    return datetime.strptime(value, fmt)
                except ValueError:
                    continue
    return None


def _group_notifications_by_day(notifications: Sequence[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    grouped = {"today": [], "earlier": []}
    today = datetime.now().date()
    for notification in notifications:
        created = _coerce_datetime(notification.get("created_at"))
        if created and created.date() == today:
            grouped["today"].append(notification)
        else:
            grouped["earlier"].append(notification)
    return grouped

# ======================
# ROUTES
# ======================
@app.route("/login", methods=["GET", "POST"])
@rate_limit('login', max_requests=5, window_minutes=5)
@log_errors()
def login():
    if request.method == "POST":
        try:
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            
            # Fast-path validation
            if not username or not password:
                logger.warning("Login attempt with missing credentials")
                flash("Username and password are required", "error")
                return render_template("login.html")
            
            # Sanitize username input
            username = SecurityConfig.sanitize_input(username)
            
            # Fast-path blocking for suspicious activity
            if check_suspicious_login_activity(username, request.remote_addr):
                logger.warning(f"Blocking suspicious login attempt for {username} from {request.remote_addr}")
                flash("Too many failed login attempts. Please try again later.", "error")
                return render_template("login.html")
            
            # Single database call to get user data
            user_data = ErrorHandler.handle_database_error(db_enhanced.get_user_by_username, username)
            user_row = _user_data_to_row(user_data)
            if user_data and not user_row:
                logger.error(
                    "Login attempt encountered invalid user data structure for %s: type=%s keys=%s",
                    username,
                    type(user_data),
                    list(user_data.keys()) if isinstance(user_data, dict) else None,
                )
                flash("Database error. Please contact administrator.", "error")
                return render_template("login.html")
            if user_row:
                account_username = user_row.username or username
                password_hash = user_row.password
                if not password_hash:
                    logger.error(f"Password hash missing for user record: {account_username}")
                    flash("Database error. Please contact administrator.", "error")
                    return render_template("login.html")

                user_is_active = bool(user_row.active if user_row.active is not None else True)
                if not user_is_active:
                    logger.warning(f"Login attempt for deactivated user: {account_username}")
                    flash("Account deactivated. Please contact administrator.", "error")
                    return render_template("login.html")
                
                if SecurityConfig.verify_password(password_hash, password):
                    # Check if email is verified (only if email verification is configured)
                    if is_email_configured() and not bool(user_row.verified):
                        logger.warning(f"Login attempt for unverified user: {account_username}")
                        flash("Please verify your email address before logging in. Check your inbox for the verification link.", "warning")
                        # Show option to resend verification email
                        return render_template("login.html", unverified_user=account_username)
                    
                    user_role = user_row.role or "user"
                    user = User(account_username, password_hash, user_role)
                    login_user(user, remember=True)
                    session.permanent = True
                    
                    # Batch database operations to reduce timeouts
                    try:
                        # Update login tracking and log activity in a single transaction
                        db_enhanced.update_user_login_and_log_activity(
                            account_username, 
                            request.remote_addr, 
                            request.headers.get('User-Agent')
                        )
                    except Exception as e:
                        logger.warning(f"Failed to log login activity for {account_username}: {e}")
                        # Don't fail login if logging fails
                    
                    logger.info(f"Successful login for user: {account_username}")
                    return redirect(url_for("dashboard"))
                else:
                    logger.warning(f"Invalid password for user: {account_username}")
                    # Log failed attempt asynchronously to avoid blocking
                    try:
                        db_enhanced.log_user_activity(
                            account_username, 
                            'login_failed', 
                            'Invalid password', 
                            request.remote_addr, 
                            request.headers.get('User-Agent')
                        )
                    except Exception as e:
                        logger.warning(f"Failed to log failed login for {username}: {e}")
                    flash("Invalid password", "error")
            else:
                logger.warning(f"Login attempt for non-existent user: {username}")
                # Log failed login attempt asynchronously
                try:
                    db_enhanced.log_user_activity(
                        username, 
                        'login_failed', 
                        'Non-existent user login attempt', 
                        request.remote_addr, 
                        request.headers.get('User-Agent')
                    )
                except Exception as e:
                    logger.warning(f"Failed to log non-existent user login: {e}")
                flash("Invalid username or password", "error")
            
            return render_template("login.html")
        except Exception as e:
            logger.error(f"Error during login process: {e}")
            flash("An error occurred during login. Please try again.", "error")
            return render_template("login.html")
    
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    username = current_user.id
    # Clear user cache on logout
    cache_user_data(username)
    
    db_enhanced.log_user_activity(
        username, 
        'logout', 
        'User logged out', 
        request.remote_addr, 
        request.headers.get('User-Agent')
    )
    logout_user()
    return redirect(url_for("login"))

@app.route("/refresh-session")
@login_required
def refresh_session():
    """Force refresh the user session from database"""
    username = current_user.id
    
    # Clear user cache
    cache_user_data(username)
    
    # Log them out and back in to reload user data
    logout_user()
    flash("Session refreshed. Please log in again.", "success")
    return redirect(url_for("login"))

@app.route("/health")
def health_check():
    """Health check endpoint for monitoring"""
    try:
        # Quick database connectivity check
        db_enhanced.get_user_count()

        # Check background thread status
        from security_middleware import _security_logger_running, _security_log_queue
        security_logger_status = "running" if _security_logger_running else "stopped"
        activity_logger_status = "running" if db_enhanced._activity_logger_running else "stopped"
        realtime_health = get_realtime_health()

        overall_status = "healthy"
        if realtime_health.get("status") != "ok":
            overall_status = "degraded"

        response = {
            "status": overall_status,
            "timestamp": datetime.now().isoformat(),
            "checks": {
                "database": {"status": "connected"},
                "realtime": realtime_health,
                "background_threads": {
                    "security_logger": security_logger_status,
                    "activity_logger": activity_logger_status,
                },
                "queues": {
                    "security_log_queue": _security_log_queue.qsize(),
                    "activity_log_queue": db_enhanced._activity_log_queue.qsize(),
                },
            },
        }
        log_event("health.check", status=overall_status, severity="info" if overall_status == "healthy" else "warning")
        return jsonify(response), 200
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        log_event("health.check", status="unhealthy", severity="error", error=str(e))
        return jsonify({
            "status": "unhealthy",
            "timestamp": datetime.now().isoformat(),
            "error": str(e)
        }), 500


@app.route("/readiness")
def readiness_check():
    """Readiness probe providing detailed subsystem status."""
    checks: Dict[str, Any] = {}
    ready = True
    http_status = 200
    severity = "info"
    errors: List[str] = []

    try:
        db_enhanced.get_user_count()
        checks["database"] = {"status": "ready"}
    except Exception as exc:
        ready = False
        severity = "warning"
        errors.append(str(exc))
        checks["database"] = {"status": "error", "error": str(exc)}

    realtime_health = get_realtime_health()
    checks["realtime"] = realtime_health
    if realtime_health.get("status") != "ok":
        ready = False
        severity = "warning"

    from security_middleware import _security_logger_running, _security_log_queue
    background = {
        "security_logger": {
            "status": "running" if _security_logger_running else "stopped"
        },
        "activity_logger": {
            "status": "running" if db_enhanced._activity_logger_running else "stopped"
        },
    }
    if not _security_logger_running or not db_enhanced._activity_logger_running:
        ready = False
        severity = "warning"
    checks["background_threads"] = background

    queue_sizes = {
        "security_log_queue": _security_log_queue.qsize(),
        "activity_log_queue": db_enhanced._activity_log_queue.qsize(),
    }
    checks["queues"] = queue_sizes

    status_text = "ready" if ready else "not_ready"
    if not ready:
        http_status = 503

    log_event(
        "readiness.check",
        status=status_text,
        severity=severity,
        errors=errors or None,
    )
    return jsonify({
        "status": status_text,
        "timestamp": datetime.now().isoformat(),
        "checks": checks,
    }), http_status

@app.route("/")
def landing():
    """Public landing page"""
    preview_requested = request.args.get("preview", "").lower() in {"1", "true", "yes"}
    if current_user.is_authenticated and not preview_requested:
        return redirect(url_for('dashboard'))
    return render_template("landing.html")

@app.route("/ai-automation")
def ai_automation():
    """AI automation services landing page"""
    current_year = datetime.now().year
    return render_template("ai_automation.html", current_year=current_year)

@app.route("/dashboard")
@login_required
@rate_limit('api', max_requests=60)
def dashboard():
    """Main dashboard for authenticated users"""
    user_id = current_user.id
    listings = get_listings_from_db()
    settings = get_user_settings()
    status = {
        "facebook": is_facebook_running(user_id),
        "craigslist": is_craigslist_running(user_id),
        "ksl": is_ksl_running(user_id),
        "ebay": is_ebay_running(user_id),
        "poshmark": is_poshmark_running(user_id),
        "mercari": is_mercari_running(user_id),
    }
    return render_template("index.html", listings=listings, settings=settings, status=status)

# Start/Stop routes
@app.route("/start/<site>")
@login_required
@check_platform_access()
@rate_limit('scraper', max_requests=10)
def start(site):
    user_id = current_user.id  # Get current user
    
    if site == "facebook":
        start_facebook(user_id)
    elif site == "craigslist":
        start_craigslist(user_id)
    elif site == "ksl":
        start_ksl(user_id)
    elif site == "ebay":
        start_ebay(user_id)
    elif site == "poshmark":
        # Poshmark is pro-only, check subscription
        subscription = db_enhanced.get_user_subscription(current_user.id)
        if subscription.get('tier') != 'pro' and current_user.role != 'admin':
            flash("Poshmark is only available for Pro subscribers. Please upgrade your plan.", "error")
            return redirect(url_for("subscription_plans"))
        start_poshmark(user_id)
    elif site == "mercari":
        # Mercari is pro-only, check subscription
        subscription = db_enhanced.get_user_subscription(current_user.id)
        if subscription.get('tier') != 'pro' and current_user.role != 'admin':
            flash("Mercari is only available for Pro subscribers. Please upgrade your plan.", "error")
            return redirect(url_for("subscription_plans"))
        start_mercari(user_id)
    
    db_enhanced.log_user_activity(
        current_user.id, 
        'start_scraper', 
        f'Started {site} scraper', 
        request.remote_addr, 
        request.headers.get('User-Agent')
    )
    return redirect(url_for("dashboard"))

@app.route("/stop/<site>")
@login_required
@check_platform_access()
@rate_limit('scraper', max_requests=10)
def stop(site):
    user_id = current_user.id  # Get current user
    
    if site == "facebook":
        stop_facebook(user_id)
    elif site == "craigslist":
        stop_craigslist(user_id)
    elif site == "ksl":
        stop_ksl(user_id)
    elif site == "ebay":
        stop_ebay(user_id)
    elif site == "poshmark":
        stop_poshmark(user_id)
    elif site == "mercari":
        stop_mercari(user_id)
    
    db_enhanced.log_user_activity(
        current_user.id, 
        'stop_scraper', 
        f'Stopped {site} scraper', 
        request.remote_addr, 
        request.headers.get('User-Agent')
    )
    return redirect(url_for("dashboard"))

@app.route("/start-all")
@login_required
@check_platform_access()
@rate_limit('scraper', max_requests=10)
def start_all():
    """Start all scrapers that are available in user's subscription plan"""
    try:
        user_id = current_user.id  # Get current user
        
        # Get user's subscription tier
        subscription = db_enhanced.get_user_subscription(user_id)
        tier = subscription.get('tier', 'free')
        
        # Override to 'pro' for admins
        if current_user.role == 'admin':
            tier = 'pro'
        
        # Get allowed platforms for this tier
        allowed_platforms = SubscriptionManager.get_allowed_platforms(tier)
        
        # Start only the scrapers that are allowed for this subscription
        started_platforms = []
        if 'facebook' in allowed_platforms:
            start_facebook(user_id)
            started_platforms.append('Facebook')
        if 'craigslist' in allowed_platforms:
            start_craigslist(user_id)
            started_platforms.append('Craigslist')
        if 'ksl' in allowed_platforms:
            start_ksl(user_id)
            started_platforms.append('KSL')
        if 'ebay' in allowed_platforms:
            start_ebay(user_id)
            started_platforms.append('eBay')
        if 'poshmark' in allowed_platforms:
            start_poshmark(user_id)
            started_platforms.append('Poshmark')
        if 'mercari' in allowed_platforms:
            start_mercari(user_id)
            started_platforms.append('Mercari')
        
        db_enhanced.log_user_activity(
            current_user.id, 
            'start_all_scrapers', 
            f'Started scrapers: {", ".join(started_platforms)}', 
            request.remote_addr, 
            request.headers.get('User-Agent')
        )
        
        if started_platforms:
            flash(f"Started {len(started_platforms)} scraper(s): {', '.join(started_platforms)}", "success")
        else:
            flash("No scrapers available for your subscription plan.", "warning")
    except Exception as e:
        logger.error(f"Error starting all scrapers: {e}")
        flash("Error starting some scrapers. Please check individual scrapers.", "error")
    
    return redirect(url_for("dashboard"))

@app.route("/stop-all")
@login_required
@check_platform_access()
@rate_limit('scraper', max_requests=10)
def stop_all():
    """Stop all scrapers that are available in user's subscription plan"""
    try:
        user_id = current_user.id

        # Get user's subscription tier
        subscription = db_enhanced.get_user_subscription(user_id)
        tier = subscription.get('tier', 'free')
        
        # Override to 'pro' for admins
        if current_user.role == 'admin':
            tier = 'pro'
        
        # Get allowed platforms for this tier
        allowed_platforms = SubscriptionManager.get_allowed_platforms(tier)
        
        # Stop only the scrapers that are allowed for this subscription
        stopped_platforms = []
        if 'facebook' in allowed_platforms:
            stop_facebook(user_id)
            stopped_platforms.append('Facebook')
        if 'craigslist' in allowed_platforms:
            stop_craigslist(user_id)
            stopped_platforms.append('Craigslist')
        if 'ksl' in allowed_platforms:
            stop_ksl(user_id)
            stopped_platforms.append('KSL')
        if 'ebay' in allowed_platforms:
            stop_ebay(user_id)
            stopped_platforms.append('eBay')
        if 'poshmark' in allowed_platforms:
            stop_poshmark(user_id)
            stopped_platforms.append('Poshmark')
        if 'mercari' in allowed_platforms:
            stop_mercari(user_id)
            stopped_platforms.append('Mercari')
        
        db_enhanced.log_user_activity(
            user_id, 
            'stop_all_scrapers', 
            f'Stopped scrapers: {", ".join(stopped_platforms)}', 
            request.remote_addr, 
            request.headers.get('User-Agent')
        )
        
        if stopped_platforms:
            flash(f"Stopped {len(stopped_platforms)} scraper(s): {', '.join(stopped_platforms)}", "success")
        else:
            flash("No scrapers available for your subscription plan.", "warning")
    except Exception as e:
        logger.error(f"Error stopping all scrapers: {e}")
        flash("Error stopping some scrapers. Please check individual scrapers.", "error")
    
    return redirect(url_for("dashboard"))

# Settings page
@app.route("/settings", methods=["GET", "POST"])
@login_required
@check_keyword_limit()
@check_refresh_interval()
@rate_limit('settings', max_requests=30)
def settings():
    if request.method == "GET":
        settings = get_user_settings()
        notifications = db_enhanced.get_notification_preferences(current_user.id)
        return render_template("settings.html", settings=settings, notifications=notifications)
    
    # POST method - update settings with validation
    location = SecurityConfig.sanitize_input(request.form.get("location", "Boise, ID"))
    radius = request.form.get("radius", "50")
    keywords = SecurityConfig.sanitize_input(request.form.get("keywords", ""))
    min_price = request.form.get("min_price")
    max_price = request.form.get("max_price")
    interval = request.form.get("interval")

    # Validate numeric inputs with proper error handling
    try:
        if radius:
            try:
                radius_val = int(radius)
                if radius_val < 1 or radius_val > 500:
                    logger.warning(f"Invalid radius value: {radius_val}")
                    flash("Radius must be between 1 and 500 miles", "error")
                    return redirect(url_for("settings"))
            except ValueError as e:
                logger.warning(f"Invalid radius format: {radius} - {e}")
                flash("Invalid radius value", "error")
                return redirect(url_for("settings"))

        if min_price:
            try:
                min_price_val = int(min_price)
                if min_price_val < 0:
                    logger.warning(f"Invalid minimum price: {min_price_val}")
                    flash("Minimum price cannot be negative", "error")
                    return redirect(url_for("settings"))
            except ValueError as e:
                logger.warning(f"Invalid minimum price format: {min_price} - {e}")
                flash("Invalid minimum price value", "error")
                return redirect(url_for("settings"))

        if max_price:
            try:
                max_price_val = int(max_price)
                if max_price_val < 0:
                    logger.warning(f"Invalid maximum price: {max_price_val}")
                    flash("Maximum price cannot be negative", "error")
                    return redirect(url_for("settings"))
            except ValueError as e:
                logger.warning(f"Invalid maximum price format: {max_price} - {e}")
                flash("Invalid maximum price value", "error")
                return redirect(url_for("settings"))

        if interval:
            try:
                interval_val = int(interval)
                if interval_val < 10 or interval_val > 1440:
                    logger.warning(f"Invalid interval value: {interval_val}")
                    flash("Interval must be between 10 and 1440 minutes", "error")
                    return redirect(url_for("settings"))
            except ValueError as e:
                logger.warning(f"Invalid interval format: {interval} - {e}")
                flash("Invalid interval value", "error")
                return redirect(url_for("settings"))
    except Exception as e:
        logger.error(f"Unexpected error during settings validation: {e}")
        flash("An error occurred while validating settings", "error")
        return redirect(url_for("settings"))

    # Update all settings
    update_user_setting("location", location)
    update_user_setting("radius", radius)
    if keywords:
        update_user_setting("keywords", keywords)
    if min_price:
        update_user_setting("min_price", str(int(min_price)))
    if max_price:
        update_user_setting("max_price", str(int(max_price)))
    if interval:
        update_user_setting("interval", str(int(interval)))
    
    db_enhanced.log_user_activity(
        current_user.id, 
        'update_settings', 
        'Updated user settings', 
        request.remote_addr, 
        request.headers.get('User-Agent')
    )
    
    flash("Settings updated successfully!", "success")
    return redirect(url_for("dashboard"))

@app.route("/update_settings", methods=["POST"])
@login_required
@check_keyword_limit()
@check_refresh_interval()
@rate_limit('settings', max_requests=30)
def update_settings():
    """Update settings from the index page form"""
    try:
        location = SecurityConfig.sanitize_input(request.form.get("location", "Boise, ID"))
        radius = request.form.get("radius", "50")
        keywords = SecurityConfig.sanitize_input(request.form.get("keywords", ""))
        min_price = request.form.get("min_price")
        max_price = request.form.get("max_price")
        interval = request.form.get("interval")

        # Validate numeric inputs
        try:
            if radius:
                radius_val = int(radius)
                if radius_val < 1 or radius_val > 500:
                    flash("Radius must be between 1 and 500 miles", "error")
                    return redirect(url_for("dashboard"))

            if min_price:
                min_price_val = int(min_price)
                if min_price_val < 0:
                    flash("Minimum price cannot be negative", "error")
                    return redirect(url_for("dashboard"))

            if max_price:
                max_price_val = int(max_price)
                if max_price_val < 0:
                    flash("Maximum price cannot be negative", "error")
                    return redirect(url_for("dashboard"))

            if interval:
                interval_val = int(interval)
                if interval_val < 10 or interval_val > 1440:
                    flash("Interval must be between 10 and 1440 minutes", "error")
                    return redirect(url_for("dashboard"))

        except ValueError:
            flash("Invalid numeric value", "error")
            return redirect(url_for("dashboard"))

        # Update all settings
        update_user_setting("location", location)
        update_user_setting("radius", radius)
        if keywords:
            update_user_setting("keywords", keywords)
        if min_price:
            update_user_setting("min_price", str(int(min_price)))
        if max_price:
            update_user_setting("max_price", str(int(max_price)))
        if interval:
            update_user_setting("interval", str(int(interval)))
        
        db_enhanced.log_user_activity(
            current_user.id, 
            'update_settings', 
            'Updated user settings from index', 
            request.remote_addr, 
            request.headers.get('User-Agent')
        )
        
        flash("Settings updated successfully!", "success")
        return redirect(url_for("dashboard"))

    except Exception as e:
        logger.error(f"Error updating settings: {e}")
        flash("An error occurred while updating settings", "error")
        return redirect(url_for("dashboard"))

@app.route("/update_notification_settings", methods=["POST"])
@login_required
@rate_limit('settings', max_requests=30)
def update_notification_settings():
    """Update notification preferences for the current user"""
    try:
        # Get form data
        email_notifications = request.form.get("email_notifications") == "1"
        sms_notifications = request.form.get("sms_notifications") == "1"
        phone_number = request.form.get("phone_number", "").strip()
        
        # Sanitize phone number
        if phone_number:
            phone_number = SecurityConfig.sanitize_input(phone_number)
            # Basic validation for phone number format (E.164)
            if not phone_number.startswith('+'):
                flash("Phone number must start with + and country code (e.g., +1234567890)", "error")
                return redirect(url_for("settings"))
            # Remove any non-digit characters except +
            import re
            phone_clean = re.sub(r'[^\d+]', '', phone_number)
            if len(phone_clean) < 10 or len(phone_clean) > 16:
                flash("Invalid phone number format. Use E.164 format (e.g., +1234567890)", "error")
                return redirect(url_for("settings"))
            phone_number = phone_clean
        
        # Update notification preferences
        db_enhanced.update_notification_preferences(
            username=current_user.id,
            email_notifications=email_notifications,
            sms_notifications=sms_notifications,
            phone_number=phone_number if phone_number else None
        )
        
        # Log the activity
        db_enhanced.log_user_activity(
            current_user.id,
            'update_notifications',
            'Updated notification preferences',
            request.remote_addr,
            request.headers.get('User-Agent')
        )
        
        flash("Notification preferences updated successfully!", "success")
        return redirect(url_for("settings"))
        
    except Exception as e:
        logger.error(f"Error updating notification preferences: {e}")
        flash("An error occurred while updating notification preferences", "error")
        return redirect(url_for("settings"))

@app.route("/register", methods=["GET", "POST"])
@rate_limit('register', max_requests=3, window_minutes=60)
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        email = request.form.get("email", "").strip()
        agree_terms = request.form.get("agree_terms")
        
        # Check if user agreed to terms
        if not agree_terms:
            flash("You must agree to the Terms of Service to create an account.", "error")
            return render_template("register.html", error_field="terms")
        
        success, msg = create_user(username, password, email)
        if success:
            # Record ToS agreement
            try:
                if db_enhanced.record_tos_agreement(username):
                    logger.info(f"ToS agreement recorded for user: {username}")
                else:
                    logger.warning(f"Failed to record ToS agreement for {username}: record_tos_agreement returned False")
            except Exception as e:
                logger.warning(f"Failed to record ToS agreement for {username}: {e}")
            
            # Send verification email if email is configured
            if is_email_configured():
                try:
                    token = generate_verification_token()
                    db_enhanced.create_verification_token(username, token, expiration_hours=24)
                    
                    # Get base URL from request
                    base_url = request.url_root.rstrip('/')
                    send_verification_email(email, username, token, base_url)
                    try:
                        login_url = f"{base_url}/login"
                        if not send_welcome_email(email, username, login_url=login_url):
                            logger.warning(f"Welcome email not sent to {username}")
                    except Exception as welcome_error:
                        logger.warning(f"Failed to send welcome email to {username}: {welcome_error}")
                    
                    flash("Registration successful! Please check your email to verify your account.", "success")
                except Exception as e:
                    logger.error(f"Failed to send verification email: {e}")
                    flash("Registration successful! Please log in. (Verification email could not be sent)", "warning")
            else:
                flash("Registration successful! Please log in.", "success")
            
            return redirect(url_for("login"))
        else:
            flash(msg, "error")
    
    return render_template("register.html")

@app.route("/terms")
def terms_of_service():
    """Display Terms of Service page"""
    # Check if we're coming from register page
    show_register = request.referrer and 'register' in request.referrer
    return render_template("terms.html", show_register=show_register)

@app.route("/privacy")
def privacy_policy():
    """Display Privacy Policy page"""
    return render_template("privacy.html")

@app.route("/updates")
@log_errors()
def updates_page():
    """Display website updates/changelog page"""
    import re
    from markupsafe import Markup
    
    updates = []
    changelog_path = Path(__file__).parent / "CHANGELOG.md"
    
    try:
        if changelog_path.exists():
            with open(changelog_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Parse changelog entries
            # Split by --- separator first, then look for version headers
            sections = re.split(r'\n---\n', content)
            
            for section in sections:
                # Look for version header: ## [Version] - Date
                version_match = re.search(r'## \[([^\]]+)\]\s*-\s*([^\n]+)', section)
                if not version_match:
                    continue
                
                version = version_match.group(1).strip()
                date = version_match.group(2).strip()
                
                # Get content after the header
                section_content = section[version_match.end():].strip()
                
                # Skip the header/intro section
                if "All notable changes" in section_content or not section_content:
                    continue
                
                # Parse subsections (Fixed, Added, Changed, etc.)
                formatted_content = ""
                primary_badge = None
                
                # Split by ### headers
                subsections = re.split(r'\n### ', section_content)
                
                # Handle content before first subsection
                if subsections and not subsections[0].strip().startswith('###'):
                    first_content = subsections[0].strip()
                    if first_content:
                        formatted_content += f"<p>{first_content}</p>"
                    subsections = subsections[1:] if len(subsections) > 1 else []
                
                for subsection in subsections:
                    if not subsection.strip():
                        continue
                    
                    # Get subsection title (may include - Description)
                    lines = subsection.split('\n', 1)
                    subsection_header = lines[0].strip() if lines else ""
                    subsection_body = lines[1] if len(lines) > 1 else ""
                    
                    # Extract subsection title (before - if present)
                    subsection_title = subsection_header.split(' - ')[0].strip()
                    
                    # Determine badge color based on subsection type
                    badge = None
                    icon = ""
                    if subsection_title.lower() in ['fixed', 'fix']:
                        badge = 'fixed'
                        icon = 'wrench'
                        subsection_title_html = f'<h3><i class="fas fa-wrench"></i> Fixed</h3>'
                        if not primary_badge:
                            primary_badge = 'fixed'
                    elif subsection_title.lower() in ['added', 'add']:
                        badge = 'added'
                        icon = 'plus-circle'
                        subsection_title_html = f'<h3><i class="fas fa-plus-circle"></i> Added</h3>'
                        if not primary_badge:
                            primary_badge = 'added'
                    elif subsection_title.lower() in ['changed', 'change']:
                        badge = 'changed'
                        icon = 'edit'
                        subsection_title_html = f'<h3><i class="fas fa-edit"></i> Changed</h3>'
                        if not primary_badge:
                            primary_badge = 'changed'
                    elif subsection_title.lower() in ['removed', 'remove']:
                        badge = 'removed'
                        icon = 'trash'
                        subsection_title_html = f'<h3><i class="fas fa-trash"></i> Removed</h3>'
                        if not primary_badge:
                            primary_badge = 'removed'
                    elif subsection_title.lower() in ['enhanced', 'enhance']:
                        badge = 'enhanced'
                        icon = 'star'
                        subsection_title_html = f'<h3><i class="fas fa-star"></i> Enhanced</h3>'
                        if not primary_badge:
                            primary_badge = 'enhanced'
                    else:
                        subsection_title_html = f'<h3>{subsection_title}</h3>'
                    
                    formatted_content += subsection_title_html
                    
                    # Parse list items and format them
                    if subsection_body:
                        # Convert markdown lists to HTML
                        lines_list = subsection_body.split('\n')
                        in_list = False
                        list_type = None  # 'ul' or 'ol'
                        list_html = ""
                        
                        for line in lines_list:
                            line = line.strip()
                            if not line:
                                if in_list:
                                    list_html += f"</{list_type}>"
                                    in_list = False
                                    list_type = None
                                continue
                            
                            # Check if it's a bullet list item
                            if line.startswith('- '):
                                if in_list and list_type != 'ul':
                                    # Close previous list if different type
                                    list_html += f"</{list_type}>"
                                    in_list = False
                                    list_type = None
                                
                                if not in_list:
                                    list_html += "<ul>"
                                    in_list = True
                                    list_type = 'ul'
                                
                                # Remove the dash and format
                                item_text = line[2:].strip()
                                # Bold text between **
                                item_text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', item_text)
                                # Code blocks
                                item_text = re.sub(r'`([^`]+)`', r'<code>\1</code>', item_text)
                                list_html += f"<li>{item_text}</li>"
                            elif re.match(r'^\d+\.', line):
                                # Numbered list
                                if in_list and list_type != 'ol':
                                    # Close previous list if different type
                                    list_html += f"</{list_type}>"
                                    in_list = False
                                    list_type = None
                                
                                if not in_list:
                                    list_html += "<ol>"
                                    in_list = True
                                    list_type = 'ol'
                                
                                # Remove number and format
                                item_text = re.sub(r'^\d+\.\s*', '', line).strip()
                                item_text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', item_text)
                                item_text = re.sub(r'`([^`]+)`', r'<code>\1</code>', item_text)
                                list_html += f"<li>{item_text}</li>"
                            else:
                                if in_list:
                                    list_html += f"</{list_type}>"
                                    in_list = False
                                    list_type = None
                                # Regular paragraph
                                line = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', line)
                                line = re.sub(r'`([^`]+)`', r'<code>\1</code>', line)
                                formatted_content += f"<p>{line}</p>"
                        
                        if in_list:
                            list_html += f"</{list_type}>"
                        
                        formatted_content += list_html
                
                # Create update entry
                update = {
                    'title': version,
                    'date': date,
                    'content': Markup(formatted_content),
                    'badge': primary_badge
                }
                updates.append(update)
        
    except Exception as e:
        logger.error(f"Error parsing changelog: {e}")
        updates = []
    
    # Get user tier for template
    user_tier = 'free'
    if current_user.is_authenticated:
        try:
            subscription = db_enhanced.get_user_subscription(current_user.id)
            if subscription and subscription.get('tier'):
                user_tier = subscription.get('tier', 'free').lower()
        except Exception:
            pass
    
    return render_template("updates.html", updates=updates, user_tier=user_tier)

@app.route("/verify-email")
@rate_limit('api', max_requests=10)
def verify_email():
    """Verify user's email address"""
    token = request.args.get('token')
    
    if not token:
        flash("Invalid verification link", "error")
        return redirect(url_for("login"))
    
    try:
        success, result = db_enhanced.verify_email_token(token)
        
        if success:
            username = result
            flash(f"Email verified successfully! Welcome, {username}! You can now log in.", "success")
            db_enhanced.log_user_activity(
                username,
                'email_verified',
                'Email address verified',
                request.remote_addr,
                request.headers.get('User-Agent')
            )
        else:
            flash(f"Verification failed: {result}", "error")
        
        return redirect(url_for("login"))
        
    except Exception as e:
        logger.error(f"Error verifying email: {e}")
        flash("An error occurred during verification", "error")
        return redirect(url_for("login"))


@app.route("/resend-verification", methods=["POST"])
@rate_limit('api', max_requests=3, window_minutes=60)
def resend_verification():
    """Resend verification email"""
    email = request.form.get("email", "").strip()
    
    if not email:
        flash("Please provide your email address", "error")
        return redirect(url_for("login"))
    
    try:
        # Get user by email
        user_data = db_enhanced.get_user_by_email(email)
        
        if not user_data:
            # Don't reveal if email exists
            flash("If that email is registered, a verification email has been sent.", "info")
            return redirect(url_for("login"))
        
        # Use named tuple for safe access
        user_row = _user_data_to_row(user_data)
        if not user_row:
            logger.error(
                "Invalid user data structure for email %s: type=%s keys=%s",
                email,
                type(user_data),
                list(user_data.keys()) if isinstance(user_data, dict) else None,
            )
            flash("Database error. Please try again.", "error")
            return redirect(url_for("login"))
        
        username = user_row.username
        
        # Check if already verified
        if user_row.verified:
            flash("Your email is already verified. Please log in.", "info")
            return redirect(url_for("login"))
        
        # Send new verification email
        if is_email_configured():
            token = generate_verification_token()
            db_enhanced.create_verification_token(username, token, expiration_hours=24)
            
            base_url = request.url_root.rstrip('/')
            send_verification_email(email, username, token, base_url)
            
            flash("Verification email sent! Please check your inbox.", "success")
        else:
            flash("Email service is not configured. Please contact support.", "error")
        
        return redirect(url_for("login"))
    
    except Exception as e:
        logger.error(f"Error resending verification: {e}")
        flash("An error occurred. Please try again.", "error")
        return redirect(url_for("login"))


@app.route("/forgot-password", methods=["GET", "POST"])
@rate_limit('api', max_requests=3, window_minutes=60)
def forgot_password():
    """Password reset request page"""
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        
        if not email:
            flash("Please provide your email address", "error")
            return render_template("forgot_password.html")
        
        try:
            # Get user by email
            user_data = db_enhanced.get_user_by_email(email)
            
            # Don't reveal if email exists (security best practice)
            flash("If that email is registered, a password reset link has been sent.", "info")
            
            if user_data:
                username = user_data[0]
                
                # Send password reset email
                if is_email_configured():
                    token = generate_password_reset_token()
                    db_enhanced.create_password_reset_token(username, token, expiration_hours=1)
                    
                    base_url = request.url_root.rstrip('/')
                    send_password_reset_email(email, username, token, base_url)
                    
                    db_enhanced.log_user_activity(
                        username,
                        'password_reset_requested',
                        'Password reset email sent',
                        request.remote_addr,
                        request.headers.get('User-Agent')
                    )
            
            return redirect(url_for("login"))
            
        except Exception as e:
            logger.error(f"Error in forgot password: {e}")
            flash("An error occurred. Please try again.", "error")
            return render_template("forgot_password.html")
    
    return render_template("forgot_password.html")


@app.route("/reset-password", methods=["GET", "POST"])
@rate_limit('api', max_requests=5, window_minutes=60)
def reset_password():
    """Password reset form page"""
    token = request.args.get('token')
    
    if not token:
        flash("Invalid password reset link", "error")
        return redirect(url_for("login"))
    
    if request.method == "POST":
        new_password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        
        # Validate passwords match
        if new_password != confirm_password:
            flash("Passwords do not match", "error")
            return render_template("reset_password.html", token=token)
        
        # Validate password strength
        is_valid, error_msg = SecurityConfig.validate_password(new_password)
        if not is_valid:
            flash(error_msg, "error")
            return render_template("reset_password.html", token=token)
        
        try:
            # Verify token
            is_valid, username = db_enhanced.verify_password_reset_token(token)
            
            if not is_valid or not username:
                flash("Invalid or expired reset link. Please request a new one.", "error")
                return redirect(url_for("forgot_password"))
            
            # Reset password
            new_password_hash = SecurityConfig.hash_password(new_password)
            db_enhanced.reset_user_password(username, new_password_hash)
            db_enhanced.use_password_reset_token(token)
            
            db_enhanced.log_user_activity(
                username,
                'password_reset',
                'Password was reset',
                request.remote_addr,
                request.headers.get('User-Agent')
            )
            
            flash("Password reset successfully! Please log in with your new password.", "success")
            return redirect(url_for("login"))
            
        except Exception as e:
            logger.error(f"Error resetting password: {e}")
            flash("An error occurred. Please try again.", "error")
            return render_template("reset_password.html", token=token)
    
    # GET request - verify token is valid before showing form
    try:
        is_valid, username = db_enhanced.verify_password_reset_token(token)
        
        if not is_valid:
            flash("Invalid or expired reset link. Please request a new one.", "error")
            return redirect(url_for("forgot_password"))
        
        return render_template("reset_password.html", token=token)
        
    except Exception as e:
        logger.error(f"Error verifying reset token: {e}")
        flash("An error occurred. Please try again.", "error")
        return redirect(url_for("forgot_password"))


@app.route("/analytics")
@login_required
@require_feature('analytics')
@rate_limit('api', max_requests=60)
def analytics():
    """Analytics dashboard page"""
    return render_template("analytics.html")

@app.route("/selling")
@login_required
@require_feature('selling')
@rate_limit('api', max_requests=60)
def selling():
    """Selling page for posting items to marketplaces"""
    return render_template("selling.html")

@app.route("/favorites")
@login_required
@rate_limit('api', max_requests=60)
def favorites_page():
    """User's favorites page"""
    try:
        favorites = db_enhanced.get_favorites(current_user.id, limit=200)
        return render_template("favorites.html", favorites=favorites)
    except Exception as e:
        logger.error(f"Error loading favorites page: {e}")
        flash("Error loading favorites", "error")
        return redirect(url_for("dashboard"))


@app.route("/alerts")
@login_required
@rate_limit('api', max_requests=60)
def alerts_page():
    """User's price alerts page"""
    try:
        return render_template("alerts.html")
    except Exception as e:
        logger.error(f"Error loading alerts page: {e}")
        flash("Error loading alerts page", "error")
        return redirect(url_for("dashboard"))

# Favicon and icon routes
@app.route("/favicon.ico")
def favicon():
    """Serve favicon.ico"""
    return app.send_static_file('images/favicon.ico')

@app.route("/apple-touch-icon.png")
@app.route("/apple-touch-icon-precomposed.png")
def apple_touch_icon():
    """Serve apple touch icon"""
    return app.send_static_file('images/apple-touch-icon.png')


# ======================
# PROFILE HELPERS
# ======================

def _save_profile_media_file(file_storage, username: str, media_kind: str) -> str:
    if file_storage is None:
        raise ValueError("No file provided.")

    filename = file_storage.filename or ""
    if not filename or "." not in filename:
        raise ValueError("Unsupported file type.")

    ext = filename.rsplit(".", 1)[1].lower()
    if ext not in ALLOWED_PROFILE_MEDIA_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_PROFILE_MEDIA_EXTENSIONS))
        raise ValueError(f"Unsupported file type. Allowed types: {allowed}")

    mimetype = (file_storage.mimetype or "").lower()
    if mimetype and not mimetype.startswith("image/"):
        raise ValueError("Only image uploads are allowed.")

    user_dir = PROFILE_MEDIA_ROOT / username
    user_dir.mkdir(parents=True, exist_ok=True)

    token = secrets.token_hex(8)
    generated_name = f"{media_kind}-{token}.{ext}"
    destination = user_dir / generated_name

    try:
        file_storage.stream.seek(0)
    except Exception:
        pass

    file_storage.save(destination)

    relative_path = destination.relative_to(Path(app.root_path) / 'static')
    return f"/static/{relative_path.as_posix()}"

def _sanitize_optional_string(value, field_name, max_length, errors, *, min_length=0):
    if value is None:
        return None
    if not isinstance(value, str):
        errors.append(f"{field_name} must be a string")
        return None
    trimmed = value.strip()
    if trimmed == "" and min_length > 0:
        errors.append(f"{field_name} is required")
        return None
    if trimmed and len(trimmed) < min_length:
        errors.append(f"{field_name} must be at least {min_length} characters")
        return None
    if len(trimmed) > max_length:
        errors.append(f"{field_name} must be at most {max_length} characters")
        return None
    return trimmed or None


def _sanitize_media_url(value, field_name, errors):
    if value is None:
        return None
    if not isinstance(value, str):
        errors.append(f"{field_name} must be a string")
        return None
    url = value.strip()
    if url == "":
        return None
    if len(url) > 2048:
        errors.append(f"{field_name} is too long")
        return None
    if not (url.startswith("http://") or url.startswith("https://") or url.startswith("/")):
        errors.append(f"{field_name} must be an absolute URL or site-relative path")
        return None
    return url


def _sanitize_search_interests_payload(raw, errors):
    if raw is None:
        return None
    if not isinstance(raw, list):
        errors.append("search_interests must be a list")
        return None

    cleaned = []
    for item in raw[:12]:
        if isinstance(item, dict):
            label = (item.get("label") or "").strip()
            if not label:
                continue
            cleaned.append({
                "id": str(item.get("id") or label),
                "label": label,
                "category": (item.get("category") or None),
            })
        elif isinstance(item, str):
            label = item.strip()
            if not label:
                continue
            cleaned.append({
                "id": label,
                "label": label,
                "category": None,
            })
    return cleaned


CHANNEL_MESSAGE_ALLOWED_TYPES = {"text", "announcement", "listing", "link", "image", "attachment"}
CHANNEL_ATTACHMENT_ALLOWED_TYPES = {"image", "listing", "link"}


def _normalize_channel_message_payload(payload: Dict[str, Any]) -> Tuple[str, str, Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[int], List[str]]:
    errors: List[str] = []
    if not isinstance(payload, dict):
        return "", "text", None, [], None, ["Invalid payload format."]

    message_type = str(payload.get("message_type") or "text").strip().lower()
    if message_type not in CHANNEL_MESSAGE_ALLOWED_TYPES:
        allowed = ", ".join(sorted(CHANNEL_MESSAGE_ALLOWED_TYPES))
        errors.append(f"message_type must be one of: {allowed}")

    raw_body = payload.get("body")
    sanitized_body = ""
    if raw_body is not None:
        if not isinstance(raw_body, str):
            errors.append("body must be a string")
        else:
            sanitized_body = SecurityConfig.sanitize_input(raw_body).strip()
            if len(sanitized_body) > 2000:
                errors.append("body must be 2000 characters or fewer")
    else:
        sanitized_body = ""

    raw_attachments = payload.get("attachments")
    attachments: List[Dict[str, Any]] = []
    if raw_attachments is None:
        raw_attachments = []
    if not isinstance(raw_attachments, list):
        errors.append("attachments must be a list")
    else:
        for idx, item in enumerate(raw_attachments):
            if not isinstance(item, dict):
                errors.append(f"attachments[{idx}] must be an object")
                continue
            storage_key = (item.get("storage_key") or "").strip()
            attachment_type = (item.get("type") or "").strip().lower()
            if not storage_key:
                errors.append(f"attachments[{idx}].storage_key is required")
                continue
            if attachment_type not in CHANNEL_ATTACHMENT_ALLOWED_TYPES:
                allowed = ", ".join(sorted(CHANNEL_ATTACHMENT_ALLOWED_TYPES))
                errors.append(f"attachments[{idx}].type must be one of: {allowed}")
                continue
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            attachments.append({
                "storage_key": storage_key,
                "type": attachment_type,
                "metadata": metadata,
            })

    rich_content = payload.get("rich_content")
    if rich_content is not None and not isinstance(rich_content, dict):
        errors.append("rich_content must be an object")
        rich_content = None

    thread_root_id = payload.get("thread_root_id")
    normalized_thread_root_id: Optional[int] = None
    if thread_root_id is not None:
        try:
            normalized_thread_root_id = int(thread_root_id)
            if normalized_thread_root_id <= 0:
                raise ValueError
        except (TypeError, ValueError):
            errors.append("thread_root_id must be a positive integer")
            normalized_thread_root_id = None

    if message_type == "text" and not sanitized_body:
        errors.append("Message cannot be empty.")

    if not sanitized_body and not attachments and not rich_content:
        errors.append("Message content cannot be empty.")

    return sanitized_body, message_type, rich_content, attachments, normalized_thread_root_id, errors


def _parse_profile_update_payload(payload):
    if not isinstance(payload, dict):
        return {}, ["Invalid payload format"]

    errors = []
    updates = {}

    display_name = _sanitize_optional_string(payload.get("display_name"), "display_name", 40, errors, min_length=3)
    if display_name is not None:
        updates["display_name"] = display_name

    bio = payload.get("bio")
    if bio is not None:
        if not isinstance(bio, str):
            errors.append("bio must be a string")
        else:
            trimmed = bio.strip()
            if len(trimmed) > 280:
                errors.append("bio must be 280 characters or less")
            else:
                updates["bio"] = trimmed or None

    location = _sanitize_optional_string(payload.get("location"), "location", 120, errors)
    if location is not None or payload.get("location") is None:
        updates["location"] = location

    avatar_url = _sanitize_media_url(payload.get("avatar_url"), "avatar_url", errors)
    if avatar_url is not None or payload.get("avatar_url") is None:
        updates["avatar_url"] = avatar_url

    banner_url = _sanitize_media_url(payload.get("banner_url"), "banner_url", errors)
    if banner_url is not None or payload.get("banner_url") is None:
        updates["banner_url"] = banner_url

    pronouns_raw = payload.get("pronouns")
    pronouns = _sanitize_optional_string(pronouns_raw, "pronouns", 30, errors)
    if pronouns is not None or pronouns_raw is None:
        updates["pronouns"] = pronouns

    gender_raw = payload.get("gender")
    gender = _sanitize_optional_string(gender_raw, "gender", 30, errors)
    if gender is not None or gender_raw is None:
        updates["gender"] = gender

    interests = _sanitize_search_interests_payload(payload.get("search_interests"), errors)
    if interests is not None or payload.get("search_interests") is not None:
        updates["search_interests"] = interests or []

    return updates, errors


def _prepare_visibility_updates(raw_payload):
    if not isinstance(raw_payload, dict):
        return {}, ["visibility must be an object"]

    errors = []
    updates = {}
    valid_values = {"public", "connections", "private"}
    valid_fields = getattr(db_enhanced, "DEFAULT_PROFILE_VISIBILITY", {}).keys()

    for field, value in raw_payload.items():
        if field not in valid_fields:
            errors.append(f"Unsupported visibility field: {field}")
            continue
        if value not in valid_values:
            errors.append(f"Invalid visibility for {field}")
            continue
        updates[field] = value

    return updates, errors


def _normalize_showcase_payload(items):
    if not isinstance(items, list):
        return [], ["items must be a list"]

    normalized = []
    errors = []
    for idx, item in enumerate(items[:10]):
        if not isinstance(item, dict):
            errors.append(f"Item #{idx + 1} must be an object")
            continue
        entity_id = item.get("entity_id")
        if entity_id in (None, ""):
            errors.append(f"Item #{idx + 1} is missing entity_id")
            continue
        label = item.get("label")
        if label is not None:
            label = str(label).strip() or None
        normalized.append({
            "entity_id": str(entity_id),
            "label": label,
            "note": item.get("note"),
            "metadata": item.get("metadata"),
        })

    return normalized, errors


@app.route("/profile")
@login_required
@rate_limit('api', max_requests=60)
def profile_page():
    """User profile management page"""
    try:
        logger.info(f"Loading profile for user: {current_user.id}")
        user_data = db_enhanced.get_user_by_username(current_user.id)
        if not user_data:
            logger.error(f"No user data found for {current_user.id}")
            flash("User not found. Please contact support.", "error")
            return redirect(url_for("dashboard"))

        user_row = _user_data_to_row(user_data)
        if not user_row:
            logger.error(
                "Invalid user data structure for %s: type=%s keys=%s",
                current_user.id,
                type(user_data),
                list(user_data.keys()) if isinstance(user_data, dict) else None,
            )
            flash("Database error. Please try again.", "error")
            return redirect(url_for("dashboard"))

        profile = db_enhanced.ensure_profile(current_user.id)
        visibility = profile.get("visibility_settings", {})
        showcase = db_enhanced.get_profile_showcase(current_user.id)
        profile_activity = db_enhanced.get_profile_activity(current_user.id, limit=20, viewer_username=current_user.id)
        saved_searches = db_enhanced.get_saved_searches(current_user.id)
        favorite_listings = db_enhanced.get_favorites(current_user.id, limit=12)
        notifications = db_enhanced.get_notification_preferences(current_user.id)
        subscription = db_enhanced.get_user_subscription(current_user.id)
        friend_overview = db_enhanced.get_friend_overview(current_user.id, limit=24)
        account_activity_rows = db_enhanced.get_user_activity(current_user.id, limit=10)
        streak = db_enhanced.get_user_streak(current_user.id)
        referral_overview = db_enhanced.get_referral_overview(current_user.id)
        if not referral_overview.get("referral"):
            db_enhanced.ensure_referral_code(current_user.id)
            referral_overview = db_enhanced.get_referral_overview(current_user.id)
        def _to_iso(value):
            if isinstance(value, datetime):
                try:
                    return value.isoformat(sep=' ', timespec='seconds')
                except TypeError:
                    return value.isoformat()
            return value

        saved_searches = [
            {
                **search,
                "created_at": _to_iso(search.get("created_at")),
                "last_run": _to_iso(search.get("last_run")),
            }
            for search in saved_searches
        ]
        favorite_listings = [
            {
                **listing,
                "created_at": _to_iso(listing.get("created_at")),
                "favorited_at": _to_iso(listing.get("favorited_at")),
            }
            for listing in favorite_listings
        ]
        account_activity = [{
            "action": row[0],
            "details": row[1],
            "ip_address": row[2],
            "timestamp": _to_iso(row[3]),
        } for row in account_activity_rows]

        if user_row.role == 'admin':
            subscription = {
                'tier': 'pro',
                'status': 'active',
                'stripe_customer_id': None,
                'stripe_subscription_id': None,
                'current_period_start': None,
                'current_period_end': None,
                'cancel_at_period_end': False,
                'created_at': None,
                'updated_at': None
            }

        account = {
            'username': user_row.username,
            'email': user_row.email,
            'verified': user_row.verified,
            'role': user_row.role,
            'created_at': user_row.created_at,
            'last_login': user_row.last_login,
            'login_count': user_row.login_count
        }

        return render_template(
            "profile.html",
            account=account,
            profile=profile,
            visibility=visibility,
            showcase=showcase,
            profile_activity=profile_activity,
            account_activity=account_activity,
            notifications=notifications,
            subscription=subscription,
            saved_searches=saved_searches,
            favorite_listings=favorite_listings,
            friend_overview=friend_overview,
            streak=streak,
            referral_overview=referral_overview,
        )
    except Exception as e:
        logger.error(f"Error loading profile page: {e}")
        flash("Error loading profile", "error")
        return redirect(url_for("dashboard"))


@app.route("/api/profile/media/upload", methods=["POST"])
@csrf.exempt
@login_required
@rate_limit('api', max_requests=20)
def api_profile_media_upload():
    if not request.files:
        return jsonify({"error": "No file uploaded."}), 400

    responses: Dict[str, str] = {}
    errors: List[str] = []

    for kind in ("avatar", "banner"):
        file_obj = request.files.get(kind)
        if not file_obj:
            continue
        try:
            media_url = _save_profile_media_file(file_obj, current_user.id, kind)
            responses[f"{kind}_url"] = media_url
        except ValueError as exc:
            errors.append(str(exc))
        except Exception as exc:
            logger.error(f"Failed to upload {kind} for {current_user.id}: {exc}")
            errors.append(f"Failed to upload {kind} image.")

    if not responses:
        return jsonify({"errors": errors or ["No valid files supplied."]}), 400

    if errors:
        responses["warnings"] = errors

    return jsonify(responses)


@app.route("/api/profile/me", methods=["GET", "PUT", "PATCH"])
@login_required
@rate_limit('api', max_requests=120)
def api_profile_me():
    payload = request.get_json(silent=True) if request.method != "GET" else None

    if request.method in ("PUT", "PATCH"):
        updates, errors = _parse_profile_update_payload(payload or {})
        if errors:
            return jsonify({"errors": errors}), 400

        changed_fields = list(updates.keys())
        if changed_fields:
            updated = db_enhanced.update_profile(current_user.id, updates)
            if updated:
                db_enhanced.log_profile_activity(
                    current_user.id,
                    "profile_updated",
                    metadata={"fields": changed_fields},
                    visibility="connections",
                )

    profile = db_enhanced.get_profile(current_user.id)
    showcase = db_enhanced.get_profile_showcase(current_user.id)
    profile_activity = db_enhanced.get_profile_activity(current_user.id, limit=10, viewer_username=current_user.id)
    streak = db_enhanced.get_user_streak(current_user.id)

    return jsonify({
        "profile": profile,
        "showcase": showcase,
        "profile_activity": profile_activity,
        "streak": streak,
    })


@app.route("/api/referrals", methods=["GET", "POST"])
@login_required
@rate_limit('api', max_requests=60)
def api_referrals():
    if request.method == "GET":
        regenerate = request.args.get("regenerate")
        if regenerate and regenerate.lower() in {"1", "true", "yes"}:
            db_enhanced.create_referral_code(current_user.id, regenerate=True)
        else:
            db_enhanced.ensure_referral_code(current_user.id)
        overview = db_enhanced.get_referral_overview(current_user.id)
    else:
        payload = request.get_json(silent=True) or {}
        regenerate = bool(payload.get("regenerate", True))
        max_uses = payload.get("max_uses")
        try:
            max_uses_value = int(max_uses) if max_uses is not None else None
        except (TypeError, ValueError):
            return jsonify({"error": "max_uses must be an integer"}), 400
        expires_at = _coerce_datetime(payload.get("expires_at"))
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        try:
            db_enhanced.create_referral_code(
                current_user.id,
                max_uses=max_uses_value,
                expires_at=expires_at,
                metadata=metadata,
                regenerate=regenerate,
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        overview = db_enhanced.get_referral_overview(current_user.id)

    referral = overview.get("referral") or {}
    code = referral.get("code")
    share_url = None
    if code:
        share_url = f"{request.host_url.rstrip('/')}/?ref={code}"
    referral["share_url"] = share_url
    overview["referral"] = referral
    return jsonify(overview), 201 if request.method == "POST" else 200


@app.route("/api/referrals/track", methods=["POST"])
@csrf.exempt
@rate_limit('api', max_requests=120)
def api_referrals_track():
    payload = request.get_json(silent=True) or {}
    code = payload.get("code")
    if not code:
        return jsonify({"error": "code is required"}), 400
    landing_page = (payload.get("landing_page") or "").strip() or request.path
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    metadata.setdefault("user_agent", request.headers.get("User-Agent"))
    metadata.setdefault("remote_addr", request.headers.get("X-Forwarded-For") or request.remote_addr)

    overview = db_enhanced.record_referral_hit(code, landing_page=landing_page, metadata=metadata)
    if overview is None:
        return jsonify({"error": "Referral code not found"}), 404
    return jsonify({"ok": True})


@app.route("/api/referrals/redeem", methods=["POST"])
@login_required
@rate_limit('api', max_requests=30)
def api_referrals_redeem():
    payload = request.get_json(silent=True) or {}
    code = payload.get("code")
    if not code:
        return jsonify({"error": "code is required"}), 400
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    try:
        overview = db_enhanced.redeem_referral_code(code, current_user.id, metadata=metadata)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    referral = overview.get("referral") or {}
    share_url = None
    if referral.get("code"):
        share_url = f"{request.host_url.rstrip('/')}/?ref={referral['code']}"
    referral["share_url"] = share_url
    overview["referral"] = referral
    return jsonify(overview)


@app.route("/api/support/metrics", methods=["GET"])
@login_required
@rate_limit('api', max_requests=60)
def api_support_metrics():
    if current_user.role != 'admin':
        return jsonify({"error": "Admin access required"}), 403

    window_hours = _bounded_int(request.args.get("window_hours"), 720, minimum=1, maximum=24 * 90)
    assigned_to = request.args.get("assigned_to")
    server_slug = request.args.get("server")
    server_id = None

    if server_slug:
        server = db_enhanced.get_server_by_slug(
            server_slug,
            viewer_username=current_user.id,
            include_channels=False,
            include_roles=False,
        )
        if not server:
            return jsonify({"error": "Server not found"}), 404
        server_id = server["id"]

    try:
        metrics = db_enhanced.get_support_metrics(
            window_hours=window_hours,
            server_id=server_id,
            assigned_to=assigned_to,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify(metrics)


@app.route("/api/admin/data/export/<username>", methods=["GET"])
@login_required
@rate_limit('api', max_requests=20)
def api_admin_data_export(username: str):
    if current_user.role != 'admin':
        return jsonify({"error": "Admin access required"}), 403

    try:
        exported = db_enhanced.export_user_data(username)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404

    return jsonify({"export": exported})


@app.route("/api/admin/data/purge/<username>", methods=["POST"])
@login_required
@rate_limit('api', max_requests=10)
def api_admin_data_purge(username: str):
    if current_user.role != 'admin':
        return jsonify({"error": "Admin access required"}), 403
    if username == current_user.id:
        return jsonify({"error": "Cannot purge currently authenticated admin account"}), 400

    confirm = request.args.get("confirm")
    if confirm != "true":
        return jsonify({"error": "Confirmation required. Append ?confirm=true"}), 400

    try:
        db_enhanced.purge_user_data(username)
    except Exception as exc:
        logger.error(f"Failed to purge user data for {username}: {exc}")
        return jsonify({"error": "Unable to purge user data"}), 500

    return jsonify({"ok": True})


@app.route("/api/support/tickets", methods=["GET", "POST"])
@login_required
@rate_limit('api', max_requests=120)
def api_support_tickets():
    viewer = current_user.id
    if request.method == "GET":
        limit = _bounded_int(request.args.get("limit"), 50, minimum=1, maximum=200)
        offset = _bounded_int(request.args.get("offset"), 0, minimum=0, maximum=5000)
        status = request.args.get("status")
        severity = request.args.get("severity")
        assigned_to = request.args.get("assigned_to")
        reporter = request.args.get("reporter")
        server_slug = request.args.get("server")
        server_id = None

        if server_slug:
            server = db_enhanced.get_server_by_slug(
                server_slug,
                viewer_username=viewer,
                include_channels=False,
                include_roles=False,
            )
            if not server:
                return jsonify({"error": "Server not found"}), 404
            server_id = server["id"]

        try:
            payload = db_enhanced.list_support_tickets(
                viewer,
                status=status,
                severity=severity,
                assigned_to=assigned_to,
                server_id=server_id,
                reporter_username=reporter,
                limit=limit,
                offset=offset,
            )
        except PermissionError:
            return jsonify({"error": "Forbidden"}), 403
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        return jsonify(payload)

    # POST create
    payload = request.get_json(silent=True) or {}
    subject = (payload.get("subject") or "").strip()
    body = (payload.get("body") or "").strip()
    severity = payload.get("severity") or "medium"
    assigned_to = payload.get("assigned_to")
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None
    related_report_id = payload.get("related_report_id")
    related_digest_id = payload.get("related_digest_id")
    reporter = payload.get("reporter_username")
    server_slug = payload.get("server_slug")
    server_id = None

    if reporter and reporter != viewer and current_user.role != 'admin':
        return jsonify({"error": "Only admins may create tickets for other reporters"}), 403

    reporter_username = reporter or viewer

    if server_slug:
        server = db_enhanced.get_server_by_slug(
            server_slug,
            viewer_username=viewer,
            include_channels=False,
            include_roles=False,
        )
        if not server:
            return jsonify({"error": "Server not found"}), 404
        if current_user.role != 'admin' and server.get("owner_username") != viewer:
            return jsonify({"error": "Forbidden"}), 403
        server_id = server["id"]

    if assigned_to and current_user.role != 'admin' and assigned_to != viewer:
        return jsonify({"error": "Forbidden"}), 403

    try:
        ticket = db_enhanced.create_support_ticket(
            reporter_username=reporter_username,
            subject=subject,
            body=body,
            server_id=server_id,
            severity=severity,
            assigned_to=assigned_to,
            metadata=metadata,
            related_report_id=related_report_id,
            related_digest_id=related_digest_id,
        )
    except PermissionError:
        return jsonify({"error": "Forbidden"}), 403
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify({"ticket": ticket}), 201


@app.route("/api/support/tickets/<int:ticket_id>", methods=["GET", "PATCH"])
@login_required
@rate_limit('api', max_requests=120)
def api_support_ticket_detail(ticket_id: int):
    viewer = current_user.id
    if request.method == "GET":
        try:
            ticket = db_enhanced.get_support_ticket(ticket_id, viewer)
        except PermissionError:
            return jsonify({"error": "Forbidden"}), 403
        if not ticket:
            return jsonify({"error": "Ticket not found"}), 404
        return jsonify({"ticket": ticket})

    payload = request.get_json(silent=True) or {}
    metadata_updates = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None
    try:
        ticket = db_enhanced.update_support_ticket(
            ticket_id,
            viewer,
            status=payload.get("status"),
            severity=payload.get("severity"),
            assigned_to=payload.get("assigned_to"),
            metadata_updates=metadata_updates,
            comment=payload.get("comment"),
            comment_type=(payload.get("event_type") or "comment"),
        )
    except PermissionError:
        return jsonify({"error": "Forbidden"}), 403
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify({"ticket": ticket})


@app.route("/api/support/tickets/<int:ticket_id>/events", methods=["GET", "POST"])
@login_required
@rate_limit('api', max_requests=120)
def api_support_ticket_events(ticket_id: int):
    viewer = current_user.id
    if request.method == "GET":
        limit = _bounded_int(request.args.get("limit"), 50, minimum=1, maximum=200)
        try:
            events = db_enhanced.list_support_ticket_events(ticket_id, viewer, limit=limit)
        except PermissionError:
            return jsonify({"error": "Forbidden"}), 403
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"events": events})

    payload = request.get_json(silent=True) or {}
    event_type = (payload.get("event_type") or "comment").strip()
    comment = payload.get("comment")
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None

    try:
        event = db_enhanced.add_support_ticket_event(
            ticket_id,
            viewer,
            event_type,
            comment=comment,
            metadata=metadata,
        )
        ticket = db_enhanced.get_support_ticket(ticket_id, viewer)
    except PermissionError:
        return jsonify({"error": "Forbidden"}), 403
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify({"event": event, "ticket": ticket})


@app.route("/support/tickets")
@login_required
def support_tickets_page():
    return render_template(
        "support_tickets.html",
        is_admin=current_user.role == 'admin',
    )


@app.route("/api/profile/me/visibility", methods=["PUT"])
@login_required
@rate_limit('api', max_requests=60)
def api_profile_visibility():
    payload = request.get_json(silent=True) or {}
    visibility_updates, errors = _prepare_visibility_updates(payload.get("visibility", {}))

    if errors:
        return jsonify({"errors": errors}), 400
    if not visibility_updates:
        return jsonify({"visibility": db_enhanced.get_profile(current_user.id)["visibility_settings"]})

    merged = db_enhanced.update_profile_visibility(current_user.id, visibility_updates)
    db_enhanced.log_profile_activity(
        current_user.id,
        "visibility_updated",
        metadata={"fields": list(visibility_updates.keys())},
        visibility="private",
    )
    return jsonify({"visibility": merged})


@app.route("/api/profile/me/showcase/<collection_type>", methods=["PUT"])
@login_required
@rate_limit('api', max_requests=60)
def api_profile_showcase(collection_type):
    payload = request.get_json(silent=True) or {}
    normalized_items, errors = _normalize_showcase_payload(payload.get("items", []))
    if errors:
        return jsonify({"errors": errors}), 400

    try:
        showcase_config = db_enhanced.set_profile_showcase(current_user.id, collection_type, normalized_items)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    showcase = db_enhanced.get_profile_showcase(current_user.id)
    return jsonify({
        "showcase": showcase,
        "showcase_config": showcase_config,
    })


@app.route("/api/profile/connections/<username>", methods=["POST"])
@login_required
@rate_limit('api', max_requests=60)
@csrf.exempt
def api_profile_add_connection(username: str):
    viewer = current_user.id
    target = SecurityConfig.sanitize_input(username or "").strip()

    if not target:
        return jsonify({"error": "Profile not found."}), 404
    if target == viewer:
        return jsonify({"error": "You cannot add yourself."}), 400

    if db_enhanced.is_user_blocked(viewer, target):
        return jsonify({"error": "You have blocked this user."}), 403
    if db_enhanced.is_user_blocked(target, viewer):
        return jsonify({"error": "This user has blocked you."}), 403

    user_exists = db_enhanced.get_user_by_username(target)
    if not user_exists:
        return jsonify({"error": "Profile not found."}), 404

    if not db_enhanced.are_friends(viewer, target):
        return jsonify({"error": "You must be friends before starting a direct message."}), 403

    # Ensure both profiles exist so messaging data can surface display names.
    db_enhanced.ensure_profile(viewer)
    db_enhanced.ensure_profile(target)

    conversation = None
    try:
        conversation = db_enhanced.ensure_dm_conversation_between(viewer, target)
    except ValueError as exc:
        message = str(exc)
        status = 400
        if "blocked" in message.lower():
            status = 403
        return jsonify({"error": message}), status
    except Exception as exc:
        logger.error(f"Failed to ensure DM conversation for {viewer} and {target}: {exc}")
        return jsonify({"error": "Unable to open conversation."}), 500

    if not conversation:
        return jsonify({"error": "Unable to open conversation."}), 500

    result = {
        "status": "ready",
        "conversation": conversation,
    }
    return jsonify(result), 200


@app.route("/api/profile/<username>/friend-request", methods=["POST"])
@login_required
@rate_limit('api', max_requests=60)
@csrf.exempt
def api_send_friend_request(username: str):
    viewer = current_user.id
    target = SecurityConfig.sanitize_input(username or "").strip()
    if not target:
        return jsonify({"error": "Profile not found."}), 404
    if target == viewer:
        return jsonify({"error": "You cannot add yourself."}), 400

    payload = request.get_json(silent=True) or {}
    raw_message = payload.get("message")
    sanitized_message = SecurityConfig.sanitize_input(raw_message) if raw_message else None

    if db_enhanced.is_user_blocked(viewer, target):
        return jsonify({"error": "You have blocked this user."}), 403
    if db_enhanced.is_user_blocked(target, viewer):
        return jsonify({"error": "This user has blocked you."}), 403

    try:
        request_record, created = db_enhanced.create_friend_request(viewer, target, sanitized_message)
    except ValueError as exc:
        message = str(exc)
        status = 400
        lowered = message.lower()
        if "blocked" in lowered:
            status = 403
        elif "limit" in lowered:
            status = 429
        return jsonify({"error": message}), status
    except Exception as exc:
        logger.error(f"Failed to create friend request from {viewer} to {target}: {exc}")
        return jsonify({"error": "Unable to send friend request."}), 500

    overview = db_enhanced.get_friend_overview(viewer, limit=24)
    status_code = 201 if created else 200
    return jsonify({
        "request": request_record,
        "created": created,
        "overview": overview,
    }), status_code


@app.route("/api/friends/requests/<int:request_id>/respond", methods=["POST"])
@login_required
@rate_limit('api', max_requests=60)
@csrf.exempt
def api_respond_friend_request(request_id: int):
    payload = request.get_json(silent=True) or {}
    action = (payload.get("action") or "").strip().lower()
    if action not in {"accept", "decline"}:
        return jsonify({"error": "Action must be 'accept' or 'decline'."}), 400

    try:
        updated = db_enhanced.respond_friend_request(request_id, current_user.id, action)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.error(f"Failed to respond to friend request {request_id}: {exc}")
        return jsonify({"error": "Unable to process friend request."}), 500

    conversation = None
    if updated.get("status") == db_enhanced.FRIEND_REQUEST_STATUS_ACCEPTED:
        requester = updated.get("requester_username")
        if requester:
            try:
                conversation = db_enhanced.ensure_dm_conversation_between(current_user.id, requester)
            except Exception as exc:
                logger.warning(f"Friend request accepted but failed to ensure DM conversation: {exc}")

    overview = db_enhanced.get_friend_overview(current_user.id, limit=24)
    response = {
        "request": updated,
        "overview": overview,
    }
    if conversation:
        response["conversation"] = conversation
    return jsonify(response)


@app.route("/api/friends/requests/<int:request_id>", methods=["DELETE"])
@login_required
@rate_limit('api', max_requests=60)
@csrf.exempt
def api_cancel_friend_request(request_id: int):
    success = db_enhanced.cancel_friend_request(request_id, current_user.id)
    if not success:
        return jsonify({"error": "Friend request not found or already handled."}), 404
    overview = db_enhanced.get_friend_overview(current_user.id, limit=24)
    return jsonify({
        "cancelled": True,
        "overview": overview,
    })


@app.route("/api/friends/<username>", methods=["DELETE"])
@login_required
@rate_limit('api', max_requests=60)
@csrf.exempt
def api_remove_friend(username: str):
    friend_username = SecurityConfig.sanitize_input(username or "").strip()
    if not friend_username:
        return jsonify({"error": "Friend not found."}), 404

    removed = db_enhanced.remove_friendship(current_user.id, friend_username)
    if not removed:
        return jsonify({"error": "Friendship not found."}), 404

    overview = db_enhanced.get_friend_overview(current_user.id, limit=24)
    return jsonify({
        "removed": True,
        "overview": overview,
    })


@app.route("/api/friends/overview", methods=["GET"])
@login_required
@rate_limit('api', max_requests=120)
def api_friend_overview():
    try:
        limit = int(request.args.get("limit", 24))
    except (TypeError, ValueError):
        limit = 24
    overview = db_enhanced.get_friend_overview(current_user.id, limit=limit)
    return jsonify({"overview": overview})


@app.route("/api/profile/blocks", methods=["GET"])
@login_required
@rate_limit('api', max_requests=60)
def api_profile_list_blocks():
    limit = _bounded_int(
        request.args.get("limit"),
        50,
        minimum=1,
        maximum=db_enhanced.USER_BLOCK_MAX_TARGETS,
    )
    offset = _bounded_int(request.args.get("offset"), 0, minimum=0)
    data = db_enhanced.list_user_blocks(current_user.id, limit=limit, offset=offset)
    return jsonify(data)


@app.route("/api/profile/<username>/block", methods=["POST"])
@login_required
@rate_limit('api', max_requests=60)
@csrf.exempt
def api_profile_block_user(username: str):
    target = SecurityConfig.sanitize_input(username or "").strip()
    if not target:
        return jsonify({"error": "User not found."}), 404
    payload = request.get_json(silent=True) or {}
    reason_raw = payload.get("reason")
    reason = SecurityConfig.sanitize_input(reason_raw) if reason_raw else None
    try:
        record = db_enhanced.block_user(current_user.id, target, reason)
    except ValueError as exc:
        message = str(exc)
        status = 400
        if "not found" in message.lower():
            status = 404
        return jsonify({"error": message}), status
    return jsonify({"block": record}), 201


@app.route("/api/profile/<username>/block", methods=["DELETE"])
@login_required
@rate_limit('api', max_requests=60)
@csrf.exempt
def api_profile_unblock_user(username: str):
    target = SecurityConfig.sanitize_input(username or "").strip()
    if not target:
        return jsonify({"error": "User not found."}), 404
    success = db_enhanced.unblock_user(current_user.id, target)
    if not success:
        return jsonify({"error": "Block not found."}), 404
    return jsonify({"unblocked": True})


@app.route("/api/profile/<username>/friends", methods=["GET"])
@rate_limit('api', max_requests=120)
def api_profile_friends(username: str):
    owner = SecurityConfig.sanitize_input(username or "").strip()
    if not owner:
        return jsonify({"error": "Profile not found"}), 404

    profile = db_enhanced.get_profile(owner)
    if not profile:
        return jsonify({"error": "Profile not found"}), 404

    viewer = current_user.id if current_user.is_authenticated else None
    if viewer != owner and not db_enhanced.is_profile_field_visible(owner, "friends", viewer):
        return jsonify({"error": "Friends list is private."}), 403

    limit = _bounded_int(request.args.get("limit"), 24, minimum=1, maximum=200)
    cursor_param = request.args.get("cursor")
    try:
        offset = max(0, int(cursor_param)) if cursor_param is not None else 0
    except (TypeError, ValueError):
        offset = 0

    friends = db_enhanced.list_friendships(owner, limit=limit, offset=offset)
    total = db_enhanced.count_friendships(owner)
    next_offset = offset + limit if len(friends) == limit else None
    next_cursor = None
    if next_offset is not None and next_offset < total:
        next_cursor = str(next_offset)

    return jsonify({
        "friends": friends,
        "count": total,
        "next_cursor": next_cursor,
    })


@app.route("/api/realtime/token", methods=["POST"])
@csrf.exempt
@login_required
@rate_limit('api', max_requests=60)
def api_realtime_token():
    now = int(time.time())
    ttl = int(app.config.get("REALTIME_JWT_TTL_SECONDS", 300))
    issuer = app.config.get("REALTIME_JWT_ISSUER", "superbot")
    audience = app.config.get("REALTIME_JWT_AUDIENCE", "superbot-realtime")

    memberships = db_enhanced.list_user_servers(current_user.id, limit=200)
    server_claims: List[Dict[str, Any]] = []
    for membership in memberships:
        if not isinstance(membership, dict):
            continue
        server_claims.append({
            "slug": membership.get("slug"),
            "role": membership.get("role_name"),
            "permissions": membership.get("permissions", {}),
        })

    payload = {
        "sub": current_user.id,
        "iat": now,
        "exp": now + ttl,
        "iss": issuer,
        "aud": audience,
        "servers": server_claims,
    }

    token = jwt.encode(payload, app.config["REALTIME_JWT_SECRET"], algorithm="HS256")
    if isinstance(token, bytes):
        token = token.decode("utf-8")

    return jsonify({
        "token": token,
        "expires_in": ttl,
    })


@app.route("/api/profile/<username>", methods=["GET"])
@rate_limit('api', max_requests=120)
def api_profile_public(username):
    viewer = current_user.id if current_user.is_authenticated else None
    profile = db_enhanced.get_profile_for_viewer(username, viewer)
    if not profile:
        return jsonify({"error": "Profile not found"}), 404

    showcase = {}
    if db_enhanced.is_profile_field_visible(username, "showcase", viewer):
        showcase = db_enhanced.get_profile_showcase(username)

    activity = db_enhanced.get_profile_activity(username, limit=10, viewer_username=viewer)

    return jsonify({
        "profile": profile,
        "showcase": showcase,
        "profile_activity": activity,
    })


@app.route("/api/profile/<username>/activity", methods=["GET"])
@rate_limit('api', max_requests=120)
def api_profile_public_activity(username):
    viewer = current_user.id if current_user.is_authenticated else None
    profile = db_enhanced.get_profile_for_viewer(username, viewer)
    if not profile:
        return jsonify({"error": "Profile not found"}), 404

    try:
        limit = int(request.args.get("limit", 10))
    except ValueError:
        limit = 10
    limit = max(1, min(limit, 50))
    activity = db_enhanced.get_profile_activity(username, limit=limit, viewer_username=viewer)
    return jsonify({"activity": activity})


@app.route("/api/profile/media/sign", methods=["POST"])
@login_required
@rate_limit('api', max_requests=30)
def api_profile_media_sign():
    return jsonify({"error": "Direct media uploads are not configured for this environment."}), 501


@app.route("/profiles/<username>")
@rate_limit('api', max_requests=120)
def public_profile(username):
    viewer = current_user.id if current_user.is_authenticated else None
    profile = db_enhanced.get_profile_for_viewer(username, viewer)
    if not profile:
        abort(404)

    showcase_visible = db_enhanced.is_profile_field_visible(username, "showcase", viewer)
    activity_visible = db_enhanced.is_profile_field_visible(username, "recent_activity", viewer)

    showcase = db_enhanced.get_profile_showcase(username) if showcase_visible else {}
    profile_activity = db_enhanced.get_profile_activity(username, limit=12, viewer_username=viewer) if activity_visible else []
    relationship = db_enhanced.get_friend_relationship(viewer, username)

    return render_template(
        "profile_public.html",
        profile=profile,
        showcase=showcase,
        profile_activity=profile_activity,
        showcase_visible=showcase_visible,
        activity_visible=activity_visible,
        is_owner=viewer == username,
        friend_relationship=relationship,
    )


# ======================
# COMMUNITY SERVER ROUTES
# ======================


def _extract_topic_tags_payload(payload):
    if not isinstance(payload, dict):
        return []
    tags = payload.get("topic_tags")
    if tags is None:
        tags = payload.get("tags")
    return tags


@app.route("/api/servers", methods=["GET", "POST"])
@csrf.exempt
@login_required
@rate_limit('api', max_requests=60)
def api_servers():
    if request.method == "GET":
        status = request.args.get("status") or "active"
        limit = request.args.get("limit", 100)
        try:
            limit = max(1, min(int(limit), 200))
        except (TypeError, ValueError):
            limit = 100
        status_filter = None if status == "all" else status
        servers = db_enhanced.list_user_servers(current_user.id, status_filter=status_filter, limit=limit)
        return jsonify({"servers": servers})

    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    visibility = (payload.get("visibility") or db_enhanced.SERVER_DEFAULT_VISIBILITY).lower()
    icon_url = payload.get("icon_url")
    banner_url = payload.get("banner_url")
    settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else None
    slug = payload.get("slug")
    description = payload.get("description")
    topic_tags = _extract_topic_tags_payload(payload)

    errors = []
    if len(name) < 3:
        errors.append("name must be at least 3 characters long")
    elif len(name) > db_enhanced.SERVER_NAME_MAX_LENGTH:
        errors.append(f"name must be {db_enhanced.SERVER_NAME_MAX_LENGTH} characters or fewer")

    if visibility not in db_enhanced.SERVER_VISIBILITY_OPTIONS:
        errors.append("visibility must be one of: " + ", ".join(sorted(db_enhanced.SERVER_VISIBILITY_OPTIONS)))

    sanitized_description = None
    if description is not None:
        if not isinstance(description, str):
            errors.append("description must be a string")
        else:
            sanitized_description = description.strip()
            if len(sanitized_description) > db_enhanced.SERVER_DESCRIPTION_MAX_LENGTH:
                errors.append(f"description must be {db_enhanced.SERVER_DESCRIPTION_MAX_LENGTH} characters or fewer")
                sanitized_description = sanitized_description[:db_enhanced.SERVER_DESCRIPTION_MAX_LENGTH]

    sanitized_icon_url = _sanitize_media_url(icon_url, "icon_url", errors)
    sanitized_banner_url = _sanitize_media_url(banner_url, "banner_url", errors)

    if errors:
        return jsonify({"errors": errors}), 400

    try:
        server = db_enhanced.create_server(
            owner_username=current_user.id,
            name=name,
            description=sanitized_description,
            topic_tags=topic_tags,
            visibility=visibility,
            icon_url=sanitized_icon_url,
            banner_url=sanitized_banner_url,
            settings=settings,
            slug=slug,
        )

        db_enhanced.log_profile_activity(
            current_user.id,
            "community_server_created",
            entity_id=server["slug"],
            metadata={
                "server_id": server["id"],
                "visibility": server.get("visibility"),
                "topic_tags": server.get("topic_tags", []),
            },
            visibility="public" if server.get("visibility") == "public" else "connections",
        )
        try:
            feed_payload = {
                "server": {
                    "id": server.get("id"),
                    "slug": server.get("slug"),
                    "name": server.get("name"),
                    "visibility": server.get("visibility"),
                    "topic_tags": server.get("topic_tags", []),
                }
            }
            db_enhanced.log_feed_event(
                event_type="server_created",
                actor_username=current_user.id,
                entity_type="server",
                entity_id=str(server.get("id")),
                server_slug=server.get("slug"),
                audience_type="global",
                payload=feed_payload,
                score=6.0,
            )
            db_enhanced.log_feed_event(
                event_type="server_launched",
                actor_username=current_user.id,
                entity_type="server",
                entity_id=str(server.get("id")),
                server_slug=server.get("slug"),
                audience_type="server",
                audience_id=server.get("slug"),
                payload=feed_payload,
                score=6.5,
            )
        except Exception as feed_exc:
            logger.warning(f"Failed to log server creation feed event: {feed_exc}")
        return jsonify({"server": server}), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.error(f"Failed to create community server: {exc}")
        return jsonify({"error": "Failed to create server"}), 500


@app.route("/api/servers/<slug>", methods=["GET"])
@rate_limit('api', max_requests=120)
def api_server_detail(slug):
    viewer = current_user.id if current_user.is_authenticated else None
    include_roles = current_user.is_authenticated
    server = db_enhanced.get_server_by_slug(
        slug,
        viewer_username=viewer,
        include_channels=False,
        include_roles=include_roles,
    )
    if not server:
        return jsonify({"error": "Server not found"}), 404

    membership = server.get("viewer_membership") or {}
    visibility = (server.get("visibility") or "public").lower()
    can_view_channels = membership.get("status") == "active" or visibility == "public"

    if can_view_channels:
        try:
            server["channels"] = db_enhanced.get_server_channels(server["id"])
        except Exception as exc:
            logger.error(f"Failed to load channels for server {slug}: {exc}")
            server["channels"] = []
    else:
        server.pop("channels", None)

    return jsonify({"server": server})


@app.route("/api/servers/<slug>/channels", methods=["GET"])
@rate_limit('api', max_requests=120)
def api_server_channels(slug):
    if not current_user.is_authenticated:
        return jsonify({"error": "Authentication required"}), 401

    viewer = current_user.id
    server = db_enhanced.get_server_by_slug(
        slug,
        viewer_username=viewer,
        include_channels=False,
        include_roles=False,
    )
    if not server:
        return jsonify({"error": "Server not found"}), 404

    membership = server.get("viewer_membership") or {}
    if membership.get("status") != "active":
        return jsonify({"error": "Join this server to access channels."}), 403

    try:
        channels = db_enhanced.get_server_channels(server["id"])
    except Exception as exc:
        logger.error(f"Failed to load channels for server {slug}: {exc}")
        channels = []

    return jsonify({"channels": channels, "server_id": server["id"]})


@app.route("/api/servers/<slug>/channels", methods=["POST"])
@csrf.exempt
@login_required
@rate_limit('api', max_requests=60)
def api_server_channel_create(slug):
    server = db_enhanced.get_server_by_slug(slug, viewer_username=current_user.id, include_channels=False, include_roles=True)
    if not server:
        return jsonify({"error": "Server not found"}), 404

    membership = server.get("viewer_membership") or {}
    permissions = db_enhanced.get_user_server_permissions(server["id"], current_user.id)
    is_owner = (membership.get("role_name") or "").lower() == "owner"
    if not (is_owner or permissions.get("manage_channels") or permissions.get("manage_server")):
        return jsonify({"error": "Insufficient permissions"}), 403

    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    channel_type = (payload.get("type") or payload.get("channel_type") or "text").lower()
    topic = payload.get("topic")
    position = payload.get("position")
    settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else None

    errors = []
    if len(name) < 2:
        errors.append("name must be at least 2 characters long")
    if channel_type not in db_enhanced.SERVER_CHANNEL_TYPES:
        errors.append("channel type must be one of: " + ", ".join(sorted(db_enhanced.SERVER_CHANNEL_TYPES)))

    sanitized_topic = None
    if topic is not None:
        if not isinstance(topic, str):
            errors.append("topic must be a string")
        else:
            sanitized_topic = topic.strip() or None

    channel_position = None
    if position is not None:
        try:
            channel_position = int(position)
        except (TypeError, ValueError):
            errors.append("position must be an integer")

    if errors:
        return jsonify({"errors": errors}), 400

    try:
        channel = db_enhanced.create_server_channel(
            server["id"],
            name=name,
            channel_type=channel_type,
            topic=sanitized_topic,
            position=channel_position,
            settings=settings,
            created_by=current_user.id,
        )
        return jsonify({"channel": channel}), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.error(f"Failed to create channel for server {slug}: {exc}")
        return jsonify({"error": "Failed to create channel"}), 500


@app.route("/api/servers/<slug>/join", methods=["POST"])
@csrf.exempt
@login_required
@rate_limit('api', max_requests=60)
def api_server_join(slug):
    payload = request.get_json(silent=True) or {}
    invite_code = payload.get("invite_code")
    try:
        result = db_enhanced.join_server(slug, current_user.id, invite_code=invite_code)
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    except Exception as exc:
        logger.error(f"Failed to join server {slug}: {exc}")
        return jsonify({"error": "Failed to join server"}), 500

    membership = result.get("membership")
    server = result.get("server", {})
    if membership and not result.get("already_member"):
        if membership.get("status") == "active":
            db_enhanced.log_profile_activity(
                current_user.id,
                "community_server_joined",
                entity_id=server.get("slug"),
                metadata={"server_id": server.get("id")},
                visibility="connections",
            )
            try:
                profile = db_enhanced.get_profile(current_user.id)
                display_name = profile.get("display_name") if profile else current_user.id
            except Exception:
                display_name = current_user.id
            try:
                payload = {
                    "server": {
                        "id": server.get("id"),
                        "slug": server.get("slug"),
                        "name": server.get("name"),
                    },
                    "member": {
                        "username": current_user.id,
                        "display_name": display_name,
                    },
                }
                event = db_enhanced.log_feed_event(
                    event_type="server_member_joined",
                    actor_username=current_user.id,
                    entity_type="server_membership",
                    entity_id=str(server.get("id")),
                    server_slug=server.get("slug"),
                    audience_type="server",
                    audience_id=server.get("slug"),
                    payload=payload,
                    score=4.0,
                )
                owner_username = server.get("owner_username")
                if owner_username and owner_username != current_user.id:
                    db_enhanced.create_notification(
                        owner_username,
                        "server_member_joined",
                        payload=payload,
                        event_id=event.get("id") if isinstance(event, dict) else None,
                    )
            except Exception as feed_exc:
                logger.warning(f"Failed to log server join feed event: {feed_exc}")
        elif membership.get("status") == "pending":
            db_enhanced.log_profile_activity(
                current_user.id,
                "community_server_join_requested",
                entity_id=server.get("slug"),
                metadata={"server_id": server.get("id")},
                visibility="private",
            )

    return jsonify(result)


@app.route("/api/servers/<slug>/invites", methods=["POST"])
@csrf.exempt
@login_required
@rate_limit('api', max_requests=30)
def api_server_create_invite(slug):
    server = db_enhanced.get_server_by_slug(slug, viewer_username=current_user.id, include_channels=False, include_roles=True)
    if not server:
        return jsonify({"error": "Server not found"}), 404

    permissions = db_enhanced.get_user_server_permissions(server["id"], current_user.id)
    membership = server.get("viewer_membership") or {}
    is_owner = (membership.get("role_name") or "").lower() == "owner"
    if not (is_owner or permissions.get("manage_invites") or permissions.get("manage_server")):
        return jsonify({"error": "Insufficient permissions"}), 403

    payload = request.get_json(silent=True) or {}
    expires_in = payload.get("expires_in") or payload.get("expires_in_hours")
    max_uses = payload.get("max_uses")
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None

    if max_uses is not None:
        try:
            max_uses = int(max_uses)
            if max_uses <= 0:
                max_uses = None
        except (TypeError, ValueError):
            return jsonify({"error": "max_uses must be an integer"}), 400

    if expires_in is not None:
        try:
            expires_in = int(expires_in)
        except (TypeError, ValueError):
            return jsonify({"error": "expires_in must be an integer (hours)"}), 400
    try:
        invite = db_enhanced.create_server_invite(
            server["id"],
            created_by=current_user.id,
            expires_in_hours=expires_in,
            max_uses=max_uses,
            metadata=metadata,
        )
        return jsonify({"invite": invite}), 201
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except Exception as exc:
        logger.error(f"Failed to create invite for server {slug}: {exc}")
        return jsonify({"error": "Failed to create invite"}), 500


@app.route("/api/servers/<slug>/requests", methods=["GET"])
@login_required
@rate_limit('api', max_requests=60)
def api_server_pending_requests(slug):
    server = db_enhanced.get_server_by_slug(slug, viewer_username=current_user.id, include_channels=False, include_roles=True)
    if not server:
        return jsonify({"error": "Server not found"}), 404
    try:
        requests_list = db_enhanced.list_server_pending_requests(server["id"], current_user.id, limit=100)
        return jsonify({"requests": requests_list})
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except Exception as exc:
        logger.error(f"Failed to list join requests for server {slug}: {exc}")
        return jsonify({"error": "Failed to load requests"}), 500


@app.route("/api/servers/<slug>/requests/<target_username>/<action>", methods=["POST"])
@csrf.exempt
@login_required
@rate_limit('api', max_requests=60)
def api_server_request_action(slug, target_username, action):
    server = db_enhanced.get_server_by_slug(slug, viewer_username=current_user.id, include_channels=False, include_roles=True)
    if not server:
        return jsonify({"error": "Server not found"}), 404

    normalized_action = (action or "").lower()
    if normalized_action in {"approve", "accept", "allow"}:
        approve = True
    elif normalized_action in {"reject", "deny"}:
        approve = False
    else:
        return jsonify({"error": "Unsupported action"}), 400

    try:
        result = db_enhanced.respond_to_join_request(server["id"], current_user.id, target_username, approve=approve)
        return jsonify(result)
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    except Exception as exc:
        logger.error(f"Failed to update join request for server {slug}: {exc}")
        return jsonify({"error": "Failed to update request"}), 500


@app.route("/api/servers/discover", methods=["GET"])
@rate_limit('api', max_requests=120)
def api_server_discover():
    viewer = current_user.id if current_user.is_authenticated else None
    query = request.args.get("q") or request.args.get("query")
    tags_query = request.args.getlist("tags")
    if not tags_query:
        raw_tags = request.args.get("topics") or request.args.get("tag")
        if raw_tags:
            tags_query = [part.strip() for part in raw_tags.split(",") if part.strip()]

    limit = request.args.get("limit", 20)
    offset = request.args.get("offset", 0)
    location = request.args.get("location") or request.args.get("city")
    order = (request.args.get("order") or "popularity").lower()
    if order not in {"popularity", "name", "new"}:
        order = "popularity"
    min_members = request.args.get("min_members")
    try:
        limit = max(1, min(int(limit), 50))
    except (TypeError, ValueError):
        limit = 20
    try:
        offset = max(0, int(offset))
    except (TypeError, ValueError):
        offset = 0
    try:
        min_members_int = int(min_members) if min_members is not None else None
        if min_members_int is not None and min_members_int < 0:
            min_members_int = None
    except (TypeError, ValueError):
        min_members_int = None

    try:
        data = db_enhanced.discover_servers(
            viewer_username=viewer,
            query=query,
            tags=tags_query,
            limit=limit,
            offset=offset,
            location=location,
            min_members=min_members_int,
            order=order,
        )
        return jsonify(data)
    except Exception as exc:
        logger.error(f"Failed to load server discovery results: {exc}")
        return jsonify({"error": "Failed to load discovery data"}), 500


@app.route("/servers/discover")
@rate_limit('api', max_requests=60)
def servers_discover_page():
    viewer = current_user.id if current_user.is_authenticated else None
    query = request.args.get("q") or request.args.get("query")
    tags_input = request.args.get("tags") or ""
    tags_list = [part.strip() for part in tags_input.split(",") if part.strip()] if tags_input else []
    location = request.args.get("location") or request.args.get("city")
    try:
        data = db_enhanced.discover_servers(
            viewer_username=viewer,
            query=query,
            tags=tags_list,
            limit=24,
            offset=0,
            location=location,
        )
    except Exception as exc:
        logger.error(f"Failed to render server discovery page: {exc}")
        data = {"results": [], "trending": [], "recommended": [], "joined": []}

    joined_servers = data.get("joined", []) or []
    joined_slugs = {
        srv.get("slug") for srv in joined_servers if srv.get("slug") and srv.get("membership_status") == "active"
    }
    pending_slugs = {
        srv.get("slug") for srv in joined_servers if srv.get("slug") and srv.get("membership_status") == "pending"
    }

    return render_template(
        "servers_discover.html",
        data=data,
        query=query or "",
        tags_input=tags_input,
        location=location or "",
        joined_servers=joined_servers,
        joined_slugs=joined_slugs,
        pending_slugs=pending_slugs,
    )


@app.route("/servers/new", methods=["GET", "POST"])
@login_required
@rate_limit('api', max_requests=30)
def servers_create_page():
    visibility_options = sorted(db_enhanced.SERVER_VISIBILITY_OPTIONS)
    form_defaults = {
        "name": "",
        "slug": "",
        "description": "",
        "topic_tags": "",
        "visibility": db_enhanced.SERVER_DEFAULT_VISIBILITY,
        "icon_url": "",
        "banner_url": "",
        "default_slow_mode": "",
        "welcome_message": "",
        "keyword_filters": "",
    }
    form_data = dict(form_defaults)

    if request.method == "POST":
        for key in form_defaults:
            value = request.form.get(key)
            form_data[key] = value.strip() if isinstance(value, str) else ""
        if form_data["visibility"] not in visibility_options:
            form_data["visibility"] = db_enhanced.SERVER_DEFAULT_VISIBILITY

        errors: List[str] = []
        name = form_data["name"]
        if len(name) < 3:
            errors.append("Server name must be at least 3 characters long.")
        elif len(name) > db_enhanced.SERVER_NAME_MAX_LENGTH:
            errors.append(f"Server name must be {db_enhanced.SERVER_NAME_MAX_LENGTH} characters or fewer.")

        description = form_data["description"] or None
        topic_tags_input = form_data["topic_tags"]
        topic_tags = [tag.strip() for tag in topic_tags_input.split(",") if tag.strip()]

        icon_url = _sanitize_media_url(form_data["icon_url"], "icon_url", errors)
        banner_url = _sanitize_media_url(form_data["banner_url"], "banner_url", errors)

        visibility = form_data["visibility"]

        settings_payload: Dict[str, Any] = {}
        slow_mode_input = form_data["default_slow_mode"]
        if slow_mode_input:
            try:
                slow_mode_value = max(0, min(int(slow_mode_input), 21600))
                settings_payload["default_slow_mode"] = slow_mode_value
            except ValueError:
                errors.append("Default slow mode must be a whole number of seconds.")

        welcome_message = form_data["welcome_message"] or ""
        if welcome_message:
            settings_payload["welcome_message"] = welcome_message

        keyword_filters_input = form_data["keyword_filters"]
        if keyword_filters_input:
            filters = [line.strip() for line in keyword_filters_input.splitlines() if line.strip()]
            if filters:
                settings_payload["keyword_filters"] = filters

        slug_value = form_data["slug"] or None

        if errors:
            for error in errors:
                flash(error, "error")
            return render_template(
                "servers_create.html",
                form_data=form_data,
                visibility_options=visibility_options,
            )

        try:
            server = db_enhanced.create_server(
                owner_username=current_user.id,
                name=name,
                description=description,
                topic_tags=topic_tags,
                visibility=visibility,
                icon_url=icon_url,
                banner_url=banner_url,
                settings=settings_payload,
                slug=slug_value,
            )

            db_enhanced.log_profile_activity(
                current_user.id,
                "community_server_created",
                entity_id=server["slug"],
                metadata={
                    "server_id": server["id"],
                    "visibility": server.get("visibility"),
                    "topic_tags": server.get("topic_tags", []),
                },
                visibility="public" if server.get("visibility") == "public" else "connections",
            )

            flash(f"Server '{server['name']}' created successfully!", "success")
            return redirect(url_for("servers_discover_page", created=server["slug"]))
        except ValueError as exc:
            flash(str(exc), "error")
        except Exception as exc:
            logger.error(f"Failed to create community server: {exc}")
            flash("We couldn't create the server right now. Please try again.", "error")

    return render_template(
        "servers_create.html",
        form_data=form_data,
        visibility_options=visibility_options,
    )


@app.route("/servers")
@rate_limit('api', max_requests=60)
def servers_directory_page():
    viewer = current_user.id if current_user.is_authenticated else None
    try:
        servers = db_enhanced.get_all_servers(limit=500)
    except Exception as exc:
        logger.error(f"Failed to load community server directory: {exc}")
        flash("Unable to load community servers right now.", "error")
        servers = []

    user_servers: List[Dict[str, Any]] = []
    joined_slugs: set[str] = set()
    pending_slugs: set[str] = set()
    if viewer:
        try:
            user_servers = db_enhanced.list_user_servers(viewer, status_filter=None)
        except Exception as exc:
            logger.error(f"Failed to load user servers for {viewer}: {exc}")
            user_servers = []

        for srv in user_servers:
            slug_value = srv.get("slug")
            status = srv.get("membership_status")
            if not slug_value:
                continue
            if status == "active":
                joined_slugs.add(slug_value)
            elif status in {"pending", "requested"}:
                pending_slugs.add(slug_value)

    return render_template(
        "servers_list.html",
        servers=servers,
        user_servers=user_servers,
        joined_slugs=joined_slugs,
        pending_slugs=pending_slugs,
    )


@app.route("/servers/<slug>")
@login_required
@rate_limit('api', max_requests=60)
def servers_view(slug):
    viewer = current_user.id
    server = db_enhanced.get_server_by_slug(
        slug,
        viewer_username=viewer,
        include_channels=True,
        include_roles=False,
    )
    if not server:
        abort(404)

    membership = server.get("viewer_membership") or {}
    status = membership.get("status")
    if status != "active":
        if status == "pending":
            flash("Your join request is pending approval.", "info")
        else:
            flash("Join this server to access its channels.", "error")
        return redirect(url_for("servers_discover_page", q=slug))

    channels = server.get("channels") or []
    return render_template(
        "servers_view.html",
        server=server,
        channels=channels,
    )


@app.route("/servers/<slug>/channels/<channel_slug>")
@login_required
@rate_limit('api', max_requests=120)
def servers_channel_page(slug, channel_slug):
    viewer = current_user.id
    server = db_enhanced.get_server_by_slug(
        slug,
        viewer_username=viewer,
        include_channels=True,
        include_roles=False,
    )
    if not server:
        abort(404)

    membership = server.get("viewer_membership") or {}
    if membership.get("status") != "active":
        flash("You need to join this server to access channels.", "error")
        return redirect(url_for("servers_discover_page", q=slug))

    channel = db_enhanced.get_server_channel_by_slug(server["id"], channel_slug)
    if not channel:
        flash("Channel not found.", "error")
        return redirect(url_for("servers_view", slug=slug))

    channels = server.get("channels") or []
    messages = db_enhanced.get_channel_messages(channel["id"], limit=60, viewer_username=viewer)
    permissions = membership.get("permissions") or {}
    role_name = (membership.get("role_name") or "").lower()
    can_manage_server = bool(
        role_name == "owner"
        or permissions.get("manage_server")
        or permissions.get("manage_channels")
        or permissions.get("moderate_members")
    )

    return render_template(
        "servers_channel.html",
        server=server,
        channel=channel,
        channels=channels,
        messages=messages,
        viewer_username=viewer,
        can_manage_server=can_manage_server,
    )


@app.route("/api/servers/<slug>/channels/<channel_slug>/messages", methods=["GET", "POST"])
@csrf.exempt
@login_required
@rate_limit('api', max_requests=120)
def api_server_channel_messages(slug, channel_slug):
    viewer = current_user.id
    server = db_enhanced.get_server_by_slug(
        slug,
        viewer_username=viewer,
        include_channels=False,
        include_roles=False,
    )
    if not server:
        return jsonify({"error": "Server not found"}), 404

    membership = server.get("viewer_membership") or {}
    if membership.get("status") != "active":
        return jsonify({"error": "Join this server to access messages."}), 403

    channel = db_enhanced.get_server_channel_by_slug(server["id"], channel_slug)
    if not channel:
        return jsonify({"error": "Channel not found"}), 404

    if request.method == "GET":
        since_id = request.args.get("since_id", type=int)
        limit = request.args.get("limit", default=60, type=int)
        limit = max(1, min(limit or 60, 200))
        messages = db_enhanced.get_channel_messages(
            channel["id"],
            limit=limit,
            after_id=since_id,
            viewer_username=viewer,
        )
        return jsonify({"messages": messages})

    payload = request.get_json(silent=True) or {}
    body, message_type, rich_content, attachments, thread_root_id, errors = _normalize_channel_message_payload(payload)
    if errors:
        return jsonify({"errors": errors}), 400

    settings = channel.get("settings") if isinstance(channel.get("settings"), dict) else {}
    slow_mode_seconds = 0
    try:
        slow_mode_seconds = int(settings.get("slow_mode") or 0)
    except (TypeError, ValueError):
        slow_mode_seconds = 0
    if slow_mode_seconds > 0:
        try:
            reserve_channel_message_slot(channel["id"], viewer, slow_mode_seconds, server_id=server["id"])
        except SlowModeViolation as exc:
            retry_after = max(1, int(exc.retry_after))
            return jsonify({"error": f"Slow mode is enabled. Try again in {retry_after} seconds."}), 429

    try:
        message = db_enhanced.create_channel_message(
            channel["id"],
            viewer,
            body,
            message_type=message_type,
            rich_content=rich_content,
            attachments=attachments,
            thread_root_id=thread_root_id,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.error(f"Failed to create channel message: {exc}")
        return jsonify({"error": "Unable to send message."}), 500

    return jsonify({"message": message})


@app.route("/api/servers/<slug>/channels/<channel_slug>/messages/<int:message_id>/reactions", methods=["POST", "DELETE"])
@csrf.exempt
@login_required
@rate_limit('api', max_requests=240)
def api_server_message_reactions(slug, channel_slug, message_id: int):
    viewer = current_user.id
    server = db_enhanced.get_server_by_slug(
        slug,
        viewer_username=viewer,
        include_channels=False,
        include_roles=False,
    )
    if not server:
        return jsonify({"error": "Server not found"}), 404

    membership = server.get("viewer_membership") or {}
    if membership.get("status") != "active":
        return jsonify({"error": "Join this server to interact with messages."}), 403

    channel = db_enhanced.get_server_channel_by_slug(server["id"], channel_slug)
    if not channel:
        return jsonify({"error": "Channel not found"}), 404

    message = db_enhanced.get_channel_message(message_id, viewer_username=viewer)
    if not message or message.get("channel_id") != channel["id"]:
        return jsonify({"error": "Message not found"}), 404

    if request.method == "POST":
        payload = request.get_json(silent=True) or {}
        reaction = (payload.get("reaction") or "").strip()
        if not reaction:
            return jsonify({"error": "Reaction is required."}), 400
        try:
            reactions = db_enhanced.add_channel_message_reaction(message_id, viewer, reaction)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"reactions": reactions})

    payload = request.get_json(silent=True) or {}
    reaction = request.args.get("reaction") or (payload.get("reaction") if isinstance(payload, dict) else None)
    if not reaction:
        return jsonify({"error": "Reaction is required."}), 400
    try:
        reactions = db_enhanced.remove_channel_message_reaction(message_id, viewer, reaction)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"reactions": reactions})


@app.route("/api/servers/<slug>/moderation/keyword-filters", methods=["GET", "POST", "DELETE"])
@csrf.exempt
@login_required
@rate_limit('api', max_requests=60)
def api_server_keyword_filters(slug):
    server = db_enhanced.get_server_by_slug(
        slug,
        viewer_username=current_user.id,
        include_channels=False,
        include_roles=True,
    )
    if not server:
        return jsonify({"error": "Server not found"}), 404

    can_moderate, _, _ = _server_moderation_permissions(server, current_user.id)
    if not can_moderate:
        return jsonify({"error": "Insufficient permissions"}), 403

    if request.method == "GET":
        filters = db_enhanced.get_server_keyword_filters(server["id"])
        return jsonify({"filters": filters})

    payload = request.get_json(silent=True) or {}

    if request.method == "POST":
        phrase = (payload.get("phrase") or "").strip()
        action = (payload.get("action") or "block").strip().lower()
        if not phrase:
            return jsonify({"error": "phrase is required"}), 400

        existing = {
            entry["phrase"].lower(): entry
            for entry in db_enhanced.get_server_keyword_filters(server["id"])
        }
        try:
            filters = db_enhanced.add_server_keyword_filter(
                server["id"],
                phrase,
                action,
                created_by=current_user.id,
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        normalized_phrase = phrase.lower()
        action_type = "keyword_filter_added"
        if normalized_phrase in existing:
            action_type = "keyword_filter_updated"

        try:
            db_enhanced.log_moderation_action(
                server["id"],
                current_user.id,
                action_type,
                target_id=phrase,
                target_type="keyword_filter",
                metadata={
                    "action": next(
                        (item.get("action") for item in filters if item["phrase"].lower() == normalized_phrase),
                        action,
                    )
                },
            )
        except Exception as exc:
            logger.warning(f"Failed to log moderation action for keyword filter update: {exc}")
        return jsonify({"filters": filters}), 200

    phrase = (request.args.get("phrase") or payload.get("phrase") or "").strip()
    if not phrase:
        return jsonify({"error": "phrase is required"}), 400
    try:
        filters = db_enhanced.remove_server_keyword_filter(server["id"], phrase)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        db_enhanced.log_moderation_action(
            server["id"],
            current_user.id,
            "keyword_filter_removed",
            target_id=phrase,
            target_type="keyword_filter",
        )
    except Exception as exc:
        logger.warning(f"Failed to log moderation action for keyword filter removal: {exc}")
    return jsonify({"filters": filters}), 200


@app.route("/api/servers/<slug>/moderation/reports", methods=["GET"])
@login_required
@rate_limit('api', max_requests=60)
def api_server_reports_queue(slug):
    server = db_enhanced.get_server_by_slug(
        slug,
        viewer_username=current_user.id,
        include_channels=False,
        include_roles=True,
    )
    if not server:
        return jsonify({"error": "Server not found"}), 404

    can_moderate, _, _ = _server_moderation_permissions(server, current_user.id)
    if not can_moderate:
        return jsonify({"error": "Insufficient permissions"}), 403

    status_param = request.args.get("status") or ""
    if status_param:
        statuses = [value.strip().lower() for value in status_param.split(",") if value.strip()]
    else:
        statuses = [
            db_enhanced.REPORT_STATUS_PENDING,
            db_enhanced.REPORT_STATUS_REVIEWING,
        ]

    target_type = request.args.get("target_type")
    limit = _bounded_int(request.args.get("limit"), 50, minimum=1, maximum=200)
    offset = _bounded_int(request.args.get("offset"), 0, minimum=0)

    try:
        data = db_enhanced.list_reports(
            limit=limit,
            offset=offset,
            statuses=statuses,
            target_type=target_type,
            server_slug=slug,
        )
    except Exception as exc:
        logger.error(f"Failed to fetch reports queue for {slug}: {exc}")
        return jsonify({"error": "Unable to load reports"}), 500

    data["statuses"] = statuses
    data["target_type"] = target_type
    return jsonify(data)


@app.route("/api/servers/<slug>/moderation/reports/<int:report_id>", methods=["PATCH"])
@csrf.exempt
@login_required
@rate_limit('api', max_requests=60)
def api_server_report_update(slug, report_id: int):
    server = db_enhanced.get_server_by_slug(
        slug,
        viewer_username=current_user.id,
        include_channels=False,
        include_roles=True,
    )
    if not server:
        return jsonify({"error": "Server not found"}), 404

    can_moderate, _, _ = _server_moderation_permissions(server, current_user.id)
    if not can_moderate:
        return jsonify({"error": "Insufficient permissions"}), 403

    payload = request.get_json(silent=True) or {}
    status = (payload.get("status") or "").strip().lower()
    note = payload.get("note")
    if status not in db_enhanced.REPORT_STATUSES:
        return jsonify({"error": "Unsupported status"}), 400

    report = db_enhanced.get_report_by_id(report_id)
    if not report:
        return jsonify({"error": "Report not found"}), 404

    context = report.get("context") or {}
    context_slug = context.get("server_slug") or context.get("server")
    if context_slug and str(context_slug).lower() != slug.lower():
        return jsonify({"error": "Report not found for this server"}), 404

    try:
        updated = db_enhanced.update_report_status(report_id, status)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.error(f"Failed to update report {report_id}: {exc}")
        return jsonify({"error": "Unable to update report"}), 500

    try:
        metadata = {"status": status}
        if note:
            metadata["note"] = note
        db_enhanced.log_moderation_action(
            server["id"],
            current_user.id,
            "report_status_updated",
            target_id=str(report_id),
            target_type=updated.get("target_type"),
            reason=note if isinstance(note, str) else None,
            metadata=metadata,
        )
    except Exception as exc:
        logger.warning(f"Failed to log moderation action for report update: {exc}")

    updated["status"] = status
    return jsonify({"report": updated})


@app.route("/api/servers/<slug>/moderation/actions", methods=["GET"])
@login_required
@rate_limit('api', max_requests=60)
def api_server_moderation_actions(slug):
    server = db_enhanced.get_server_by_slug(
        slug,
        viewer_username=current_user.id,
        include_channels=False,
        include_roles=True,
    )
    if not server:
        return jsonify({"error": "Server not found"}), 404

    can_moderate, _, _ = _server_moderation_permissions(server, current_user.id)
    if not can_moderate:
        return jsonify({"error": "Insufficient permissions"}), 403

    limit = _bounded_int(request.args.get("limit"), 50, minimum=1, maximum=200)
    offset = _bounded_int(request.args.get("offset"), 0, minimum=0)
    action_param = request.args.get("action_types") or request.args.get("action_type") or ""
    action_types = [value.strip().lower() for value in action_param.split(",") if value.strip()] if action_param else None

    try:
        data = db_enhanced.list_moderation_actions(
            server["id"],
            limit=limit,
            offset=offset,
            action_types=action_types,
        )
    except Exception as exc:
        logger.error(f"Failed to load moderation actions for {slug}: {exc}")
        return jsonify({"error": "Unable to load moderation actions"}), 500

    data["action_types"] = action_types or []
    return jsonify(data)


@app.route("/api/servers/<slug>/moderation/actions/export", methods=["GET"])
@login_required
@rate_limit('api', max_requests=30)
def api_server_moderation_actions_export(slug: str):
    server = db_enhanced.get_server_by_slug(
        slug,
        viewer_username=current_user.id,
        include_channels=False,
        include_roles=True,
    )
    if not server:
        return jsonify({"error": "Server not found"}), 404

    can_moderate, _, _ = _server_moderation_permissions(server, current_user.id)
    if not can_moderate:
        return jsonify({"error": "Insufficient permissions"}), 403

    fmt = (request.args.get("format") or "csv").strip().lower()
    limit = _bounded_int(request.args.get("limit"), 5000, minimum=1, maximum=50000)
    start = request.args.get("start")
    end = request.args.get("end")
    action_param = request.args.get("action_types") or request.args.get("action_type") or ""
    action_types = [value.strip().lower() for value in action_param.split(",") if value.strip()] if action_param else None

    try:
        export_payload = db_enhanced.get_moderation_actions_export(
            server["id"],
            start=start,
            end=end,
            action_types=action_types,
            limit=limit,
        )
    except Exception as exc:
        logger.error(f"Failed to export moderation actions for {slug}: {exc}")
        return jsonify({"error": "Unable to generate export"}), 500

    if fmt == "json":
        export_payload["format"] = "json"
        return jsonify(export_payload)

    if fmt != "csv":
        return jsonify({"error": "Unsupported export format"}), 400

    csv_buffer = StringIO()
    fieldnames = [
        "id",
        "server_id",
        "action_type",
        "actor_username",
        "target_type",
        "target_id",
        "reason",
        "metadata",
        "created_at",
    ]
    writer = csv.DictWriter(csv_buffer, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for action in export_payload.get("actions", []):
        row = dict(action)
        row["metadata"] = json.dumps(action.get("metadata") or {}, ensure_ascii=False)
        writer.writerow(row)

    filename = f"moderation-actions-{slug}-{datetime.now().strftime('%Y%m%d%H%M%S')}.csv"
    response = app.response_class(csv_buffer.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.headers["X-Exported-Count"] = str(export_payload.get("count", 0))
    response.headers["X-Exported-Format"] = "csv"
    return response


@app.route("/api/servers/<slug>/tips", methods=["GET", "POST"])
@login_required
@rate_limit('api', max_requests=120)
def api_server_tips(slug: str):
    server = db_enhanced.get_server_by_slug(
        slug,
        viewer_username=current_user.id,
        include_channels=False,
        include_roles=True,
    )
    if not server:
        return jsonify({"error": "Server not found"}), 404

    membership = server.get("viewer_membership") or {}
    if membership.get("status") != "active":
        return jsonify({"error": "Join this server to view tips."}), 403

    can_manage, _, permissions = _server_moderation_permissions(server, current_user.id)
    limit = _bounded_int(request.args.get("limit"), 10, minimum=1, maximum=100)

    if request.method == "GET":
        include_inactive = False
        include_dismissed = False
        if can_manage:
            include_inactive = (request.args.get("include_inactive") or "").lower() in {"1", "true", "yes"}
            include_dismissed = (request.args.get("include_dismissed") or "").lower() in {"1", "true", "yes"}
        tips = db_enhanced.list_server_tips(
            server["id"],
            viewer_username=current_user.id,
            include_inactive=include_inactive,
            include_dismissed=include_dismissed,
            limit=limit,
        )
        return jsonify({
            "tips": tips,
            "can_manage": can_manage,
            "permissions": permissions,
        })

    if not can_manage:
        return jsonify({"error": "Insufficient permissions"}), 403

    payload = request.get_json(silent=True) or {}
    title = (payload.get("title") or "").strip()
    body = (payload.get("body") or "").strip()
    if not title or not body:
        return jsonify({"error": "title and body are required"}), 400

    cta_label = (payload.get("cta_label") or "").strip() or None
    cta_url = (payload.get("cta_url") or "").strip() or None
    dismissible = bool(payload.get("dismissible", True))
    active = bool(payload.get("active", True))
    priority = payload.get("priority")
    try:
        priority_value = int(priority) if priority is not None else 0
    except (TypeError, ValueError):
        priority_value = 0
    start_at = _coerce_datetime(payload.get("start_at"))
    end_at = _coerce_datetime(payload.get("end_at"))
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}

    try:
        tip = db_enhanced.create_server_tip(
            server["id"],
            current_user.id,
            title,
            body,
            cta_label=cta_label,
            cta_url=cta_url,
            dismissible=dismissible,
            active=active,
            priority=priority_value,
            start_at=start_at,
            end_at=end_at,
            metadata=metadata,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify({"tip": tip}), 201


@app.route("/api/servers/<slug>/tips/<int:tip_id>", methods=["PATCH", "DELETE"])
@login_required
@rate_limit('api', max_requests=60)
def api_server_tip_detail(slug: str, tip_id: int):
    server = db_enhanced.get_server_by_slug(
        slug,
        viewer_username=current_user.id,
        include_channels=False,
        include_roles=True,
    )
    if not server:
        return jsonify({"error": "Server not found"}), 404

    can_manage, _, _ = _server_moderation_permissions(server, current_user.id)
    if not can_manage:
        return jsonify({"error": "Insufficient permissions"}), 403

    existing = db_enhanced.get_server_tip(server["id"], tip_id)
    if not existing:
        return jsonify({"error": "Tip not found"}), 404

    if request.method == "DELETE":
        db_enhanced.delete_server_tip(server["id"], tip_id)
        return jsonify({"ok": True})

    payload = request.get_json(silent=True) or {}
    updates: Dict[str, Any] = {}
    for field in ("title", "body", "cta_label", "cta_url", "audience"):
        if field in payload:
            value = payload.get(field)
            updates[field] = value.strip() if isinstance(value, str) else value
    if "active" in payload:
        updates["active"] = bool(payload["active"])
    if "dismissible" in payload:
        updates["dismissible"] = bool(payload["dismissible"])
    if "priority" in payload:
        try:
            updates["priority"] = int(payload["priority"])
        except (TypeError, ValueError):
            return jsonify({"error": "priority must be an integer"}), 400
    if "start_at" in payload:
        updates["start_at"] = _coerce_datetime(payload.get("start_at"))
    if "end_at" in payload:
        updates["end_at"] = _coerce_datetime(payload.get("end_at"))
    if "metadata" in payload and isinstance(payload["metadata"], dict):
        updates["metadata"] = payload["metadata"]

    try:
        tip = db_enhanced.update_server_tip(server["id"], tip_id, updates)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify({"tip": tip})


@app.route("/api/servers/<slug>/tips/<int:tip_id>/dismiss", methods=["POST"])
@login_required
@rate_limit('api', max_requests=120)
def api_server_tip_dismiss(slug: str, tip_id: int):
    server = db_enhanced.get_server_by_slug(
        slug,
        viewer_username=current_user.id,
        include_channels=False,
        include_roles=False,
    )
    if not server:
        return jsonify({"error": "Server not found"}), 404

    membership = server.get("viewer_membership") or {}
    if membership.get("status") != "active":
        return jsonify({"error": "Join this server to manage tips."}), 403

    tip = db_enhanced.get_server_tip(server["id"], tip_id)
    if not tip or tip.get("server_id") != server["id"]:
        return jsonify({"error": "Tip not found"}), 404

    db_enhanced.dismiss_server_tip(tip_id, current_user.id)
    return jsonify({"ok": True})


@app.route("/api/servers/<slug>/moderation/keyword-suggestions", methods=["GET"])
@login_required
@rate_limit('api', max_requests=60)
def api_server_keyword_suggestions(slug: str):
    server = db_enhanced.get_server_by_slug(
        slug,
        viewer_username=current_user.id,
        include_channels=False,
        include_roles=True,
    )
    if not server:
        return jsonify({"error": "Server not found"}), 404

    can_moderate, _, _ = _server_moderation_permissions(server, current_user.id)
    if not can_moderate:
        return jsonify({"error": "Insufficient permissions"}), 403

    limit = _bounded_int(request.args.get("limit"), 10, minimum=1, maximum=50)
    window_hours = _bounded_int(request.args.get("window_hours"), 72, minimum=1, maximum=720)

    try:
        suggestions = db_enhanced.get_moderation_keyword_suggestions(server["id"], window_hours=window_hours, limit=limit)
    except Exception as exc:
        logger.error(f"Failed to compute keyword suggestions for {slug}: {exc}")
        return jsonify({"error": "Unable to load suggestions"}), 500

    return jsonify({
        "suggestions": suggestions,
        "limit": limit,
        "window_hours": window_hours,
    })


@app.route("/api/reports", methods=["POST"])
@csrf.exempt
@login_required
@rate_limit('api', max_requests=60)
def api_create_report():
    payload = request.get_json(silent=True) or {}
    target_type = (payload.get("target_type") or "").strip()
    target_id = (payload.get("target_id") or "").strip()
    context = payload.get("context")

    if not target_type or not target_id:
        return jsonify({"error": "target_type and target_id are required."}), 400

    if context is not None and not isinstance(context, dict):
        return jsonify({"error": "context must be an object"}), 400

    try:
        report = db_enhanced.create_report(
            current_user.id,
            target_type,
            target_id,
            context=context,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.error(f"Failed to create report for {target_type}:{target_id}: {exc}")
        return jsonify({"error": "Unable to submit report."}), 500

    return jsonify({"report": report}), 201


# ======================
# ANALYTICS ROUTES
# ======================


@app.route("/api/servers/<slug>/analytics", methods=["GET"])
@login_required
@rate_limit('api', max_requests=120)
def api_server_analytics(slug):
    server = db_enhanced.get_server_by_slug(
        slug,
        viewer_username=current_user.id,
        include_channels=False,
        include_roles=True,
    )
    if not server:
        return jsonify({"error": "Server not found"}), 404

    can_moderate, _, _ = _server_moderation_permissions(server, current_user.id)
    if not can_moderate:
        return jsonify({"error": "Insufficient permissions"}), 403

    days = _bounded_int(request.args.get("days"), 30, minimum=1, maximum=365)
    try:
        data = db_enhanced.get_server_analytics(server["id"], days=days)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.error(f"Failed to compute analytics for server {slug}: {exc}")
        return jsonify({"error": "Unable to load analytics"}), 500

    data["meta"] = {
        "slug": server.get("slug"),
        "name": server.get("name"),
        "requested_days": days,
    }
    return jsonify(data)


@app.route("/api/analytics/community", methods=["GET"])
@login_required
@rate_limit('api', max_requests=60)
def api_community_analytics():
    if getattr(current_user, "role", "user") != "admin":
        return jsonify({"error": "Insufficient permissions"}), 403
    days = _bounded_int(request.args.get("days"), 30, minimum=1, maximum=365)
    try:
        data = db_enhanced.get_community_analytics(days=days)
    except Exception as exc:
        logger.error(f"Failed to compute community analytics: {exc}")
        return jsonify({"error": "Unable to load analytics"}), 500
    data["meta"] = {"requested_days": days}
    return jsonify(data)


@app.route("/api/servers/<slug>/digest/preview", methods=["GET"])
@login_required
@rate_limit('api', max_requests=60)
def api_server_digest_preview(slug: str):
    server = db_enhanced.get_server_by_slug(
        slug,
        viewer_username=current_user.id,
        include_channels=False,
        include_roles=True,
    )
    if not server:
        return jsonify({"error": "Server not found"}), 404

    owner_username = server.get("owner_username")
    is_admin = getattr(current_user, "role", "user") == "admin"
    can_moderate, _, permissions = _server_moderation_permissions(server, current_user.id)
    if not (is_admin or current_user.id == owner_username or can_moderate or permissions.get("manage_server")):
        return jsonify({"error": "Insufficient permissions"}), 403

    period_days = _bounded_int(request.args.get("period_days"), 7, minimum=1, maximum=90)
    try:
        digest = db_enhanced.compute_server_owner_digest(
            server["id"],
            owner_username=owner_username,
            period_days=period_days,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.error(f"Failed to compute digest preview for server {slug}: {exc}")
        return jsonify({"error": "Unable to compute digest"}), 500

    return jsonify({"digest": digest})


@app.route("/api/servers/<slug>/digests", methods=["GET"])
@login_required
@rate_limit('api', max_requests=60)
def api_server_digest_list(slug: str):
    server = db_enhanced.get_server_by_slug(
        slug,
        viewer_username=current_user.id,
        include_channels=False,
        include_roles=True,
    )
    if not server:
        return jsonify({"error": "Server not found"}), 404

    owner_username = server.get("owner_username")
    is_admin = getattr(current_user, "role", "user") == "admin"
    can_moderate, _, permissions = _server_moderation_permissions(server, current_user.id)
    if not (is_admin or current_user.id == owner_username or can_moderate or permissions.get("manage_server")):
        return jsonify({"error": "Insufficient permissions"}), 403

    limit = _bounded_int(request.args.get("limit"), 20, minimum=1, maximum=100)
    status = request.args.get("status")
    try:
        digests = db_enhanced.list_server_owner_digests(
            server["id"],
            limit=limit,
            status=status,
        )
    except Exception as exc:
        logger.error(f"Failed to list digests for server {slug}: {exc}")
        return jsonify({"error": "Unable to load digests"}), 500

    return jsonify({
        "digests": digests,
        "meta": {
            "limit": limit,
            "status": status,
        },
    })


@app.route("/api/servers/<slug>/digests", methods=["POST"])
@csrf.exempt
@login_required
@rate_limit('api', max_requests=30)
def api_server_digest_enqueue(slug: str):
    server = db_enhanced.get_server_by_slug(
        slug,
        viewer_username=current_user.id,
        include_channels=False,
        include_roles=True,
    )
    if not server:
        return jsonify({"error": "Server not found"}), 404

    owner_username = server.get("owner_username")
    is_admin = getattr(current_user, "role", "user") == "admin"
    if not (is_admin or current_user.id == owner_username):
        return jsonify({"error": "Only the server owner may queue digests."}), 403

    payload = request.get_json(silent=True) or {}
    period_days = _bounded_int(payload.get("period_days"), 7, minimum=1, maximum=90)
    delivery_channel = (payload.get("delivery_channel") or "").strip().lower() or "email"

    try:
        digest = db_enhanced.enqueue_server_owner_digest(
            server["id"],
            owner_username=owner_username,
            period_days=period_days,
            delivery_channel=delivery_channel,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.error(f"Failed to enqueue digest for server {slug}: {exc}")
        return jsonify({"error": "Unable to queue digest"}), 500

    return jsonify({"digest": digest}), 201


@app.route("/api/ops/digests/pending", methods=["GET"])
@login_required
@rate_limit('api', max_requests=60)
def api_ops_pending_digests():
    if getattr(current_user, "role", "user") != "admin":
        return jsonify({"error": "Insufficient permissions"}), 403
    limit = _bounded_int(request.args.get("limit"), 25, minimum=1, maximum=200)
    try:
        pending = db_enhanced.get_pending_owner_digests(limit=limit)
    except Exception as exc:
        logger.error(f"Failed to fetch pending digests: {exc}")
        return jsonify({"error": "Unable to load pending digests"}), 500
    return jsonify({
        "pending": pending,
        "count": len(pending),
        "limit": limit,
    })


@app.route("/api/ops/digests/run", methods=["POST"])
@csrf.exempt
@login_required
@rate_limit('api', max_requests=30)
def api_ops_run_digests():
    if getattr(current_user, "role", "user") != "admin":
        return jsonify({"error": "Insufficient permissions"}), 403
    payload = request.get_json(silent=True) or {}
    limit = _bounded_int(payload.get("limit"), 25, minimum=1, maximum=200)
    try:
        pending = db_enhanced.get_pending_owner_digests(limit=limit)
    except Exception as exc:
        logger.error(f"Failed to fetch pending digests for run: {exc}")
        return jsonify({"error": "Unable to load pending digests"}), 500

    processed: List[Dict[str, Any]] = []
    for record in pending:
        try:
            updated = db_enhanced.mark_server_owner_digest_delivered(record["id"])
            processed.append(updated)
        except Exception as exc:
            logger.error(f"Failed to mark digest {record.get('id')} delivered: {exc}")

    return jsonify({
        "requested": limit,
        "processed": len(processed),
        "digests": processed,
    })


@app.route("/api/ops/digests/<int:digest_id>/deliver", methods=["POST"])
@csrf.exempt
@login_required
@rate_limit('api', max_requests=60)
def api_ops_deliver_digest(digest_id: int):
    if getattr(current_user, "role", "user") != "admin":
        return jsonify({"error": "Insufficient permissions"}), 403
    payload = request.get_json(silent=True) or {}
    success = bool(payload.get("success", True))
    failure_reason = payload.get("failure_reason") if not success else None

    try:
        digest = db_enhanced.mark_server_owner_digest_delivered(
            digest_id,
            success=success,
            failure_reason=failure_reason,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    except Exception as exc:
        logger.error(f"Failed to update digest {digest_id}: {exc}")
        return jsonify({"error": "Unable to update digest"}), 500

    return jsonify({"digest": digest})


# ======================
# FEED & NOTIFICATION ROUTES
# ======================


@app.route("/api/feed/home", methods=["GET"])
@login_required
@rate_limit('api', max_requests=120)
def api_feed_home():
    limit = _bounded_int(request.args.get("limit"), 30, minimum=1, maximum=100)
    offset = _bounded_int(request.args.get("offset"), 0, minimum=0)
    data = db_enhanced.get_home_feed(current_user.id, limit=limit, offset=offset)
    return jsonify(data)


@app.route("/api/feed/servers/<slug>", methods=["GET"])
@login_required
@rate_limit('api', max_requests=120)
def api_feed_server(slug):
    server = db_enhanced.get_server_by_slug(
        slug,
        viewer_username=current_user.id,
        include_channels=False,
        include_roles=False,
    )
    if not server:
        return jsonify({"error": "Server not found"}), 404

    visibility = (server.get("visibility") or "public").lower()
    membership = server.get("viewer_membership") or {}
    if visibility != "public":
        if membership.get("status") != "active":
            return jsonify({"error": "Access denied"}), 403

    limit = _bounded_int(request.args.get("limit"), 20, minimum=1, maximum=100)
    offset = _bounded_int(request.args.get("offset"), 0, minimum=0)
    data = db_enhanced.get_server_feed(slug, limit=limit, offset=offset)
    data["server"] = {
        "slug": server.get("slug"),
        "name": server.get("name"),
        "icon_url": server.get("icon_url"),
        "banner_url": server.get("banner_url"),
        "visibility": visibility,
        "viewer_membership": membership,
    }
    return jsonify(data)


@app.route("/api/notifications", methods=["GET"])
@login_required
@rate_limit('api', max_requests=120)
def api_notifications():
    limit = _bounded_int(request.args.get("limit"), 50, minimum=1, maximum=100)
    offset = _bounded_int(request.args.get("offset"), 0, minimum=0)
    include_read_param = str(request.args.get("include_read", "1")).lower()
    include_read = include_read_param not in {"0", "false", "off", "no"}

    data = db_enhanced.get_notifications(
        current_user.id,
        limit=limit,
        include_read=include_read,
        offset=offset,
    )
    data["grouped"] = _group_notifications_by_day(data.get("notifications", []))
    data["include_read"] = include_read
    return jsonify(data)


@app.route("/api/notifications/mark-read", methods=["POST"])
@csrf.exempt
@login_required
@rate_limit('api', max_requests=60)
def api_notifications_mark_read():
    payload = request.get_json(silent=True) or {}
    notification_ids = payload.get("ids") or []
    mark_all_flag = payload.get("all")
    mark_all = str(mark_all_flag).lower() in {"1", "true", "yes"} if mark_all_flag is not None else False

    if mark_all:
        updated = db_enhanced.mark_all_notifications_read(current_user.id)
    else:
        updated = db_enhanced.mark_notifications_read(current_user.id, notification_ids)
    return jsonify({"updated": updated})


@app.route("/api/notifications/mark-seen", methods=["POST"])
@csrf.exempt
@login_required
@rate_limit('api', max_requests=60)
def api_notifications_mark_seen():
    payload = request.get_json(silent=True) or {}
    notification_ids = payload.get("ids") or []
    updated = db_enhanced.mark_notifications_seen(current_user.id, notification_ids)
    return jsonify({"updated": updated})


@app.route("/api/notifications/dismiss", methods=["POST"])
@csrf.exempt
@login_required
@rate_limit('api', max_requests=60)
def api_notifications_dismiss():
    payload = request.get_json(silent=True) or {}
    notification_id = payload.get("id", payload.get("notification_id"))
    if notification_id is None:
        return jsonify({"error": "notification_id is required"}), 400
    success = db_enhanced.dismiss_notification(current_user.id, notification_id)
    if not success:
        return jsonify({"error": "Notification not found"}), 404
    return jsonify({"dismissed": True})


# ======================
# DIRECT MESSAGING ROUTES
# ======================


def _ensure_dm_membership(conversation_id: int, username: str) -> bool:
    try:
        return db_enhanced.is_user_in_dm_conversation(username, conversation_id)
    except Exception as exc:
        logger.error(f"Error checking DM membership for {username} in {conversation_id}: {exc}")
        return False


def _resolve_dm_attachment_payload(message_type: str, payload: Optional[Dict[str, Any]], viewer: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    if message_type == "listing":
        listing_id = payload.get("listing_id") if isinstance(payload, dict) else None
        if not listing_id:
            raise ValueError("listing_id is required to share a listing.")
        listing = db_enhanced.get_listing_by_id(listing_id)
        if not listing:
            raise ValueError("Listing could not be found.")
        summary = listing.get("title") or "Shared a listing"
        return {"listing_id": listing_id}, summary

    if message_type == "saved_search":
        saved_search_id = payload.get("saved_search_id") if isinstance(payload, dict) else None
        if not saved_search_id:
            raise ValueError("saved_search_id is required to share a saved search.")
        saved = db_enhanced.get_saved_search_by_id(saved_search_id, viewer)
        if not saved:
            raise ValueError("Saved search could not be found.")
        summary = f"Saved search: {saved.get('name') or 'Shared search'}"
        return {"saved_search_id": saved_search_id}, summary

    if message_type == "quick_reply":
        template_key = None
        if isinstance(payload, dict):
            template_key = payload.get("template_key")
        template = next((item for item in DM_QUICK_REPLY_TEMPLATES if item["template_key"] == template_key), None)
        if not template:
            raise ValueError("Unknown quick reply template.")
        return {
            "template_key": template["template_key"],
            "label": template["label"],
            "body": template["body"],
        }, template["body"]

    if message_type == "attachment":
        if not isinstance(payload, dict):
            raise ValueError("Attachment payload must be an object.")
        return payload, None

    return None, None


@app.route("/messages")
@login_required
@rate_limit('api', max_requests=120)
def messages_page():
    """Render the direct messaging hub."""
    quick_templates = DM_QUICK_REPLY_TEMPLATES
    return render_template(
        "messages.html",
        viewer_username=current_user.id,
        quick_templates=quick_templates,
    )


@app.route("/api/dm/conversations", methods=["GET", "POST"])
@login_required
@rate_limit('api', max_requests=120)
@csrf.exempt
def api_dm_conversations():
    viewer = current_user.id

    if request.method == "GET":
        limit = request.args.get("limit", default=30, type=int) or 30
        limit = max(1, min(limit, 200))
        try:
            conversations = db_enhanced.list_dm_conversations(viewer, limit=limit)
            return jsonify({"conversations": conversations, "count": len(conversations)})
        except Exception as exc:
            logger.error(f"Failed to list DM conversations for {viewer}: {exc}")
            return jsonify({"error": "Unable to load conversations."}), 500

    payload = request.get_json(silent=True) or {}
    participants = payload.get("participants", [])
    if not isinstance(participants, list):
        return jsonify({"error": "Participants must be provided as a list."}), 400

    sanitized_participants: List[str] = []
    for item in participants:
        if not item:
            continue
        sanitized = SecurityConfig.sanitize_input(str(item))
        if sanitized and sanitized != viewer:
            sanitized_participants.append(sanitized)

    if not sanitized_participants:
        return jsonify({"error": "Provide at least one other participant."}), 400

    raw_title = payload.get("title")
    title = None
    if raw_title:
        title = SecurityConfig.sanitize_input(str(raw_title))[:120]

    metadata = payload.get("metadata")
    if metadata and not isinstance(metadata, dict):
        metadata = None

    try:
        conversation = db_enhanced.create_dm_conversation(
            viewer,
            sanitized_participants,
            title=title,
            metadata=metadata,
        )
        return jsonify({"conversation": conversation}), 201
    except ValueError as exc:
        message = str(exc)
        status = 400
        if "blocked" in message.lower():
            status = 403
        return jsonify({"error": message}), status
    except Exception as exc:
        logger.error(f"Failed to create DM conversation for {viewer}: {exc}")
        return jsonify({"error": "Unable to create conversation."}), 500


@app.route("/api/dm/conversations/<int:conversation_id>", methods=["GET", "PATCH"])
@login_required
@rate_limit('api', max_requests=180)
def api_dm_conversation_detail(conversation_id: int):
    viewer = current_user.id
    if not _ensure_dm_membership(conversation_id, viewer):
        return jsonify({"error": "Conversation not found."}), 404
    if request.method == "GET":
        try:
            conversation = db_enhanced.get_dm_conversation(conversation_id, viewer)
        except Exception as exc:
            logger.error(f"Failed to fetch DM conversation {conversation_id}: {exc}")
            return jsonify({"error": "Unable to load conversation."}), 500

        if not conversation:
            return jsonify({"error": "Conversation not found."}), 404
        return jsonify({"conversation": conversation})

    payload = request.get_json(silent=True) or {}
    title = payload.get("title")
    if title is None:
        return jsonify({"error": "title is required"}), 400
    clean_title = SecurityConfig.sanitize_input(str(title))
    try:
        conversation = db_enhanced.rename_dm_conversation(conversation_id, viewer, clean_title)
    except ValueError as exc:
        message = str(exc)
        status = 400
        if "permission" in message.lower():
            status = 403
        return jsonify({"error": message}), status
    except Exception as exc:
        logger.error(f"Failed to rename DM conversation {conversation_id}: {exc}")
        return jsonify({"error": "Unable to rename conversation."}), 500

    return jsonify({"conversation": conversation})


@app.route("/api/dm/conversations/<int:conversation_id>/leave", methods=["POST"])
@login_required
@rate_limit('api', max_requests=120)
@csrf.exempt
def api_dm_conversation_leave(conversation_id: int):
    viewer = current_user.id
    if not _ensure_dm_membership(conversation_id, viewer):
        return jsonify({"error": "Conversation not found."}), 404
    try:
        success = db_enhanced.leave_dm_conversation(conversation_id, viewer)
    except ValueError as exc:
        message = str(exc)
        status = 400
        if "cannot leave" in message.lower():
            status = 403
        return jsonify({"error": message}), status
    except Exception as exc:
        logger.error(f"Failed to leave DM conversation {conversation_id}: {exc}")
        return jsonify({"error": "Unable to leave conversation."}), 500

    if not success:
        return jsonify({"error": "You have already left this conversation."}), 409
    return jsonify({"left": True})


@app.route("/api/dm/conversations/<int:conversation_id>/messages", methods=["GET", "POST"])
@login_required
@rate_limit('api', max_requests=240)
@csrf.exempt
def api_dm_messages(conversation_id: int):
    viewer = current_user.id
    if not _ensure_dm_membership(conversation_id, viewer):
        return jsonify({"error": "Conversation not found."}), 404

    if request.method == "GET":
        limit = request.args.get("limit", default=60, type=int) or 60
        limit = max(1, min(limit, 200))
        since_id = request.args.get("since_id", type=int)
        before_id = request.args.get("before_id", type=int)
        try:
            messages = db_enhanced.get_dm_messages(
                conversation_id,
                limit=limit,
                after_id=since_id,
                before_id=before_id,
                viewer_username=viewer,
            )
            return jsonify({"messages": messages})
        except Exception as exc:
            logger.error(f"Failed to load DM messages for {conversation_id}: {exc}")
            return jsonify({"error": "Unable to load messages."}), 500

    payload = request.get_json(silent=True) or {}
    body = payload.get("body") or ""
    message_type = payload.get("message_type", "text") or "text"
    rich_content_payload = payload.get("rich_content")

    try:
        attachment_payload = None
        suggested_summary = None
        if message_type != "text":
            attachment_payload, suggested_summary = _resolve_dm_attachment_payload(message_type, rich_content_payload, viewer)
            if suggested_summary and not body.strip():
                body = suggested_summary
        clean_body = SecurityConfig.sanitize_input(body)
        message = db_enhanced.create_dm_message(
            conversation_id,
            viewer,
            clean_body,
            message_type=message_type,
            rich_content=attachment_payload,
        )
    except ValueError as exc:
        message = str(exc)
        status = 400
        if "blocked" in message.lower():
            status = 403
        return jsonify({"error": message}), status
    except Exception as exc:
        logger.error(f"Failed to create DM message in {conversation_id}: {exc}")
        return jsonify({"error": "Unable to send message."}), 500

    try:
        broadcast_dm_message(conversation_id, message, sender=viewer)
    except Exception as exc:
        logger.warning(f"Failed to broadcast DM message {message.get('id')}: {exc}")

    return jsonify({"message": message})


@app.route("/api/dm/conversations/<int:conversation_id>/messages/<int:message_id>/reactions", methods=["POST", "DELETE"])
@login_required
@rate_limit('api', max_requests=240)
@csrf.exempt
def api_dm_message_reactions(conversation_id: int, message_id: int):
    viewer = current_user.id
    if not _ensure_dm_membership(conversation_id, viewer):
        return jsonify({"error": "Conversation not found."}), 404

    if request.method == "POST":
        payload = request.get_json(silent=True) or {}
        reaction = payload.get("reaction")
        if not reaction:
            return jsonify({"error": "Reaction is required."}), 400
        try:
            reactions = db_enhanced.add_dm_message_reaction(message_id, viewer, reaction)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            logger.error(f"Failed to add DM reaction for message {message_id}: {exc}")
            return jsonify({"error": "Unable to add reaction."}), 500

        try:
            broadcast_dm_reaction(conversation_id, message_id, reactions)
        except Exception as exc:
            logger.warning(f"Failed to broadcast DM reaction update for message {message_id}: {exc}")

        return jsonify({"reactions": reactions})

    reaction = request.args.get("reaction") or (request.get_json(silent=True) or {}).get("reaction")
    if not reaction:
        return jsonify({"error": "Reaction is required."}), 400
    try:
        reactions = db_enhanced.remove_dm_message_reaction(message_id, viewer, reaction)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.error(f"Failed to remove DM reaction for message {message_id}: {exc}")
        return jsonify({"error": "Unable to remove reaction."}), 500

    try:
        broadcast_dm_reaction(conversation_id, message_id, reactions)
    except Exception as exc:
        logger.warning(f"Failed to broadcast DM reaction removal for message {message_id}: {exc}")

    return jsonify({"reactions": reactions})


@app.route("/api/dm/conversations/<int:conversation_id>/read", methods=["POST"])
@login_required
@rate_limit('api', max_requests=240)
@csrf.exempt
def api_dm_mark_read(conversation_id: int):
    viewer = current_user.id
    if not _ensure_dm_membership(conversation_id, viewer):
        return jsonify({"error": "Conversation not found."}), 404

    payload = request.get_json(silent=True) or {}
    message_id = payload.get("message_id")
    if message_id is None:
        return jsonify({"error": "message_id is required."}), 400

    try:
        updated = db_enhanced.update_dm_read_receipt(conversation_id, viewer, int(message_id))
    except Exception as exc:
        logger.error(f"Failed to update DM read receipt for {conversation_id}: {exc}")
        return jsonify({"error": "Unable to update read receipt."}), 500

    if not updated:
        return jsonify({"error": "Unable to update read receipt."}), 400

    try:
        broadcast_dm_read_receipt(conversation_id, viewer, int(message_id))
    except Exception as exc:
        logger.warning(f"Failed to broadcast DM read receipt for conversation {conversation_id}: {exc}")

    return jsonify({"status": "ok"})


# ======================
# SUBSCRIPTION ROUTES
# ======================

@app.route("/subscription")
@login_required
@rate_limit('api', max_requests=60)
def subscription_page():
    """User's subscription management page"""
    try:
        subscription = db_enhanced.get_user_subscription(current_user.id)
        history = db_enhanced.get_subscription_history(current_user.id, limit=10)
        tiers = get_all_tiers()
        
        return render_template("subscription.html", 
                             subscription=subscription, 
                             history=history,
                             tiers=tiers,
                             format_price=format_price)
    except Exception as e:
        logger.error(f"Error loading subscription page: {e}")
        flash("Error loading subscription information", "error")
        return redirect(url_for("dashboard"))


@app.route("/subscription/plans")
@login_required
@rate_limit('api', max_requests=60)
def subscription_plans():
    """View available subscription plans"""
    try:
        tiers = get_all_tiers()
        current_subscription = db_enhanced.get_user_subscription(current_user.id)
        
        return render_template("subscription_plans.html", 
                             tiers=tiers,
                             current_tier=current_subscription.get('tier', 'free'),
                             format_price=format_price)
    except Exception as e:
        logger.error(f"Error loading subscription plans: {e}")
        flash("Error loading subscription plans", "error")
        return redirect(url_for("dashboard"))


@app.route("/subscription/checkout/<tier>")
@login_required
@rate_limit('checkout', max_requests=5, window_minutes=5)
def subscription_checkout(tier):
    """Create Stripe checkout session for subscription"""
    try:
        # Validate tier
        if tier not in ['standard', 'pro']:
            flash("Invalid subscription tier", "error")
            return redirect(url_for("subscription_plans"))
        
        # Get user info
        user_data = db_enhanced.get_user_by_username(current_user.id)
        if not user_data:
            flash("User not found", "error")
            return redirect(url_for("subscription_plans"))

        user_row = _user_data_to_row(user_data)
        if not user_row:
            logger.error(
                "Invalid user data structure for %s during subscription checkout: type=%s keys=%s",
                current_user.id,
                type(user_data),
                list(user_data.keys()) if isinstance(user_data, dict) else None,
            )
            flash("Database error. Please try again.", "error")
            return redirect(url_for("subscription_plans"))
        
        email = user_row.email
        
        # Create checkout session
        success_url = url_for('subscription_success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}'
        cancel_url = url_for('subscription_plans', _external=True)
        
        # Create checkout session - isolated from Flask context to prevent recursion
        try:
            session_obj, error = StripeManager.create_checkout_session(
                tier_name=tier,
                user_email=email,
                username=current_user.id,
                success_url=success_url,
                cancel_url=cancel_url
            )
        except Exception as stripe_error:
            # Catch any errors from Stripe to prevent propagation
            import sys
            print(f"CAUGHT ERROR in checkout route: {type(stripe_error).__name__}: {str(stripe_error)[:200]}", file=sys.stderr)
            flash("Error starting checkout. Please try again.", "error")
            return redirect(url_for("subscription_plans"))
        
        if error:
            # Don't use logger.error here to avoid recursion - error already logged in StripeManager
            flash("Error starting checkout. Please try again.", "error")
            return redirect(url_for("subscription_plans"))
        
        # Log activity
        db_enhanced.log_user_activity(
            current_user.id,
            'subscription_checkout',
            f'Started checkout for {tier} tier',
            request.remote_addr,
            request.headers.get('User-Agent')
        )
        
        # Redirect to Stripe checkout
        return redirect(session_obj.url, code=303)
        
    except Exception as e:
        logger.error(f"Error in subscription checkout: {e}")
        flash("An error occurred. Please try again.", "error")
        return redirect(url_for("subscription_plans"))


@app.route("/subscription/success")
@login_required
def subscription_success():
    """Handle successful subscription checkout"""
    try:
        session_id = request.args.get('session_id')
        
        if session_id:
            # The webhook will handle the actual subscription update
            # This is just the success page
            flash("Subscription activated successfully! Thank you for upgrading.", "success")
            db_enhanced.log_user_activity(
                current_user.id,
                'subscription_activated',
                'Subscription checkout completed',
                request.remote_addr,
                request.headers.get('User-Agent')
            )
        
        return redirect(url_for("subscription_page"))
        
    except Exception as e:
        logger.error(f"Error handling subscription success: {e}")
        flash("Subscription may have been activated. Please check your subscription page.", "info")
        return redirect(url_for("subscription_page"))


@app.route("/subscription/portal")
@login_required
@rate_limit('api', max_requests=10)
def subscription_portal():
    """Redirect to Stripe customer portal"""
    try:
        subscription = db_enhanced.get_user_subscription(current_user.id)
        customer_id = subscription.get('stripe_customer_id')
        
        if not customer_id:
            flash("No active subscription found", "error")
            return redirect(url_for("subscription_plans"))
        
        # Create portal session
        return_url = url_for('subscription_page', _external=True)
        portal_session, error = StripeManager.create_customer_portal_session(customer_id, return_url)
        
        if error:
            logger.error(f"Error creating portal session: {error}")
            flash("Error accessing subscription portal. Please try again.", "error")
            return redirect(url_for("subscription_page"))
        
        # Log activity
        db_enhanced.log_user_activity(
            current_user.id,
            'subscription_portal',
            'Accessed Stripe customer portal',
            request.remote_addr,
            request.headers.get('User-Agent')
        )
        
        return redirect(portal_session.url, code=303)
        
    except Exception as e:
        logger.error(f"Error accessing subscription portal: {e}")
        flash("An error occurred. Please try again.", "error")
        return redirect(url_for("subscription_page"))


@app.route("/webhook/stripe", methods=["POST"])
@csrf.exempt
def stripe_webhook():
    """Handle Stripe webhook events"""
    try:
        payload = request.data
        sig_header = request.headers.get('Stripe-Signature')
        
        # Verify webhook signature
        event, error = StripeManager.verify_webhook_signature(payload, sig_header)
        
        if error:
            logger.error(f"Webhook signature verification failed: {error}")
            return jsonify({"error": error}), 400
        
        # Handle the event
        result = StripeManager.handle_webhook_event(event)
        
        # Process the result and update database
        if result.get('status') == 'success':
            # Checkout completed - update subscription
            username = result.get('username')
            tier = result.get('tier')
            subscription_id = result.get('subscription_id')
            customer_id = result.get('customer_id')
            
            if username and tier:
                try:
                    db_enhanced.create_or_update_subscription(
                        username=username,
                        tier=tier,
                        status='active',
                        stripe_customer_id=customer_id,
                        stripe_subscription_id=subscription_id
                    )
                    cache_set(f"settings:{username}", None, ttl=0)
                    
                    db_enhanced.log_subscription_event(
                        username=username,
                        tier=tier,
                        action='subscription_created',
                        stripe_event_id=event['id'],
                        details=f'Subscription created via Stripe checkout'
                    )
                    
                    logger.info(f"Subscription activated for {username} - {tier} tier")
                except Exception as e:
                    logger.error(f"Failed to update subscription in database: {e}")
                    return jsonify({"error": "Database update failed"}), 500
        
        elif result.get('status') == 'updated':
            # Subscription status changed (active, past_due, canceled, etc.)
            customer_id = result.get('customer_id')
            subscription_status = result.get('subscription_status')
            
            # Find user and update status
            subscription = db_enhanced.get_subscription_by_customer_id(customer_id)
            if subscription:
                username = subscription['username']
                
                # Map Stripe status to our status
                # Stripe statuses: active, past_due, unpaid, canceled, incomplete, incomplete_expired, trialing
                our_status = 'active' if subscription_status in ['active', 'trialing'] else 'inactive'
                
                try:
                    db_enhanced.create_or_update_subscription(
                        username=username,
                        tier=subscription['tier'],
                        status=our_status,
                        stripe_customer_id=customer_id,
                        stripe_subscription_id=subscription.get('stripe_subscription_id')
                    )
                    
                    cache_set(f"settings:{username}", None, ttl=0)
                    
                    db_enhanced.log_subscription_event(
                        username=username,
                        tier=subscription['tier'],
                        action='subscription_updated',
                        stripe_event_id=event['id'],
                        details=f'Status changed to {subscription_status}'
                    )
                    
                    logger.info(f"Subscription updated for {username} - status: {subscription_status}")
                except Exception as e:
                    logger.error(f"Failed to update subscription status: {e}")
                    return jsonify({"error": "Database update failed"}), 500
        
        elif result.get('status') == 'deleted':
            # Subscription cancelled
            customer_id = result.get('customer_id')
            
            # Find user by customer_id using efficient lookup
            subscription = db_enhanced.get_subscription_by_customer_id(customer_id)
            if subscription:
                username = subscription['username']
                try:
                    db_enhanced.cancel_subscription(username)
                    cache_set(f"settings:{username}", None, ttl=0)
                    db_enhanced.log_subscription_event(
                        username=username,
                        tier='free',
                        action='subscription_cancelled',
                        stripe_event_id=event['id'],
                        details='Subscription cancelled via Stripe'
                    )
                    logger.info(f"Subscription cancelled for {username}")
                except Exception as e:
                    logger.error(f"Failed to cancel subscription: {e}")
                    return jsonify({"error": "Database update failed"}), 500
        
        return jsonify({"status": "success"}), 200
        
    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        return jsonify({"error": "Webhook processing failed"}), 500


# ======================
# CLEAN API ROUTES
# ======================

@app.route("/api/status")
@login_required
@rate_limit('api', max_requests=120)
def api_status():
    user_id = current_user.id
    return jsonify({
        "facebook": is_facebook_running(user_id),
        "craigslist": is_craigslist_running(user_id),
        "ksl": is_ksl_running(user_id),
        "ebay": is_ebay_running(user_id),
        "poshmark": is_poshmark_running(user_id),
        "mercari": is_mercari_running(user_id)
    })

@app.route("/api/scraper-health")
@login_required
@rate_limit('api', max_requests=60)
def api_scraper_health():
    """Get detailed health information about all scrapers"""
    try:
        user_id = current_user.id
        health = get_scraper_health(user_id)
        webdriver_diag = get_chrome_diagnostics()
        webdriver_diag["status"] = (
            "ok" if webdriver_diag.get("binary_found") and webdriver_diag.get("chromedriver_found") else "warning"
        )
        health["webdriver"] = webdriver_diag
        return jsonify(health)
    except Exception as e:
        logger.error(f"Error getting scraper health: {e}")
        return jsonify({"error": "Failed to get scraper health"}), 500

@app.route("/api/scraper-metrics")
@login_required
@rate_limit('api', max_requests=60)
def api_scraper_metrics():
    """Get performance metrics for all scrapers."""
    try:
        from scrapers.metrics import get_metrics_summary
        metrics = get_metrics_summary(hours=24)
        return jsonify(metrics)
    except Exception as e:
        logger.error(f"Error getting scraper metrics: {e}")
        return jsonify({"error": "Failed to get metrics"}), 500

@app.route("/api/scraper-metrics/<site_name>")
@login_required
@rate_limit('api', max_requests=60)
def api_scraper_metrics_detail(site_name):
    """Get detailed metrics for specific scraper."""
    try:
        from scrapers.metrics import get_metrics_summary, get_recent_runs
        metrics = get_metrics_summary(site_name, hours=24)
        recent_runs = get_recent_runs(site_name, limit=20)
        return jsonify({
            "summary": metrics,
            "recent_runs": recent_runs
        })
    except Exception as e:
        logger.error(f"Error getting metrics for {site_name}: {e}")
        return jsonify({"error": "Failed to get metrics"}), 500

@app.route("/api/listings")
@login_required
@rate_limit('api', max_requests=60)
def api_listings():
    return jsonify({"listings": get_listings_from_db(50)})

@app.route("/api/system-status")
@login_required
@rate_limit('api', max_requests=60)
def api_system_status():
    """Get comprehensive system status including error recovery information."""
    try:
        status = get_system_status()
        return jsonify(status)
    except Exception as e:
        logger.error(f"Error getting system status: {e}")
        return jsonify({"error": "Failed to get system status"}), 500

# ======================
# ANALYTICS API ROUTES
# ======================

@app.route("/api/analytics/market-insights")
@login_required
@rate_limit('api', max_requests=60)
def api_market_insights():
    """Get comprehensive market insights"""
    try:
        days = request.args.get('days', 30, type=int)
        keyword = request.args.get('keyword')
        
        # Validate days parameter
        if days <= 0 or days > 365:
            return jsonify({"error": "Days must be between 1 and 365"}), 400
        
        insights = db_enhanced.get_market_insights(days, keyword, current_user.id)
        
        # Provide default values if no data exists
        if not insights or not insights.get('overall_stats') or not insights['overall_stats'][0]:
            insights = {
                'overall_stats': (0, 0, 0, 0, 0),  # total_listings, avg_price, min_price, max_price, sources_count
                'top_keywords': [],
                'source_performance': []
            }
        
        return jsonify(insights)
    except Exception as e:
        logger.error(f"Error getting market insights: {e}")
        return jsonify({"error": "Failed to get market insights"}), 500

@app.route("/api/analytics/keyword-trends")
@login_required
@rate_limit('api', max_requests=60)
def api_keyword_trends():
    """Get keyword trends over time"""
    try:
        days = request.args.get('days', 30, type=int)
        keyword = request.args.get('keyword')
        
        # Validate days parameter
        if days <= 0 or days > 365:
            return jsonify({"error": "Days must be between 1 and 365"}), 400
        
        trends = db_enhanced.get_keyword_trends(days, keyword, current_user.id)
        if not trends:
            trends = []
        return jsonify({"trends": trends})
    except Exception as e:
        logger.error(f"Error getting keyword trends: {e}")
        return jsonify({"error": "Failed to get keyword trends"}), 500

@app.route("/api/analytics/price-analytics")
@login_required
@rate_limit('api', max_requests=60)
def api_price_analytics():
    """Get price analytics over time"""
    try:
        days = request.args.get('days', 30, type=int)
        source = request.args.get('source')
        keyword = request.args.get('keyword')
        
        # Validate days parameter
        if days <= 0 or days > 365:
            return jsonify({"error": "Days must be between 1 and 365"}), 400
        
        analytics = db_enhanced.get_price_analytics(days, source, keyword, current_user.id)
        if not analytics:
            analytics = []
        return jsonify({"analytics": analytics})
    except Exception as e:
        logger.error(f"Error getting price analytics: {e}")
        return jsonify({"error": "Failed to get price analytics"}), 500

@app.route("/api/analytics/source-comparison")
@login_required
@rate_limit('api', max_requests=60)
def api_source_comparison():
    """Compare performance across different sources"""
    try:
        days = request.args.get('days', 30, type=int)
        keyword = request.args.get('keyword')
        
        # Validate days parameter
        if days <= 0 or days > 365:
            return jsonify({"error": "Days must be between 1 and 365"}), 400
        
        comparison = db_enhanced.get_source_comparison(days, keyword, current_user.id)
        if not comparison:
            comparison = []
        return jsonify({"comparison": comparison})
    except Exception as e:
        logger.error(f"Error getting source comparison: {e}")
        return jsonify({"error": "Failed to get source comparison"}), 500

@app.route("/api/analytics/keyword-analysis")
@login_required
@rate_limit('api', max_requests=60)
def api_keyword_analysis():
    """Get top keywords and their performance"""
    try:
        days = request.args.get('days', 30, type=int)
        limit = request.args.get('limit', 20, type=int)
        keyword = request.args.get('keyword')
        
        # Validate parameters
        if days <= 0 or days > 365:
            return jsonify({"error": "Days must be between 1 and 365"}), 400
        if limit <= 0 or limit > 100:
            return jsonify({"error": "Limit must be between 1 and 100"}), 400
        
        analysis = db_enhanced.get_keyword_analysis(days, limit, keyword, current_user.id)
        if not analysis:
            analysis = []
        return jsonify({"analysis": analysis})
    except Exception as e:
        logger.error(f"Error getting keyword analysis: {e}")
        return jsonify({"error": "Failed to get keyword analysis"}), 500

@app.route("/api/analytics/hourly-activity")
@login_required
@rate_limit('api', max_requests=60)
def api_hourly_activity():
    """Get listing activity by hour of day"""
    try:
        days = request.args.get('days', 7, type=int)
        keyword = request.args.get('keyword')
        
        # Validate days parameter
        if days <= 0 or days > 365:
            return jsonify({"error": "Days must be between 1 and 365"}), 400
        
        activity = db_enhanced.get_hourly_activity(days, keyword, current_user.id)
        if not activity:
            activity = []
        return jsonify({"activity": activity})
    except Exception as e:
        logger.error(f"Error getting hourly activity: {e}")
        return jsonify({"error": "Failed to get hourly activity"}), 500

@app.route("/api/analytics/price-distribution")
@login_required
@rate_limit('api', max_requests=60)
def api_price_distribution():
    """Get price distribution data for histograms"""
    try:
        days = request.args.get('days', 30, type=int)
        bins = request.args.get('bins', 10, type=int)
        keyword = request.args.get('keyword')
        
        # Validate parameters
        if days <= 0 or days > 365:
            return jsonify({"error": "Days must be between 1 and 365"}), 400
        if bins <= 0 or bins > 50:
            return jsonify({"error": "Bins must be between 1 and 50"}), 400
        
        distribution = db_enhanced.get_price_distribution(days, bins, keyword, current_user.id)
        if not distribution:
            distribution = []
        return jsonify({"distribution": distribution})
    except Exception as e:
        logger.error(f"Error getting price distribution: {e}")
        return jsonify({"error": "Failed to get price distribution"}), 500

@app.route("/api/analytics/update-trends", methods=["POST"])
@csrf.exempt
@login_required
@rate_limit('api', max_requests=10)
def api_update_trends():
    """Update keyword trends from recent listings"""
    try:
        db_enhanced.update_keyword_trends(current_user.id)
        return jsonify({"message": "Trends updated successfully"})
    except Exception as e:
        logger.error(f"Error updating trends: {e}")
        return jsonify({"error": "Failed to update trends"}), 500

# ======================
# SELLER LISTING API ROUTES
# ======================

@app.route("/api/seller-listings", methods=["GET"])
@login_required
@rate_limit('api', max_requests=60)
def api_get_seller_listings():
    """Get all seller listings for current user"""
    try:
        status = request.args.get('status')
        listings = db_enhanced.get_seller_listings(username=current_user.id, status=status)
        return jsonify({"listings": listings})
    except Exception as e:
        logger.error(f"Error getting seller listings: {e}")
        return jsonify({"error": "Failed to get listings"}), 500

@app.route("/api/seller-listings/<int:listing_id>", methods=["GET"])
@login_required
@rate_limit('api', max_requests=60)
def api_get_seller_listing(listing_id):
    """Get a specific seller listing"""
    try:
        listing = db_enhanced.get_seller_listing_by_id(listing_id)
        if not listing:
            return jsonify({"error": "Listing not found"}), 404
        
        # Check if user owns the listing
        if listing['username'] != current_user.id:
            return jsonify({"error": "Unauthorized"}), 403
        
        return jsonify({"listing": listing})
    except Exception as e:
        logger.error(f"Error getting seller listing: {e}")
        return jsonify({"error": "Failed to get listing"}), 500

@app.route("/api/seller-listings", methods=["POST"])
@csrf.exempt
@login_required
@rate_limit('api', max_requests=30)
def api_create_seller_listing():
    """Create a new seller listing"""
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['title', 'price', 'marketplaces']
        for field in required_fields:
            if not data.get(field):
                return jsonify({"error": f"Missing required field: {field}"}), 400
        
        # Verify user exists in database (to avoid FK constraint errors)
        user_data = db_enhanced.get_user_by_username(current_user.id)
        if not user_data:
            logger.error(f"User {current_user.id} not found in database but has active session")
            return jsonify({"error": "User account not found. Please log out and log back in."}), 400
        
        # Sanitize inputs
        title = SecurityConfig.sanitize_input(data['title'])
        description = SecurityConfig.sanitize_input(data.get('description', ''))
        location = SecurityConfig.sanitize_input(data.get('location', ''))
        category = SecurityConfig.sanitize_input(data.get('category', ''))
        
        # Validate price
        try:
            price = int(data['price'])
            if price < 0:
                return jsonify({"error": "Price cannot be negative"}), 400
        except ValueError:
            return jsonify({"error": "Invalid price value"}), 400
        
        # Validate marketplaces
        valid_marketplaces = ['craigslist', 'facebook', 'ksl', 'ebay', 'poshmark', 'mercari']
        marketplaces = data.get('marketplaces', [])
        if isinstance(marketplaces, list):
            # Check if user is trying to use Poshmark or Mercari without Pro subscription
            if 'poshmark' in marketplaces or 'mercari' in marketplaces:
                subscription = db_enhanced.get_user_subscription(current_user.id)
                if subscription.get('tier') != 'pro' and current_user.role != 'admin':
                    return jsonify({"error": "Poshmark and Mercari are only available for Pro subscribers. Please upgrade your plan."}), 403
            marketplaces = ','.join([m for m in marketplaces if m in valid_marketplaces])
        else:
            return jsonify({"error": "Marketplaces must be an array"}), 400
        
        if not marketplaces:
            return jsonify({"error": "Please select at least one marketplace"}), 400
        
        # Get and validate original cost
        original_cost = data.get('original_cost')
        if original_cost is not None and original_cost != '':
            try:
                original_cost = int(original_cost)
                if original_cost < 0:
                    return jsonify({"error": "Original cost cannot be negative"}), 400
            except ValueError:
                return jsonify({"error": "Invalid original cost value"}), 400
        else:
            original_cost = None
        
        # Create listing
        listing_id = db_enhanced.create_seller_listing(
            username=current_user.id,
            title=title,
            description=description,
            price=price,
            category=category,
            location=location,
            images=data.get('images', ''),
            marketplaces=marketplaces,
            original_cost=original_cost
        )
        
        # Log activity
        db_enhanced.log_user_activity(
            current_user.id,
            'create_listing',
            f'Created seller listing: {title}',
            request.remote_addr,
            request.headers.get('User-Agent')
        )
        
        return jsonify({"message": "Listing created successfully", "listing_id": listing_id}), 201
    
    except Exception as e:
        logger.error(f"Error creating seller listing for user {current_user.id}: {e}")
        # Check if it's a foreign key constraint error
        if "FOREIGN KEY constraint failed" in str(e):
            return jsonify({"error": "User account error. Please log out and log back in."}), 400
        return jsonify({"error": "Failed to create listing"}), 500

@app.route("/api/seller-listings/<int:listing_id>", methods=["PUT"])
@csrf.exempt
@login_required
@rate_limit('api', max_requests=30)
def api_update_seller_listing(listing_id):
    """Update a seller listing"""
    try:
        # Check if listing exists and user owns it
        listing = db_enhanced.get_seller_listing_by_id(listing_id)
        if not listing:
            return jsonify({"error": "Listing not found"}), 404
        
        if listing['username'] != current_user.id:
            return jsonify({"error": "Unauthorized"}), 403
        
        data = request.get_json()
        
        # Sanitize inputs
        update_data = {}
        if 'title' in data:
            update_data['title'] = SecurityConfig.sanitize_input(data['title'])
        if 'description' in data:
            update_data['description'] = SecurityConfig.sanitize_input(data['description'])
        if 'location' in data:
            update_data['location'] = SecurityConfig.sanitize_input(data['location'])
        if 'category' in data:
            update_data['category'] = SecurityConfig.sanitize_input(data['category'])
        if 'price' in data:
            try:
                price = int(data['price'])
                if price < 0:
                    return jsonify({"error": "Price cannot be negative"}), 400
                update_data['price'] = price
            except ValueError:
                return jsonify({"error": "Invalid price value"}), 400
        if 'original_cost' in data:
            original_cost = data['original_cost']
            if original_cost is not None and original_cost != '':
                try:
                    original_cost = int(original_cost)
                    if original_cost < 0:
                        return jsonify({"error": "Original cost cannot be negative"}), 400
                    update_data['original_cost'] = original_cost
                except ValueError:
                    return jsonify({"error": "Invalid original cost value"}), 400
            else:
                update_data['original_cost'] = None
        if 'status' in data:
            update_data['status'] = data['status']
        if 'images' in data:
            update_data['images'] = data['images']
        if 'marketplaces' in data:
            marketplaces = data['marketplaces']
            if isinstance(marketplaces, list):
                valid_marketplaces = ['craigslist', 'facebook', 'ksl', 'ebay', 'poshmark', 'mercari']
                # Check if user is trying to use Poshmark or Mercari without Pro subscription
                if 'poshmark' in marketplaces or 'mercari' in marketplaces:
                    subscription = db_enhanced.get_user_subscription(current_user.id)
                    if subscription.get('tier') != 'pro' and current_user.role != 'admin':
                        return jsonify({"error": "Poshmark and Mercari are only available for Pro subscribers. Please upgrade your plan."}), 403
                update_data['marketplaces'] = ','.join([m for m in marketplaces if m in valid_marketplaces])
        
        # Update listing
        success = db_enhanced.update_seller_listing(listing_id, **update_data)
        
        if success:
            # Log activity
            db_enhanced.log_user_activity(
                current_user.id,
                'update_listing',
                f'Updated seller listing ID: {listing_id}',
                request.remote_addr,
                request.headers.get('User-Agent')
            )
            return jsonify({"message": "Listing updated successfully"})
        else:
            return jsonify({"error": "Failed to update listing"}), 500
    
    except Exception as e:
        logger.error(f"Error updating seller listing: {e}")
        return jsonify({"error": "Failed to update listing"}), 500

@app.route("/api/seller-listings/<int:listing_id>", methods=["DELETE"])
@csrf.exempt
@login_required
@rate_limit('api', max_requests=30)
def api_delete_seller_listing(listing_id):
    """Delete a seller listing"""
    try:
        success = db_enhanced.delete_seller_listing(listing_id, current_user.id)
        
        if success:
            # Log activity
            db_enhanced.log_user_activity(
                current_user.id,
                'delete_listing',
                f'Deleted seller listing ID: {listing_id}',
                request.remote_addr,
                request.headers.get('User-Agent')
            )
            return jsonify({"message": "Listing deleted successfully"})
        else:
            return jsonify({"error": "Listing not found or unauthorized"}), 404
    
    except Exception as e:
        logger.error(f"Error deleting seller listing: {e}")
        return jsonify({"error": "Failed to delete listing"}), 500

@app.route("/api/seller-listings/<int:listing_id>/post", methods=["POST"])
@csrf.exempt
@login_required
@rate_limit('api', max_requests=10)
def api_post_seller_listing(listing_id):
    """Post a listing to selected marketplaces"""
    try:
        # Get the listing
        listing = db_enhanced.get_seller_listing_by_id(listing_id)
        if not listing:
            return jsonify({"error": "Listing not found"}), 404
        
        # Check if user owns the listing
        if listing['username'] != current_user.id:
            return jsonify({"error": "Unauthorized"}), 403
        
        # For now, we'll return a message that this feature requires additional setup
        # In a real implementation, this would interface with each marketplace's API
        return jsonify({
            "message": "Posting to marketplaces",
            "note": "Direct posting to marketplaces requires additional API setup and authentication for each platform. Please manually post for now.",
            "listing": listing
        }), 200
    
    except Exception as e:
        logger.error(f"Error posting seller listing: {e}")
        return jsonify({"error": "Failed to post listing"}), 500

@app.route("/api/seller-listings/<int:listing_id>/status", methods=["PUT"])
@csrf.exempt
@login_required
@rate_limit('api', max_requests=30)
def api_update_listing_status(listing_id):
    """Update a listing's status (e.g., mark as sold)"""
    try:
        # Get the listing
        listing = db_enhanced.get_seller_listing_by_id(listing_id)
        if not listing:
            return jsonify({"error": "Listing not found"}), 404
        
        # Check if user owns the listing
        if listing['username'] != current_user.id:
            return jsonify({"error": "Unauthorized"}), 403
        
        data = request.get_json()
        new_status = data.get('status', '').lower()
        
        # Validate status
        valid_statuses = ['draft', 'posted', 'sold', 'archived']
        if new_status not in valid_statuses:
            return jsonify({"error": f"Invalid status. Must be one of: {', '.join(valid_statuses)}"}), 400
        
        # Get additional fields for sold status
        sold_on_marketplace = data.get('sold_on_marketplace')
        actual_sale_price = data.get('actual_sale_price')
        
        # Validate sold_on_marketplace if provided
        if sold_on_marketplace:
            valid_marketplaces = ['craigslist', 'facebook', 'ksl', 'ebay', 'other']
            if sold_on_marketplace not in valid_marketplaces:
                return jsonify({"error": f"Invalid marketplace. Must be one of: {', '.join(valid_marketplaces)}"}), 400
        
        # Validate actual_sale_price if provided
        if actual_sale_price is not None:
            try:
                actual_sale_price = int(actual_sale_price)
                if actual_sale_price < 0:
                    return jsonify({"error": "Sale price cannot be negative"}), 400
            except (ValueError, TypeError):
                return jsonify({"error": "Invalid sale price"}), 400
        
        # Update the status
        success = db_enhanced.update_seller_listing_status(
            listing_id, 
            current_user.id, 
            new_status,
            sold_on_marketplace=sold_on_marketplace,
            actual_sale_price=actual_sale_price
        )
        
        if success:
            # Log activity
            activity_msg = f'Updated listing "{listing["title"]}" status to {new_status}'
            if new_status == 'sold' and sold_on_marketplace:
                activity_msg += f' on {sold_on_marketplace}'
            if new_status == 'sold' and actual_sale_price is not None:
                activity_msg += f' for ${actual_sale_price}'
                
            db_enhanced.log_user_activity(
                current_user.id,
                'update_listing_status',
                activity_msg,
                request.remote_addr,
                request.headers.get('User-Agent')
            )
            
            return jsonify({"message": f"Listing status updated to {new_status}"}), 200
        else:
            return jsonify({"error": "Failed to update listing status"}), 500
    
    except Exception as e:
        logger.error(f"Error updating listing status: {e}")
        return jsonify({"error": "Failed to update listing status"}), 500

@app.route("/api/seller-listings/stats", methods=["GET"])
@login_required
@rate_limit('api', max_requests=60)
def api_seller_listing_stats():
    """Get statistics about user's seller listings"""
    try:
        stats = db_enhanced.get_seller_listing_stats(current_user.id)
        return jsonify({"stats": stats})
    except Exception as e:
        logger.error(f"Error getting seller listing stats: {e}")
        return jsonify({"error": "Failed to get stats"}), 500

# ======================
# FAVORITES API ROUTES
# ======================

@app.route("/api/favorites", methods=["GET"])
@login_required
@rate_limit('api', max_requests=60)
def api_get_favorites():
    """Get user's favorite listings"""
    try:
        limit = request.args.get('limit', 100, type=int)
        favorites = db_enhanced.get_favorites(current_user.id, limit)
        return jsonify({"favorites": favorites, "count": len(favorites)})
    except Exception as e:
        logger.error(f"Error getting favorites: {e}")
        return jsonify({"error": "Failed to get favorites"}), 500


@app.route("/api/favorites/<int:listing_id>", methods=["POST"])
@csrf.exempt
@login_required
@rate_limit('api', max_requests=30)
def api_add_favorite(listing_id):
    """Add a listing to favorites"""
    try:
        data = request.get_json() or {}
        notes = data.get('notes')
        
        success = db_enhanced.add_favorite(current_user.id, listing_id, notes)
        
        if success:
            db_enhanced.log_user_activity(
                current_user.id,
                'add_favorite',
                f'Added listing {listing_id} to favorites',
                request.remote_addr,
                request.headers.get('User-Agent')
            )
            return jsonify({"message": "Added to favorites", "favorited": True})
        else:
            return jsonify({"message": "Already in favorites", "favorited": True})
            
    except Exception as e:
        logger.error(f"Error adding favorite: {e}")
        return jsonify({"error": "Failed to add favorite"}), 500


@app.route("/api/favorites/<int:listing_id>", methods=["DELETE"])
@csrf.exempt
@login_required
@rate_limit('api', max_requests=30)
def api_remove_favorite(listing_id):
    """Remove a listing from favorites"""
    try:
        success = db_enhanced.remove_favorite(current_user.id, listing_id)
        
        if success:
            db_enhanced.log_user_activity(
                current_user.id,
                'remove_favorite',
                f'Removed listing {listing_id} from favorites',
                request.remote_addr,
                request.headers.get('User-Agent')
            )
            return jsonify({"message": "Removed from favorites", "favorited": False})
        else:
            return jsonify({"error": "Not in favorites"}), 404
            
    except Exception as e:
        logger.error(f"Error removing favorite: {e}")
        return jsonify({"error": "Failed to remove favorite"}), 500


@app.route("/api/favorites/<int:listing_id>/check", methods=["GET"])
@login_required
@rate_limit('api', max_requests=60)
def api_check_favorite(listing_id):
    """Check if a listing is favorited"""
    try:
        is_fav = db_enhanced.is_favorited(current_user.id, listing_id)
        return jsonify({"favorited": is_fav})
    except Exception as e:
        logger.error(f"Error checking favorite: {e}")
        return jsonify({"error": "Failed to check favorite"}), 500


@app.route("/api/favorites/<int:listing_id>/notes", methods=["PUT"])
@csrf.exempt
@login_required
@rate_limit('api', max_requests=30)
def api_update_favorite_notes(listing_id):
    """Update notes for a favorite"""
    try:
        data = request.get_json()
        notes = data.get('notes', '')
        
        success = db_enhanced.update_favorite_notes(current_user.id, listing_id, notes)
        
        if success:
            return jsonify({"message": "Notes updated"})
        else:
            return jsonify({"error": "Favorite not found"}), 404
            
    except Exception as e:
        logger.error(f"Error updating favorite notes: {e}")
        return jsonify({"error": "Failed to update notes"}), 500


# ======================
# SAVED SEARCHES API ROUTES
# ======================

@app.route("/api/saved-searches", methods=["GET"])
@login_required
@rate_limit('api', max_requests=60)
def api_get_saved_searches():
    """Get user's saved searches"""
    try:
        searches = db_enhanced.get_saved_searches(current_user.id)
        return jsonify({"searches": searches, "count": len(searches)})
    except Exception as e:
        logger.error(f"Error getting saved searches: {e}")
        return jsonify({"error": "Failed to get saved searches"}), 500


@app.route("/api/saved-searches", methods=["POST"])
@csrf.exempt
@login_required
@rate_limit('api', max_requests=30)
def api_create_saved_search():
    """Create a new saved search"""
    try:
        data = request.get_json()
        
        # Validate required fields
        name = data.get('name')
        if not name:
            return jsonify({"error": "Search name is required"}), 400
        
        # Sanitize inputs
        name = SecurityConfig.sanitize_input(name)
        keywords = data.get('keywords')
        min_price = data.get('min_price')
        max_price = data.get('max_price')
        sources = data.get('sources')  # Comma-separated string
        location = data.get('location')
        radius = data.get('radius')
        notify_new = data.get('notify_new', True)
        
        search_id = db_enhanced.create_saved_search(
            current_user.id, name, keywords, min_price, max_price,
            sources, location, radius, notify_new
        )
        
        db_enhanced.log_user_activity(
            current_user.id,
            'create_saved_search',
            f'Created saved search: {name}',
            request.remote_addr,
            request.headers.get('User-Agent')
        )
        
        return jsonify({"message": "Search saved", "search_id": search_id}), 201
        
    except Exception as e:
        logger.error(f"Error creating saved search: {e}")
        return jsonify({"error": "Failed to create saved search"}), 500


@app.route("/api/saved-searches/<int:search_id>", methods=["DELETE"])
@csrf.exempt
@login_required
@rate_limit('api', max_requests=30)
def api_delete_saved_search(search_id):
    """Delete a saved search"""
    try:
        success = db_enhanced.delete_saved_search(search_id, current_user.id)
        
        if success:
            db_enhanced.log_user_activity(
                current_user.id,
                'delete_saved_search',
                f'Deleted saved search ID: {search_id}',
                request.remote_addr,
                request.headers.get('User-Agent')
            )
            return jsonify({"message": "Search deleted"})
        else:
            return jsonify({"error": "Search not found"}), 404
            
    except Exception as e:
        logger.error(f"Error deleting saved search: {e}")
        return jsonify({"error": "Failed to delete search"}), 500


# ======================
# PRICE ALERTS API ROUTES
# ======================

@app.route("/api/price-alerts", methods=["GET"])
@login_required
@rate_limit('api', max_requests=60)
def api_get_price_alerts():
    """Get user's price alerts"""
    try:
        alerts = db_enhanced.get_price_alerts(current_user.id)
        return jsonify({"alerts": alerts, "count": len(alerts)})
    except Exception as e:
        logger.error(f"Error getting price alerts: {e}")
        return jsonify({"error": "Failed to get price alerts"}), 500


@app.route("/api/price-alerts", methods=["POST"])
@csrf.exempt
@login_required
@rate_limit('api', max_requests=30)
def api_create_price_alert():
    """Create a new price alert"""
    try:
        data = request.get_json()
        
        # Validate required fields
        keywords = data.get('keywords')
        threshold_price = data.get('threshold_price')
        
        if not keywords or threshold_price is None:
            return jsonify({"error": "Keywords and threshold price are required"}), 400
        
        # Validate threshold price
        try:
            threshold_price = int(threshold_price)
            if threshold_price < 0:
                return jsonify({"error": "Threshold price must be positive"}), 400
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid threshold price"}), 400
        
        # Sanitize keywords
        keywords = SecurityConfig.sanitize_input(keywords)
        alert_type = data.get('alert_type', 'under')
        
        if alert_type not in ['under', 'over']:
            return jsonify({"error": "Alert type must be 'under' or 'over'"}), 400
        
        alert_id = db_enhanced.create_price_alert(
            current_user.id, keywords, threshold_price, alert_type
        )
        
        db_enhanced.log_user_activity(
            current_user.id,
            'create_price_alert',
            f'Created price alert: {keywords} {alert_type} ${threshold_price}',
            request.remote_addr,
            request.headers.get('User-Agent')
        )
        
        return jsonify({"message": "Price alert created", "alert_id": alert_id}), 201
        
    except Exception as e:
        logger.error(f"Error creating price alert: {e}")
        return jsonify({"error": "Failed to create price alert"}), 500


@app.route("/api/price-alerts/<int:alert_id>", methods=["DELETE"])
@csrf.exempt
@login_required
@rate_limit('api', max_requests=30)
def api_delete_price_alert(alert_id):
    """Delete a price alert"""
    try:
        success = db_enhanced.delete_price_alert(alert_id, current_user.id)
        
        if success:
            db_enhanced.log_user_activity(
                current_user.id,
                'delete_price_alert',
                f'Deleted price alert ID: {alert_id}',
                request.remote_addr,
                request.headers.get('User-Agent')
            )
            return jsonify({"message": "Alert deleted"})
        else:
            return jsonify({"error": "Alert not found"}), 404
            
    except Exception as e:
        logger.error(f"Error deleting price alert: {e}")
        return jsonify({"error": "Failed to delete alert"}), 500


@app.route("/api/price-alerts/<int:alert_id>/toggle", methods=["POST"])
@csrf.exempt
@login_required
@rate_limit('api', max_requests=30)
def api_toggle_price_alert(alert_id):
    """Toggle a price alert on/off"""
    try:
        success = db_enhanced.toggle_price_alert(alert_id, current_user.id)
        
        if success:
            return jsonify({"message": "Alert toggled"})
        else:
            return jsonify({"error": "Alert not found"}), 404
            
    except Exception as e:
        logger.error(f"Error toggling price alert: {e}")
        return jsonify({"error": "Failed to toggle alert"}), 500


# ======================
# DATA EXPORT API ROUTES
# ======================

@app.route("/api/export/listings", methods=["GET"])
@login_required
@rate_limit('api', max_requests=10)
def api_export_listings():
    """Export listings data as CSV or JSON"""
    try:
        export_format = request.args.get('format', 'json')
        limit = request.args.get('limit', 1000, type=int)
        
        # Get listings
        listings = db_enhanced.get_listings(limit)
        
        if export_format == 'csv':
            import csv
            from io import StringIO
            
            output = StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow(['ID', 'Title', 'Price', 'Link', 'Image URL', 'Source', 'Created At'])
            
            # Write data
            # Note: listings is a list of tuples: (id, title, price, link, image_url, source, created_at)
            for listing in listings:
                try:
                    listing_row = ListingRow._make(listing)
                    writer.writerow([
                        listing_row.id,
                        listing_row.title,
                        listing_row.price,
                        listing_row.link,
                        listing_row.image_url,
                        listing_row.source,
                        listing_row.created_at
                    ])
                except (TypeError, ValueError) as e:
                    logger.error(f"Invalid listing data structure: {e}")
                    continue  # Skip invalid listings
            
            output.seek(0)
            return output.getvalue(), 200, {
                'Content-Type': 'text/csv',
                'Content-Disposition': f'attachment; filename=listings_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
            }
        
        else:  # JSON format
            return jsonify({
                "data": listings,
                "count": len(listings),
                "exported_at": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error exporting listings: {e}")
        return jsonify({"error": "Failed to export listings"}), 500


@app.route("/api/export/favorites", methods=["GET"])
@login_required
@rate_limit('api', max_requests=10)
def api_export_favorites():
    """Export user's favorites as CSV or JSON"""
    try:
        export_format = request.args.get('format', 'json')
        
        favorites = db_enhanced.get_favorites(current_user.id, limit=1000)
        
        if export_format == 'csv':
            import csv
            from io import StringIO
            
            output = StringIO()
            writer = csv.writer(output)
            
            writer.writerow(['ID', 'Title', 'Price', 'Link', 'Source', 'Notes', 'Favorited At'])
            
            for fav in favorites:
                writer.writerow([
                    fav.get('id'),
                    fav.get('title'),
                    fav.get('price'),
                    fav.get('link'),
                    fav.get('source'),
                    fav.get('notes', ''),
                    fav.get('favorited_at')
                ])
            
            output.seek(0)
            return output.getvalue(), 200, {
                'Content-Type': 'text/csv',
                'Content-Disposition': f'attachment; filename=favorites_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
            }
        
        else:
            return jsonify({
                "data": favorites,
                "count": len(favorites),
                "exported_at": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error exporting favorites: {e}")
        return jsonify({"error": "Failed to export favorites"}), 500


@app.route("/api/export/searches", methods=["GET"])
@login_required
@rate_limit('api', max_requests=10)
def api_export_searches():
    """Export user's saved searches as JSON"""
    try:
        searches = db_enhanced.get_saved_searches(current_user.id)
        
        return jsonify({
            "data": searches,
            "count": len(searches),
            "exported_at": datetime.now().isoformat()
        })
            
    except Exception as e:
        logger.error(f"Error exporting searches: {e}")
        return jsonify({"error": "Failed to export searches"}), 500


@app.route("/api/export/seller-listings", methods=["GET"])
@login_required
@rate_limit('api', max_requests=10)
def api_export_seller_listings():
    """Export user's seller listings with all details"""
    try:
        format_type = request.args.get('format', 'json')
        listings = db_enhanced.get_seller_listings(username=current_user.id, limit=10000)
        
        if format_type == 'csv':
            import io
            import csv
            
            output = io.StringIO()
            if listings:
                writer = csv.DictWriter(output, fieldnames=listings[0].keys())
                writer.writeheader()
                writer.writerows(listings)
            
            output.seek(0)
            return output.getvalue(), 200, {
                'Content-Type': 'text/csv',
                'Content-Disposition': f'attachment; filename=seller_listings_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
            }
        else:
            return jsonify({
                "data": listings,
                "count": len(listings),
                "exported_at": datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error exporting seller listings: {e}")
        return jsonify({"error": "Failed to export seller listings"}), 500


@app.route("/api/export/selling-analytics", methods=["GET"])
@login_required
@rate_limit('api', max_requests=10)
def api_export_selling_analytics():
    """Export selling analytics data"""
    try:
        stats = db_enhanced.get_seller_listing_stats(current_user.id)
        listings = db_enhanced.get_seller_listings(username=current_user.id, limit=10000)
        
        export_data = {
            "statistics": stats,
            "total_listings": len(listings),
            "listings_by_status": {
                "draft": [l for l in listings if l['status'] == 'draft'],
                "posted": [l for l in listings if l['status'] == 'posted'],
                "sold": [l for l in listings if l['status'] == 'sold'],
                "archived": [l for l in listings if l['status'] == 'archived']
            },
            "exported_at": datetime.now().isoformat(),
            "export_type": "selling_analytics"
        }
        
        db_enhanced.log_user_activity(
            current_user.id,
            'export_selling_analytics',
            'Exported selling analytics data',
            request.remote_addr,
            request.headers.get('User-Agent')
        )
        
        return jsonify(export_data)
            
    except Exception as e:
        logger.error(f"Error exporting selling analytics: {e}")
        return jsonify({"error": "Failed to export selling analytics"}), 500


@app.route("/api/export/market-analytics", methods=["GET"])
@login_required
@rate_limit('api', max_requests=10)
def api_export_market_analytics():
    """Export market analytics data"""
    try:
        days = int(request.args.get('days', 30))
        
        market_insights = db_enhanced.get_market_insights(days=days, user_id=current_user.id)
        keyword_trends = db_enhanced.get_keyword_trends(days=days, user_id=current_user.id)
        
        export_data = {
            "market_insights": market_insights,
            "keyword_trends": keyword_trends,
            "time_range_days": days,
            "exported_at": datetime.now().isoformat(),
            "export_type": "market_analytics"
        }
        
        db_enhanced.log_user_activity(
            current_user.id,
            'export_market_analytics',
            f'Exported market analytics data ({days} days)',
            request.remote_addr,
            request.headers.get('User-Agent')
        )
        
        return jsonify(export_data)
            
    except Exception as e:
        logger.error(f"Error exporting market analytics: {e}")
        return jsonify({"error": "Failed to export market analytics"}), 500


@app.route("/api/export/user-data", methods=["GET"])
@login_required
@rate_limit('api', max_requests=3, window_minutes=60)
def api_export_user_data():
    """Export all user data (GDPR compliance)"""
    try:
        # Get all user data
        user_data = db_enhanced.get_user_by_username(current_user.id)
        settings = db_enhanced.get_settings(current_user.id)
        favorites = db_enhanced.get_favorites(current_user.id, limit=10000)
        searches = db_enhanced.get_saved_searches(current_user.id)
        alerts = db_enhanced.get_price_alerts(current_user.id)
        activity = db_enhanced.get_user_activity(current_user.id, limit=1000)
        subscription = db_enhanced.get_user_subscription(current_user.id)
        
        # Get selling data
        seller_listings = db_enhanced.get_seller_listings(username=current_user.id, limit=10000)
        selling_stats = db_enhanced.get_seller_listing_stats(current_user.id)
        
        # Use named tuple for safe access
        user_row = _user_data_to_row(user_data)
        if not user_row:
            logger.error(
                "Invalid user data structure for %s during export: type=%s keys=%s",
                current_user.id,
                type(user_data),
                list(user_data.keys()) if isinstance(user_data, dict) else None,
            )
            return jsonify({"error": "Failed to export user data"}), 500
        
        export_data = {
            "user_profile": {
                "username": user_row.username,
                "email": user_row.email,
                "verified": user_row.verified,
                "role": user_row.role,
                "created_at": str(user_row.created_at),
                "last_login": str(user_row.last_login) if user_row.last_login else None,
                "login_count": user_row.login_count
            },
            "settings": settings,
            "favorites": favorites,
            "saved_searches": searches,
            "price_alerts": alerts,
            "activity_log": activity,
            "subscription": subscription,
            "seller_listings": seller_listings,
            "selling_statistics": selling_stats,
            "exported_at": datetime.now().isoformat(),
            "export_type": "complete_user_data"
        }
        
        db_enhanced.log_user_activity(
            current_user.id,
            'export_user_data',
            'Exported complete user data',
            request.remote_addr,
            request.headers.get('User-Agent')
        )
        
        return jsonify(export_data)
            
    except Exception as e:
        logger.error(f"Error exporting user data: {e}")
        return jsonify({"error": "Failed to export user data"}), 500


# ======================
# PAGINATION API ROUTES
# ======================

@app.route("/api/listings/paginated", methods=["GET"])
@login_required
@rate_limit('api', max_requests=60)
def api_listings_paginated():
    """Get listings with pagination"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 50, type=int)
        
        # Validate parameters
        if page < 1:
            return jsonify({"error": "Page must be >= 1"}), 400
        if per_page < 1 or per_page > 200:
            return jsonify({"error": "Per page must be between 1 and 200"}), 400
        
        # Calculate offset
        offset = (page - 1) * per_page
        
        # Get total count for current user
        total_count = db_enhanced.get_listing_count(current_user.id)
        
        # Get paginated listings for current user
        listings = db_enhanced.get_listings_paginated(limit=per_page, offset=offset, user_id=current_user.id)
        
        # Calculate pagination info
        total_pages = (total_count + per_page - 1) // per_page
        has_next = page < total_pages
        has_prev = page > 1
        
        return jsonify({
            "listings": listings,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total_items": total_count,
                "total_pages": total_pages,
                "has_next": has_next,
                "has_prev": has_prev,
                "next_page": page + 1 if has_next else None,
                "prev_page": page - 1 if has_prev else None
            }
        })
            
    except Exception as e:
        logger.error(f"Error getting paginated listings: {e}")
        return jsonify({"error": "Failed to get listings"}), 500

# ======================
# ERROR RECOVERY INTEGRATION
# ======================
def initialize_error_recovery():
    """Initialize error recovery system on first request."""
    try:
        start_error_recovery()
        logger.info("Error recovery system initialized")
    except Exception as e:
        logger.error(f"Failed to initialize error recovery system: {e}")

# Initialize error recovery when app starts
initialize_error_recovery()

# Note: Database connections and error recovery stay alive for the worker process lifetime
# Gunicorn/systemd will handle cleanup when the process is terminated
# DO NOT use @app.teardown_appcontext as it fires after EVERY request, not just on shutdown

# ======================
# RUN FLASK (must be last)
# ======================
if __name__ == "__main__":
    try:
        # Initialize database on startup
        db_enhanced.init_db()
        
        # Validate Stripe configuration
        from subscriptions import validate_stripe_config
        is_valid, issues = validate_stripe_config()
        if not is_valid:
            logger.warning("Starting with incomplete Stripe configuration. Some features may not work.")
        
        logger.info("=" * 80)
        logger.info("Starting Super-Bot Application v2.0 (Enhanced + Feature-Rich)")
        logger.info("=" * 80)
        logger.info("[OK] Core: Connection Pooling, Rate Limiting, Caching, User Roles")
        logger.info("[OK] Auth: Email Verification, Password Reset")
        logger.info("[OK] Features: Favorites, Saved Searches, Price Alerts")
        logger.info("[OK] Export: GDPR Compliance, CSV/JSON Export")
        logger.info("[OK] Real-Time: WebSocket Notifications")
        logger.info("[OK] API: 40+ Endpoints, Swagger Documentation at /api-docs")
        logger.info("=" * 80)
        
        # Run with SocketIO support
        # Use environment variables for production deployment
        port = int(os.getenv('PORT', 5000))
        debug = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
        socketio.run(app, host="0.0.0.0", port=port, debug=debug, allow_unsafe_werkzeug=True)
    except Exception as e:
        logger.error(f"Failed to start application: {e}")
        handle_error(e, "application", "startup")
