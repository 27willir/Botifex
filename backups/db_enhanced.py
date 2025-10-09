# db_enhanced.py - Enhanced database module for handling 1000+ users
import sqlite3
import threading
from datetime import datetime
from contextlib import contextmanager
from queue import Queue, Empty
from error_handling import ErrorHandler, log_errors, DatabaseError
from utils import logger

DB_FILE = "superbot.db"

# Connection pool configuration
POOL_SIZE = 10  # Number of connections to maintain in pool
CONNECTION_TIMEOUT = 30  # Timeout for getting connection from pool


class DatabaseConnectionPool:
    """Thread-safe connection pool for SQLite"""
    
    def __init__(self, database, pool_size=POOL_SIZE):
        self.database = database
        self.pool_size = pool_size
        self.pool = Queue(maxsize=pool_size)
        self.all_connections = []
        self.lock = threading.Lock()
        self._initialize_pool()
    
    def _initialize_pool(self):
        """Initialize the connection pool"""
        for _ in range(self.pool_size):
            conn = self._create_connection()
            self.pool.put(conn)
            self.all_connections.append(conn)
        logger.info(f"Initialized database connection pool with {self.pool_size} connections")
    
    def _create_connection(self):
        """Create a new database connection with optimal settings"""
        conn = sqlite3.connect(
            self.database,
            check_same_thread=False,
            timeout=CONNECTION_TIMEOUT
        )
        # Enable WAL mode for better concurrent access
        conn.execute("PRAGMA journal_mode=WAL")
        # Enable foreign keys
        conn.execute("PRAGMA foreign_keys=ON")
        # Set busy timeout
        conn.execute(f"PRAGMA busy_timeout={CONNECTION_TIMEOUT * 1000}")
        return conn
    
    @contextmanager
    def get_connection(self):
        """Get a connection from the pool (context manager)"""
        conn = None
        try:
            conn = self.pool.get(timeout=CONNECTION_TIMEOUT)
            yield conn
        except Empty:
            logger.error("Connection pool exhausted - consider increasing pool size")
            raise DatabaseError("Database connection pool exhausted")
        finally:
            if conn:
                self.pool.put(conn)
    
    def close_all(self):
        """Close all connections in the pool"""
        with self.lock:
            for conn in self.all_connections:
                try:
                    conn.close()
                except Exception as e:
                    logger.error(f"Error closing connection: {e}")
            self.all_connections.clear()
            logger.info("Closed all database connections")


# Global connection pool
_connection_pool = None


def get_pool():
    """Get or create the global connection pool"""
    global _connection_pool
    if _connection_pool is None:
        _connection_pool = DatabaseConnectionPool(DB_FILE)
    return _connection_pool


