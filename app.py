from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_wtf.csrf import CSRFProtect
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_session import Session
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
from utils import logger
# Import new modules
from rate_limiter import rate_limit, add_rate_limit_headers
from cache_manager import cache_get, cache_set, cache_clear, cache_user_data, get_cache
from admin_panel import admin_bp
from security_middleware import security_before_request, security_after_request, get_security_stats
from honeypot_routes import create_honeypot_routes, get_honeypot_stats
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
import json
import os
from dotenv import load_dotenv
from datetime import datetime

# Define named tuples for database row access
UserRow = namedtuple('UserRow', ['username', 'email', 'password', 'verified', 'role', 'active', 'created_at', 'last_login', 'login_count'])
ListingRow = namedtuple('ListingRow', ['id', 'title', 'price', 'link', 'image_url', 'source', 'created_at'])

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

# Initialize WebSocket support
from websocket_manager import init_socketio
socketio = init_socketio(app)

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

# Add rate limit headers to all responses
@app.after_request
def after_request(response):
    response = add_rate_limit_headers(response)
    return security_after_request(response)

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
        if user_data:
            # Use named tuple for safe access
            try:
                user_row = UserRow._make(user_data)
                user = User(user_row.username, user_row.password, user_row.role)
                # Cache user object for 5 minutes
                cache_set(cache_key, user, ttl=300)
                return user
            except (TypeError, ValueError) as e:
                logger.error(f"Invalid user data structure for {user_id}: {e}")
                return None
        return None
    except Exception as e:
        logger.error(f"Error loading user {user_id}: {e}")
        return None


# ======================
# SETTINGS MANAGEMENT
# ======================

@log_errors()
def get_user_settings():
    """Get settings for the current user from database with caching"""
    try:
        if not current_user.is_authenticated:
            logger.debug("Getting default settings for unauthenticated user")
            return get_default_settings()
        
        # Try cache first
        cache_key = f"settings:{current_user.id}"
        cached_settings = cache_get(cache_key)
        if cached_settings:
            return cached_settings
        
        settings = ErrorHandler.handle_database_error(db_enhanced.get_settings, current_user.id)
        # Set default values if missing
        default_settings = get_default_settings()
        for key, value in default_settings.items():
            if key not in settings:
                settings[key] = value
                logger.debug(f"Using default value for missing setting: {key}")
        
        # Cache settings for 5 minutes
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
        "interval": "60",
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
    # Cache for 2 minutes
    cache_set(cache_key, listings, ttl=120)
    return listings

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
            if user_data:
                # Use named tuple for safe access
                try:
                    user_row = UserRow._make(user_data)
                except (TypeError, ValueError) as e:
                    logger.error(f"Invalid user data structure for {username}: {e}")
                    flash("Database error. Please contact administrator.", "error")
                    return render_template("login.html")
                
                # Check if user is active
                if not user_row.active:
                    logger.warning(f"Login attempt for deactivated user: {username}")
                    flash("Account deactivated. Please contact administrator.", "error")
                    return render_template("login.html")
                
                if SecurityConfig.verify_password(user_row.password, password):
                    # Check if email is verified (only if email verification is configured)
                    if is_email_configured() and not user_row.verified:
                        logger.warning(f"Login attempt for unverified user: {username}")
                        flash("Please verify your email address before logging in. Check your inbox for the verification link.", "warning")
                        # Show option to resend verification email
                        return render_template("login.html", unverified_user=username)
                    
                    user = User(username, user_row.password, user_row.role)
                    login_user(user, remember=True)
                    session.permanent = True
                    
                    # Batch database operations to reduce timeouts
                    try:
                        # Update login tracking and log activity in a single transaction
                        db_enhanced.update_user_login_and_log_activity(
                            username, 
                            request.remote_addr, 
                            request.headers.get('User-Agent')
                        )
                    except Exception as e:
                        logger.warning(f"Failed to log login activity for {username}: {e}")
                        # Don't fail login if logging fails
                    
                    logger.info(f"Successful login for user: {username}")
                    return redirect(url_for("dashboard"))
                else:
                    logger.warning(f"Invalid password for user: {username}")
                    # Log failed attempt asynchronously to avoid blocking
                    try:
                        db_enhanced.log_user_activity(
                            username, 
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
        
        return jsonify({
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "database": "connected",
            "background_threads": {
                "security_logger": security_logger_status,
                "activity_logger": activity_logger_status
            },
            "queue_sizes": {
                "security_log_queue": _security_log_queue.qsize(),
                "activity_log_queue": db_enhanced._activity_log_queue.qsize()
            }
        }), 200
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({
            "status": "unhealthy",
            "timestamp": datetime.now().isoformat(),
            "error": str(e)
        }), 500

@app.route("/")
def landing():
    """Public landing page"""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template("landing.html")

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
                db_enhanced.record_tos_agreement(username)
                logger.info(f"ToS agreement recorded for user: {username}")
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
        try:
            user_row = UserRow._make(user_data)
        except (TypeError, ValueError) as e:
            logger.error(f"Invalid user data structure for email {email}: {e}")
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

@app.route("/profile")
@login_required
@rate_limit('api', max_requests=60)
def profile_page():
    """User profile management page"""
    try:
        logger.info(f"Loading profile for user: {current_user.id}")
        try:
            user_data = db_enhanced.get_user_by_username(current_user.id)
            logger.info(f"User data retrieved: {user_data}")
        except Exception as db_error:
            logger.error(f"Database error retrieving user {current_user.id}: {db_error}")
            flash("Database error. Please try again.", "error")
            return redirect(url_for("dashboard"))
        
        if not user_data:
            logger.error(f"No user data found for {current_user.id}")
            flash("User not found. Please contact support.", "error")
            return redirect(url_for("dashboard"))
        
        notifications = db_enhanced.get_notification_preferences(current_user.id)
        subscription = db_enhanced.get_user_subscription(current_user.id)
        activity = db_enhanced.get_user_activity(current_user.id, limit=20)
        
        # Use named tuple for safe access
        try:
            user_row = UserRow._make(user_data)
        except (TypeError, ValueError) as e:
            logger.error(f"Invalid user data structure for {current_user.id}: {e}")
            logger.error(f"User data: {user_data}")
            flash("Database error. Please try again.", "error")
            return redirect(url_for("dashboard"))
        
        # Override subscription for admins to show pro tier
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
        
        profile = {
            'username': user_row.username,
            'email': user_row.email,
            'verified': user_row.verified,
            'role': user_row.role,
            'created_at': user_row.created_at,
            'last_login': user_row.last_login,
            'login_count': user_row.login_count
        }
        
        return render_template("profile.html", 
                             profile=profile,
                             notifications=notifications,
                             subscription=subscription,
                             activity=activity)
    except Exception as e:
        logger.error(f"Error loading profile page: {e}")
        flash("Error loading profile", "error")
        return redirect(url_for("dashboard"))

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
        
        # Use named tuple for safe access
        try:
            user_row = UserRow._make(user_data)
        except (TypeError, ValueError) as e:
            logger.error(f"Invalid user data structure for {current_user.id}: {e}")
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
        try:
            user_row = UserRow._make(user_data)
        except (TypeError, ValueError) as e:
            logger.error(f"Invalid user data structure for {current_user.id}: {e}")
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
