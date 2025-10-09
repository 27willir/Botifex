from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_wtf.csrf import CSRFProtect
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from pathlib import Path
from werkzeug.security import generate_password_hash, check_password_hash
from scraper_thread import (
    start_facebook, stop_facebook, is_facebook_running,
    start_craigslist, stop_craigslist, is_craigslist_running,
    start_ksl, stop_ksl, is_ksl_running,
)
from db import (
    get_settings, update_setting, get_listings, save_listing,
    get_user_by_username, create_user_db, init_db, get_all_users,
    get_keyword_trends, get_price_analytics, get_source_comparison,
    get_keyword_analysis, get_hourly_activity, get_price_distribution,
    get_market_insights, update_keyword_trends
)
from security import SecurityConfig
from error_handling import ErrorHandler, log_errors, safe_execute, DatabaseError
from error_recovery import start_error_recovery, stop_error_recovery, handle_error, get_system_status
from utils import logger
import json
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = SecurityConfig.get_secret_key()

# Configure session security
SecurityConfig.setup_session_security(app)

# Initialize CSRF protection
csrf = CSRFProtect(app)

# ======================
# FLASK-LOGIN SETUP
# ======================
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

class User(UserMixin):
    def __init__(self, username, password_hash):
        self.id = username
        self.password_hash = password_hash

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
        existing_user = ErrorHandler.handle_database_error(get_user_by_username, username)
        if existing_user:
            logger.warning(f"Registration attempt with existing username: {username}")
            return False, "Username already exists"
        
        # Check if email already exists
        all_users = ErrorHandler.handle_database_error(get_all_users)
        for user in all_users:
            if user[1] == email:  # email is at index 1
                logger.warning(f"Registration attempt with existing email: {email}")
                return False, "Email already registered"
        
        # Hash password securely
        hashed = SecurityConfig.hash_password(password)
        success = ErrorHandler.handle_database_error(create_user_db, username, email, hashed)
        if success:
            logger.info(f"User created successfully: {username}")
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
        user_data = ErrorHandler.handle_database_error(get_user_by_username, user_id)
        if user_data:
            return User(user_data[0], user_data[2])  # username, password
        return None
    except Exception as e:
        logger.error(f"Error loading user {user_id}: {e}")
        return None


# ======================
# SETTINGS MANAGEMENT
# ======================

@log_errors()
def get_user_settings():
    """Get settings for the current user from database"""
    try:
        if not current_user.is_authenticated:
            logger.debug("Getting default settings for unauthenticated user")
            return get_default_settings()
        
        settings = ErrorHandler.handle_database_error(get_settings, current_user.id)
        # Set default values if missing
        default_settings = get_default_settings()
        for key, value in default_settings.items():
            if key not in settings:
                settings[key] = value
                logger.debug(f"Using default value for missing setting: {key}")
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
            ErrorHandler.handle_database_error(update_setting, key, value, current_user.id)
            logger.debug(f"Updated setting {key} for user {current_user.id}")
        else:
            # For unauthenticated users, update global settings
            ErrorHandler.handle_database_error(update_setting, key, value, None)
            logger.debug(f"Updated global setting {key}")
    except Exception as e:
        logger.error(f"Error updating setting {key}: {e}")
        raise

# ======================
# LISTINGS STORAGE
# ======================

def get_listings_from_db(limit=200):
    """Get listings from database"""
    return get_listings(limit)

# ======================
# ROUTES
# ======================
@app.route("/login", methods=["GET", "POST"])
@log_errors()
def login():
    if request.method == "POST":
        try:
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            
            # Sanitize username input
            username = SecurityConfig.sanitize_input(username)
            
            if not username or not password:
                logger.warning("Login attempt with missing credentials")
                flash("Username and password are required", "error")
                return render_template("login.html")
            
            user_data = ErrorHandler.handle_database_error(get_user_by_username, username)
            if user_data:
                if SecurityConfig.verify_password(user_data[2], password):  # password is at index 2
                    user = User(username, user_data[2])
                    login_user(user, remember=True)
                    session.permanent = True
                    logger.info(f"Successful login for user: {username}")
                    # Don't flash success message here - redirect immediately to avoid duplicate messages
                    return redirect(url_for("index"))
                else:
                    logger.warning(f"Invalid password for user: {username}")
                    flash("Invalid password", "error")
            else:
                logger.warning(f"Login attempt for non-existent user: {username}")
                flash("User not found", "error")
            
            return render_template("login.html")
        except Exception as e:
            logger.error(f"Error during login process: {e}")
            flash("An error occurred during login. Please try again.", "error")
            return render_template("login.html")
    
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))