@log_errors()
def init_db():
    """Initialize database with all required tables and indexes"""
    try:
        with get_pool().get_connection() as conn:
            c = conn.cursor()
            
            # Listings table
            c.execute("""
                CREATE TABLE IF NOT EXISTS listings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT,
                    price INTEGER,
                    link TEXT UNIQUE,
                    image_url TEXT,
                    source TEXT,
                    created_at DATETIME,
                    user_id TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (username)
                )
            """)
            
            # Settings table - supports user-specific settings
            c.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT,
                    key TEXT,
                    value TEXT,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(username, key),
                    FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)
            
            # Users table with enhanced fields
            c.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    role TEXT DEFAULT 'user',
                    verified BOOLEAN DEFAULT 1,
                    active BOOLEAN DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_login DATETIME,
                    login_count INTEGER DEFAULT 0
                )
            """)
            
            # User activity logging table
            c.execute("""
                CREATE TABLE IF NOT EXISTS user_activity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT,
                    action TEXT,
                    details TEXT,
                    ip_address TEXT,
                    user_agent TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)
            
            # Rate limiting table
            c.execute("""
                CREATE TABLE IF NOT EXISTS rate_limits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT,
                    endpoint TEXT,
                    request_count INTEGER DEFAULT 1,
                    window_start DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(username, endpoint)
                )
            """)
            
            # User scraper management table
            c.execute("""
                CREATE TABLE IF NOT EXISTS user_scrapers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT,
                    scraper_name TEXT,
                    is_running BOOLEAN DEFAULT 0,
                    last_run DATETIME,
                    run_count INTEGER DEFAULT 0,
                    UNIQUE(username, scraper_name),
                    FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)
            
            # Analytics tables for market insights
            c.execute("""
                CREATE TABLE IF NOT EXISTS listing_analytics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    listing_id INTEGER,
                    keyword TEXT,
                    category TEXT,
                    price_range TEXT,
                    source TEXT,
                    created_at DATETIME,
                    FOREIGN KEY (listing_id) REFERENCES listings (id) ON DELETE CASCADE
                )
            """)
            
            c.execute("""
                CREATE TABLE IF NOT EXISTS keyword_trends (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    keyword TEXT,
                    count INTEGER,
                    avg_price REAL,
                    date DATE,
                    source TEXT
                )
            """)
            
            c.execute("""
                CREATE TABLE IF NOT EXISTS price_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    listing_id INTEGER,
                    price INTEGER,
                    recorded_at DATETIME,
                    FOREIGN KEY (listing_id) REFERENCES listings (id) ON DELETE CASCADE
                )
            """)
            
            c.execute("""
                CREATE TABLE IF NOT EXISTS market_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date DATE,
                    total_listings INTEGER,
                    avg_price REAL,
                    min_price INTEGER,
                    max_price INTEGER,
                    source TEXT,
                    category TEXT
                )
            """)
            
            # Create comprehensive indexes for performance
            indexes = [
                "CREATE INDEX IF NOT EXISTS idx_listings_created_at ON listings(created_at)",
                "CREATE INDEX IF NOT EXISTS idx_listings_source ON listings(source)",
                "CREATE INDEX IF NOT EXISTS idx_listings_price ON listings(price)",
                "CREATE INDEX IF NOT EXISTS idx_listings_user_id ON listings(user_id)",
                "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)",
                "CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)",
                "CREATE INDEX IF NOT EXISTS idx_users_role ON users(role)",
                "CREATE INDEX IF NOT EXISTS idx_activity_username ON user_activity(username)",
                "CREATE INDEX IF NOT EXISTS idx_activity_timestamp ON user_activity(timestamp)",
                "CREATE INDEX IF NOT EXISTS idx_activity_action ON user_activity(action)",
                "CREATE INDEX IF NOT EXISTS idx_analytics_keyword ON listing_analytics(keyword)",
                "CREATE INDEX IF NOT EXISTS idx_analytics_date ON listing_analytics(created_at)",
                "CREATE INDEX IF NOT EXISTS idx_trends_date ON keyword_trends(date)",
                "CREATE INDEX IF NOT EXISTS idx_trends_keyword ON keyword_trends(keyword)",
                "CREATE INDEX IF NOT EXISTS idx_market_stats_date ON market_stats(date)",
                "CREATE INDEX IF NOT EXISTS idx_rate_limits_username ON rate_limits(username)",
                "CREATE INDEX IF NOT EXISTS idx_rate_limits_endpoint ON rate_limits(endpoint)",
                "CREATE INDEX IF NOT EXISTS idx_settings_username ON settings(username)",
            ]
            
            for index_sql in indexes:
                c.execute(index_sql)
            
            conn.commit()
            logger.info("Database initialized successfully with all tables and indexes")
    except sqlite3.Error as e:
        logger.error(f"Database initialization error: {e}")
        raise DatabaseError(f"Failed to initialize database: {e}")
    except Exception as e:
        logger.error(f"Unexpected error initializing database: {e}")
        raise


# ======================
# USER MANAGEMENT
# ======================

@log_errors()
def get_user_by_username(username):
    """Get user by username"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT username, email, password, verified, role, active, created_at, last_login, login_count 
            FROM users WHERE username = ?
        """, (username,))
        user = c.fetchone()
        return user


@log_errors()
def get_user_by_email(email):
    """Get user by email"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT username, email, password, verified, role, active 
            FROM users WHERE email = ?
        """, (email,))
        user = c.fetchone()
        return user


@log_errors()
def create_user_db(username, email, password_hash, role='user'):
    """Create a new user in the database"""
    try:
        with get_pool().get_connection() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO users (username, email, password, role, created_at) 
                VALUES (?, ?, ?, ?, ?)
            """, (username, email, password_hash, role, datetime.now()))
            conn.commit()
            logger.info(f"Created new user: {username} with role: {role}")
            return True
    except sqlite3.IntegrityError as e:
        logger.warning(f"User creation failed (integrity error): {e}")
        return False


@log_errors()
def update_user_login(username):
    """Update user login timestamp and count"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            UPDATE users 
            SET last_login = ?, login_count = login_count + 1 
            WHERE username = ?
        """, (datetime.now(), username))
        conn.commit()


@log_errors()
def get_all_users():
    """Get all users from database"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT username, email, password, verified, role, active, created_at, last_login, login_count 
            FROM users ORDER BY created_at DESC
        """)
        users = c.fetchall()
        return users


@log_errors()
def get_user_count():
    """Get total number of users"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users")
        count = c.fetchone()[0]
        return count


@log_errors()
def update_user_role(username, role):
    """Update user role"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("UPDATE users SET role = ? WHERE username = ?", (role, username))
        conn.commit()
        logger.info(f"Updated role for user {username} to {role}")


@log_errors()
def deactivate_user(username):
    """Deactivate a user account"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("UPDATE users SET active = 0 WHERE username = ?", (username,))
        conn.commit()
        logger.info(f"Deactivated user: {username}")


# ======================
# SETTINGS MANAGEMENT
# ======================

@log_errors()
def get_settings(username=None):
    """Get settings for a specific user, or global settings if username is None"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        if username:
            c.execute("SELECT key, value FROM settings WHERE username = ?", (username,))
        else:
            c.execute("SELECT key, value FROM settings WHERE username IS NULL")
        settings = dict(c.fetchall())
        return settings


@log_errors()
def update_setting(key, value, username=None):
    """Update setting for a specific user, or global setting if username is None"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT OR REPLACE INTO settings (username, key, value, updated_at) 
            VALUES (?, ?, ?, ?)
        """, (username, key, value, datetime.now()))
        conn.commit()


# ======================
# USER ACTIVITY LOGGING
# ======================