@app.route("/")
@login_required
def index():
    listings = get_listings_from_db()
    settings = get_user_settings()
    status = {
        "facebook": is_facebook_running(),
        "craigslist": is_craigslist_running(),
        "ksl": is_ksl_running(),
    }
    return render_template("index.html", listings=listings, settings=settings, status=status)

# Start/Stop routes
@app.route("/start/<site>")
@login_required
def start(site):
    if site == "facebook":
        start_facebook()
    elif site == "craigslist":
        start_craigslist()
    elif site == "ksl":
        start_ksl()
    return redirect(url_for("index"))

@app.route("/stop/<site>")
@login_required
def stop(site):
    if site == "facebook":
        stop_facebook()
    elif site == "craigslist":
        stop_craigslist()
    elif site == "ksl":
        stop_ksl()
    return redirect(url_for("index"))

# Settings page
@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "GET":
        settings = get_user_settings()
        return render_template("settings.html", settings=settings)
    
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
    
    flash("Settings updated successfully!", "success")

    return redirect(url_for("index"))

@app.route("/update_settings", methods=["POST"])
@login_required
def update_settings():
    """Update settings from the index page form"""
    try:
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
                        flash("Radius must be between 1 and 500 miles", "error")
                        return redirect(url_for("index"))
                except ValueError:
                    flash("Invalid radius value", "error")
                    return redirect(url_for("index"))

            if min_price:
                try:
                    min_price_val = int(min_price)
                    if min_price_val < 0:
                        flash("Minimum price cannot be negative", "error")
                        return redirect(url_for("index"))
                except ValueError:
                    flash("Invalid minimum price value", "error")
                    return redirect(url_for("index"))

            if max_price:
                try:
                    max_price_val = int(max_price)
                    if max_price_val < 0:
                        flash("Maximum price cannot be negative", "error")
                        return redirect(url_for("index"))
                except ValueError:
                    flash("Invalid maximum price value", "error")
                    return redirect(url_for("index"))

            if interval:
                try:
                    interval_val = int(interval)
                    if interval_val < 10 or interval_val > 1440:
                        flash("Interval must be between 10 and 1440 minutes", "error")
                        return redirect(url_for("index"))
                except ValueError:
                    flash("Invalid interval value", "error")
                    return redirect(url_for("index"))

        except Exception as e:
            logger.error(f"Unexpected error during settings validation: {e}")
            flash("An error occurred while validating settings", "error")
            return redirect(url_for("index"))

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
        
        flash("Settings updated successfully!", "success")
        return redirect(url_for("index"))

    except Exception as e:
        logger.error(f"Error updating settings: {e}")
        flash("An error occurred while updating settings", "error")
        return redirect(url_for("index"))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        email = request.form.get("email", "").strip()
        
        success, msg = create_user(username, password, email)
        if success:
            flash("Registration successful! Please log in.", "success")
            return redirect(url_for("login"))
        else:
            flash(msg, "error")
    
    return render_template("register.html")

@app.route("/analytics")
@login_required
def analytics():
    """Analytics dashboard page"""
    return render_template("analytics.html")

# ======================
# CLEAN API ROUTES
# ======================
from flask import jsonify

@app.route("/api/status")
@login_required
@csrf.exempt
def api_status():
    return jsonify({
        "facebook": is_facebook_running(),
        "craigslist": is_craigslist_running(),
        "ksl": is_ksl_running()
    })

@app.route("/api/listings")
@login_required
@csrf.exempt
def api_listings():
    return jsonify({"listings": get_listings_from_db(50)})