@log_errors()
def log_user_activity(username, action, details=None, ip_address=None, user_agent=None):
    """Log user activity for monitoring and security"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO user_activity (username, action, details, ip_address, user_agent, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (username, action, details, ip_address, user_agent, datetime.now()))
        conn.commit()


@log_errors()
def get_user_activity(username, limit=100):
    """Get recent activity for a user"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT action, details, ip_address, timestamp 
            FROM user_activity 
            WHERE username = ? 
            ORDER BY timestamp DESC 
            LIMIT ?
        """, (username, limit))
        activity = c.fetchall()
        return activity


@log_errors()
def get_recent_activity(limit=100):
    """Get recent activity across all users (admin function)"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT username, action, details, ip_address, timestamp 
            FROM user_activity 
            ORDER BY timestamp DESC 
            LIMIT ?
        """, (limit,))
        activity = c.fetchall()
        return activity


# ======================
# RATE LIMITING
# ======================

@log_errors()
def check_rate_limit(username, endpoint, max_requests=60, window_minutes=1):
    """
    Check if user has exceeded rate limit for an endpoint
    Returns: (is_allowed, remaining_requests)
    """
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        # Get current rate limit record
        c.execute("""
            SELECT request_count, window_start 
            FROM rate_limits 
            WHERE username = ? AND endpoint = ?
        """, (username, endpoint))
        
        result = c.fetchone()
        now = datetime.now()
        
        if result:
            request_count, window_start = result
            window_start = datetime.fromisoformat(window_start)
            
            # Check if we're still in the same window
            time_diff = (now - window_start).total_seconds() / 60
            
            if time_diff < window_minutes:
                # Still in same window
                if request_count >= max_requests:
                    logger.warning(f"Rate limit exceeded for {username} on {endpoint}")
                    return False, 0
                
                # Increment count
                c.execute("""
                    UPDATE rate_limits 
                    SET request_count = request_count + 1 
                    WHERE username = ? AND endpoint = ?
                """, (username, endpoint))
                conn.commit()
                return True, max_requests - request_count - 1
            else:
                # New window - reset
                c.execute("""
                    UPDATE rate_limits 
                    SET request_count = 1, window_start = ? 
                    WHERE username = ? AND endpoint = ?
                """, (now, username, endpoint))
                conn.commit()
                return True, max_requests - 1
        else:
            # First request
            c.execute("""
                INSERT INTO rate_limits (username, endpoint, request_count, window_start) 
                VALUES (?, ?, 1, ?)
            """, (username, endpoint, now))
            conn.commit()
            return True, max_requests - 1


@log_errors()
def reset_rate_limit(username, endpoint=None):
    """Reset rate limit for a user (admin function)"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        if endpoint:
            c.execute("DELETE FROM rate_limits WHERE username = ? AND endpoint = ?", (username, endpoint))
        else:
            c.execute("DELETE FROM rate_limits WHERE username = ?", (username,))
        conn.commit()
        logger.info(f"Reset rate limits for user: {username}")


# ======================
# LISTINGS MANAGEMENT
# ======================

@log_errors()
def save_listing(title, price, link, image_url=None, source=None, user_id=None):
    """Save a listing to the database"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        # Insert the listing
        c.execute("""
            INSERT OR IGNORE INTO listings (title, price, link, image_url, source, created_at, user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (title, price, link, image_url, source, datetime.now(), user_id))
        
        # Get the listing ID for analytics
        listing_id = c.lastrowid
        if listing_id == 0:  # If no new row was inserted (duplicate)
            c.execute("SELECT id FROM listings WHERE link = ?", (link,))
            result = c.fetchone()
            listing_id = result[0] if result else None
        
        conn.commit()
        
        # Save analytics data if we have a valid listing ID
        if listing_id:
            try:
                # Extract keywords from title
                title_lower = title.lower()
                car_keywords = ['firebird', 'camaro', 'corvette', 'mustang', 'charger', 'challenger', 
                               'trans am', 'gto', 'nova', 'chevelle', 'impala', 'monte carlo']
                
                for keyword in car_keywords:
                    if keyword in title_lower:
                        # Determine price range
                        if price < 5000:
                            price_range = "Under $5K"
                        elif price < 10000:
                            price_range = "$5K-$10K"
                        elif price < 20000:
                            price_range = "$10K-$20K"
                        elif price < 30000:
                            price_range = "$20K-$30K"
                        else:
                            price_range = "Over $30K"
                        
                        # Determine category
                        category = "Classic Cars" if any(k in title_lower for k in ['firebird', 'camaro', 'corvette', 'trans am', 'gto', 'nova', 'chevelle', 'impala', 'monte carlo']) else "Modern Cars"
                        
                        save_listing_analytics(listing_id, keyword, category, price_range, source)
            except Exception as e:
                logger.error(f"Error saving analytics for listing {listing_id}: {e}")
        
        return listing_id


@log_errors()
def get_listings(limit=100, user_id=None):
    """Get listings from database, optionally filtered by user"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        if user_id:
            c.execute("""
                SELECT title, price, link, image_url, source, created_at 
                FROM listings 
                WHERE user_id = ? 
                ORDER BY created_at DESC 
                LIMIT ?
            """, (user_id, limit))
        else:
            c.execute("""
                SELECT title, price, link, image_url, source, created_at 
                FROM listings 
                ORDER BY created_at DESC 
                LIMIT ?
            """, (limit,))
        rows = c.fetchall()
        return rows


@log_errors()
def get_listing_count(user_id=None):
    """Get total number of listings, optionally for a specific user"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        if user_id:
            c.execute("SELECT COUNT(*) FROM listings WHERE user_id = ?", (user_id,))
        else:
            c.execute("SELECT COUNT(*) FROM listings")
        count = c.fetchone()[0]
        return count


# ======================
# ANALYTICS FUNCTIONS (from original db.py)
# ======================

@log_errors()
def save_listing_analytics(listing_id, keyword, category, price_range, source):
    """Save analytics data for a listing"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO listing_analytics (listing_id, keyword, category, price_range, source, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (listing_id, keyword, category, price_range, source, datetime.now()))
        conn.commit()


@log_errors()
def get_keyword_trends(days=30, keyword=None):
    """Get keyword trends over time"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        if keyword:
            c.execute("""
                SELECT date, keyword, count, avg_price, source
                FROM keyword_trends 
                WHERE date >= date('now', '-{} days') AND keyword = ?
                ORDER BY date DESC
            """.format(days), (keyword,))
        else:
            c.execute("""
                SELECT date, keyword, count, avg_price, source
                FROM keyword_trends 
                WHERE date >= date('now', '-{} days')
                ORDER BY date DESC, count DESC
            """.format(days))
        
        rows = c.fetchall()
        return rows


@log_errors()
def get_price_analytics(days=30, source=None):
    """Get price analytics over time"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        if source:
            c.execute("""
                SELECT DATE(created_at) as date, 
                       COUNT(*) as count,
                       AVG(price) as avg_price,
                       MIN(price) as min_price,
                       MAX(price) as max_price,
                       source
                FROM listings 
                WHERE created_at >= datetime('now', '-{} days') AND source = ?
                GROUP BY DATE(created_at), source
                ORDER BY date DESC
            """.format(days), (source,))
        else:
            c.execute("""
                SELECT DATE(created_at) as date, 
                       COUNT(*) as count,
                       AVG(price) as avg_price,
                       MIN(price) as min_price,
                       MAX(price) as max_price,
                       source
                FROM listings 
                WHERE created_at >= datetime('now', '-{} days')
                GROUP BY DATE(created_at), source
                ORDER BY date DESC
            """.format(days))
        
        rows = c.fetchall()
        return rows


@log_errors()
def get_source_comparison(days=30):
    """Compare performance across different sources"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT source,
                   COUNT(*) as total_listings,
                   AVG(price) as avg_price,
                   MIN(price) as min_price,
                   MAX(price) as max_price,
                   COUNT(DISTINCT DATE(created_at)) as active_days
            FROM listings 
            WHERE created_at >= datetime('now', '-{} days')
            GROUP BY source
            ORDER BY total_listings DESC
        """.format(days))
        
        rows = c.fetchall()
        return rows


@log_errors()
def get_keyword_analysis(days=30, limit=20):
    """Get top keywords and their performance"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT la.keyword,
                   COUNT(*) as frequency,
                   AVG(l.price) as avg_price,
                   MIN(l.price) as min_price,
                   MAX(l.price) as max_price,
                   COUNT(DISTINCT la.source) as sources_count
            FROM listing_analytics la
            JOIN listings l ON la.listing_id = l.id
            WHERE la.created_at >= datetime('now', '-{} days')
            GROUP BY la.keyword
            ORDER BY frequency DESC
            LIMIT ?
        """.format(days), (limit,))
        
        rows = c.fetchall()
        return rows


@log_errors()
def get_hourly_activity(days=7):
    """Get listing activity by hour of day"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT strftime('%H', created_at) as hour,
                   COUNT(*) as count,
                   source
            FROM listings 
            WHERE created_at >= datetime('now', '-{} days')
            GROUP BY strftime('%H', created_at), source
            ORDER BY hour
        """.format(days))
        
        rows = c.fetchall()
        return rows


@log_errors()
def get_price_distribution(days=30, bins=10):
    """Get price distribution data for histograms"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT MIN(price) as min_price, MAX(price) as max_price
            FROM listings 
            WHERE created_at >= datetime('now', '-{} days') AND price > 0
        """.format(days))
        
        result = c.fetchone()
        if not result or not result[0] or not result[1]:
            return []
        
        min_price, max_price = result
        bin_size = (max_price - min_price) / bins
        
        price_ranges = []
        for i in range(bins):
            start = min_price + (i * bin_size)
            end = min_price + ((i + 1) * bin_size)
            c.execute("""
                SELECT COUNT(*) as count
                FROM listings 
                WHERE created_at >= datetime('now', '-{} days') 
                AND price >= ? AND price < ?
            """.format(days), (start, end))
            count = c.fetchone()[0]
            price_ranges.append({
                'range': f"${start:.0f}-${end:.0f}",
                'count': count,
                'start': start,
                'end': end
            })
        
        return price_ranges


@log_errors()
def update_keyword_trends():
    """Update keyword trends from recent listings"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        # Get recent listings and extract keywords
        c.execute("""
            SELECT id, title, price, source, created_at
            FROM listings 
            WHERE created_at >= datetime('now', '-1 day')
        """)
        
        listings = c.fetchall()
        
        # Simple keyword extraction
        keywords = {}
        for listing in listings:
            listing_id, title, price, source, created_at = listing
            title_lower = title.lower()
            
            car_keywords = ['firebird', 'camaro', 'corvette', 'mustang', 'charger', 'challenger', 
                           'trans am', 'gto', 'nova', 'chevelle', 'impala', 'monte carlo']
            
            for keyword in car_keywords:
                if keyword in title_lower:
                    if keyword not in keywords:
                        keywords[keyword] = {'count': 0, 'total_price': 0, 'sources': set()}
                    keywords[keyword]['count'] += 1
                    keywords[keyword]['total_price'] += price
                    keywords[keyword]['sources'].add(source)
        
        # Save keyword trends
        today = datetime.now().date()
        for keyword, data in keywords.items():
            avg_price = data['total_price'] / data['count']
            for source in data['sources']:
                c.execute("""
                    INSERT OR REPLACE INTO keyword_trends (keyword, count, avg_price, date, source)
                    VALUES (?, ?, ?, ?, ?)
                """, (keyword, data['count'], avg_price, today, source))
        
        conn.commit()