@app.route("/api/system-status")
@login_required
@csrf.exempt
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
@csrf.exempt
def api_market_insights():
    """Get comprehensive market insights"""
    try:
        days = request.args.get('days', 30, type=int)
        insights = get_market_insights(days)
        return jsonify(insights)
    except Exception as e:
        logger.error(f"Error getting market insights: {e}")
        return jsonify({"error": "Failed to get market insights"}), 500

@app.route("/api/analytics/keyword-trends")
@login_required
@csrf.exempt
def api_keyword_trends():
    """Get keyword trends over time"""
    try:
        days = request.args.get('days', 30, type=int)
        keyword = request.args.get('keyword')
        trends = get_keyword_trends(days, keyword)
        return jsonify({"trends": trends})
    except Exception as e:
        logger.error(f"Error getting keyword trends: {e}")
        return jsonify({"error": "Failed to get keyword trends"}), 500

@app.route("/api/analytics/price-analytics")
@login_required
@csrf.exempt
def api_price_analytics():
    """Get price analytics over time"""
    try:
        days = request.args.get('days', 30, type=int)
        source = request.args.get('source')
        analytics = get_price_analytics(days, source)
        return jsonify({"analytics": analytics})
    except Exception as e:
        logger.error(f"Error getting price analytics: {e}")
        return jsonify({"error": "Failed to get price analytics"}), 500

@app.route("/api/analytics/source-comparison")
@login_required
@csrf.exempt
def api_source_comparison():
    """Compare performance across different sources"""
    try:
        days = request.args.get('days', 30, type=int)
        comparison = get_source_comparison(days)
        return jsonify({"comparison": comparison})
    except Exception as e:
        logger.error(f"Error getting source comparison: {e}")
        return jsonify({"error": "Failed to get source comparison"}), 500

@app.route("/api/analytics/keyword-analysis")
@login_required
@csrf.exempt
def api_keyword_analysis():
    """Get top keywords and their performance"""
    try:
        days = request.args.get('days', 30, type=int)
        limit = request.args.get('limit', 20, type=int)
        analysis = get_keyword_analysis(days, limit)
        return jsonify({"analysis": analysis})
    except Exception as e:
        logger.error(f"Error getting keyword analysis: {e}")
        return jsonify({"error": "Failed to get keyword analysis"}), 500

@app.route("/api/analytics/hourly-activity")
@login_required
@csrf.exempt
def api_hourly_activity():
    """Get listing activity by hour of day"""
    try:
        days = request.args.get('days', 7, type=int)
        activity = get_hourly_activity(days)
        return jsonify({"activity": activity})
    except Exception as e:
        logger.error(f"Error getting hourly activity: {e}")
        return jsonify({"error": "Failed to get hourly activity"}), 500

@app.route("/api/analytics/price-distribution")
@login_required
@csrf.exempt
def api_price_distribution():
    """Get price distribution data for histograms"""
    try:
        days = request.args.get('days', 30, type=int)
        bins = request.args.get('bins', 10, type=int)
        distribution = get_price_distribution(days, bins)
        return jsonify({"distribution": distribution})
    except Exception as e:
        logger.error(f"Error getting price distribution: {e}")
        return jsonify({"error": "Failed to get price distribution"}), 500

@app.route("/api/analytics/update-trends", methods=["POST"])
@login_required
@csrf.exempt
def api_update_trends():
    """Update keyword trends from recent listings"""
    try:
        update_keyword_trends()
        return jsonify({"message": "Trends updated successfully"})
    except Exception as e:
        logger.error(f"Error updating trends: {e}")
        return jsonify({"error": "Failed to update trends"}), 500

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

@app.teardown_appcontext
def cleanup_error_recovery(exception):
    """Cleanup error recovery system on app shutdown."""
    try:
        stop_error_recovery()
    except Exception as e:
        logger.error(f"Error during error recovery cleanup: {e}")

# ======================
# RUN FLASK (must be last)
# ======================
if __name__ == "__main__":
    try:
        # Initialize database on startup
        init_db()
        logger.info("Starting super-bot application")
        app.run(host="0.0.0.0", port=5000, debug=True)
    except Exception as e:
        logger.error(f"Failed to start application: {e}")
        handle_error(e, "application", "startup")