@log_errors()
def get_market_insights(days=30):
    """Get comprehensive market insights"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        # Overall stats
        c.execute("""
            SELECT COUNT(*) as total_listings,
                   AVG(price) as avg_price,
                   MIN(price) as min_price,
                   MAX(price) as max_price,
                   COUNT(DISTINCT source) as sources_count
            FROM listings 
            WHERE created_at >= datetime('now', '-{} days')
        """.format(days))
        
        overall_stats = c.fetchone()
        
        # Top performing keywords
        c.execute("""
            SELECT la.keyword, COUNT(*) as count, AVG(l.price) as avg_price
            FROM listing_analytics la
            JOIN listings l ON la.listing_id = l.id
            WHERE la.created_at >= datetime('now', '-{} days')
            GROUP BY la.keyword
            ORDER BY count DESC
            LIMIT 5
        """.format(days))
        
        top_keywords = c.fetchall()
        
        # Source performance
        c.execute("""
            SELECT source, COUNT(*) as count, AVG(price) as avg_price
            FROM listings 
            WHERE created_at >= datetime('now', '-{} days')
            GROUP BY source
            ORDER BY count DESC
        """.format(days))
        
        source_performance = c.fetchall()
        
        return {
            'overall_stats': overall_stats,
            'top_keywords': top_keywords,
            'source_performance': source_performance
        }


# ======================
# CLEANUP
# ======================

def close_database():
    """Close all database connections"""
    global _connection_pool
    if _connection_pool:
        _connection_pool.close_all()
        _connection_pool = None
