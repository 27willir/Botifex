# db_enhanced.py - Enhanced database module for handling 1000+ users
import sqlite3
import re
import threading
import time
import os
from datetime import datetime, timedelta
from contextlib import contextmanager
from queue import Queue, Empty
from error_handling import ErrorHandler, log_errors, DatabaseError
from utils import logger

# Database configuration - supports both SQLite and PostgreSQL
DATABASE_URL = os.getenv('DATABASE_URL', '')
DB_FILE = os.getenv('DB_FILE', 'superbot.db')

# Detect database type
USE_POSTGRES = False
if DATABASE_URL and (DATABASE_URL.startswith('postgres://') or DATABASE_URL.startswith('postgresql://')):
    USE_POSTGRES = True
    try:
        import psycopg2
        from psycopg2 import pool
        from psycopg2.extras import RealDictCursor
        logger.info("PostgreSQL detected - using PostgreSQL database")
    except ImportError:
        logger.warning("DATABASE_URL points to PostgreSQL but psycopg2 not installed. Falling back to SQLite.")
        logger.warning("Install with: pip install psycopg2-binary")
        USE_POSTGRES = False
else:
    logger.info(f"Using SQLite database: {DB_FILE}")

def _prepare_sql(statement):
    """Translate SQLite-specific DDL to PostgreSQL-compatible SQL when needed."""
    if not USE_POSTGRES or not isinstance(statement, str):
        return statement
    replacements = [
        ("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY"),
        ("DATETIME", "TIMESTAMP"),
        ("BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT FALSE"),
        ("BOOLEAN DEFAULT 1", "BOOLEAN DEFAULT TRUE"),
        ("BOOLEAN DEFAULT '0'", "BOOLEAN DEFAULT FALSE"),
        ("BOOLEAN DEFAULT '1'", "BOOLEAN DEFAULT TRUE"),
        ("BOOLEAN DEFAULT \"0\"", "BOOLEAN DEFAULT FALSE"),
        ("BOOLEAN DEFAULT \"1\"", "BOOLEAN DEFAULT TRUE"),
        ("REAL", "DOUBLE PRECISION"),
    ]
    converted = statement
    for old, new in replacements:
        converted = converted.replace(old, new)
    stripped = converted.lstrip()
    if stripped.upper().startswith("ALTER TABLE"):
        converted = re.sub(
            r"ADD COLUMN(?!\s+IF\s+NOT\s+EXISTS)",
            "ADD COLUMN IF NOT EXISTS",
            converted,
            flags=re.IGNORECASE
        )
    return converted

def _should_ignore_duplicate_error(error):
    """Return True when duplicate column/index errors can be safely ignored."""
    message = str(error).lower()
    if "already exists" in message or "duplicate column" in message:
        return True
    if USE_POSTGRES:
        pgcode = getattr(error, "pgcode", None)
        if pgcode in {"42701", "42P07"}:  # duplicate_column, duplicate_table
            return True
    return False

def _ignore_duplicate_schema_error(conn, error):
    """
    Normalize duplicate schema errors across SQLite/PostgreSQL.
    Returns True when the error can be ignored safely.
    """
    if _should_ignore_duplicate_error(error):
        if USE_POSTGRES:
            try:
                conn.rollback()
            except Exception:
                pass
        return True
    return False

class _PostgresCursorWrapper:
    """Cursor proxy that normalizes SQLite DDL to PostgreSQL syntax."""

    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, statement, *args, **kwargs):
        statement = _prepare_sql(statement)
        return self._cursor.execute(statement, *args, **kwargs)

    def executemany(self, statement, seq_of_params):
        statement = _prepare_sql(statement)
        return self._cursor.executemany(statement, seq_of_params)

    def __getattr__(self, item):
        return getattr(self._cursor, item)

    def __iter__(self):
        return iter(self._cursor)

    def __enter__(self):
        self._cursor.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return self._cursor.__exit__(exc_type, exc_val, exc_tb)

# Connection pool configuration - optimized for production
POOL_SIZE = 5  # Reduced pool size for better memory management
CONNECTION_TIMEOUT = 10  # Reduced timeout for faster failure detection

# Async activity logging queue to prevent blocking on login
_activity_log_queue = Queue(maxsize=2000)
_activity_logger_thread = None
_activity_logger_running = False

def _activity_logger_worker():
    """Background thread that processes activity log events from queue"""
    global _activity_logger_running
    logger.info("Activity logger worker started")
    
    while _activity_logger_running:
        try:
            # Wait for events with timeout to allow clean shutdown
            event_data = _activity_log_queue.get(timeout=1)
            
            # Try to log to database with limited retries
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    if event_data['type'] == 'login':
                        # Update login tracking and log activity
                        _update_user_login_and_log_activity_sync(
                            event_data['username'],
                            event_data.get('ip_address'),
                            event_data.get('user_agent')
                        )
                    elif event_data['type'] == 'activity':
                        # Log general activity
                        _log_user_activity_sync(
                            event_data['username'],
                            event_data['action'],
                            event_data.get('details'),
                            event_data.get('ip_address'),
                            event_data.get('user_agent')
                        )
                    break  # Success
                except Exception as e:
                    if attempt < max_retries - 1:
                        time.sleep(0.1 * (2 ** attempt))  # Exponential backoff
                    else:
                        # Failed all retries, log to file
                        logger.warning(
                            f"Failed to log activity after {max_retries} attempts: "
                            f"Type={event_data['type']}, Username={event_data.get('username')}"
                        )
            
            _activity_log_queue.task_done()
            
        except Empty:
            # Queue timeout, continue loop
            continue
        except Exception as e:
            logger.error(f"Activity logger worker error: {e}")
    
    logger.info("Activity logger worker stopped")

def start_activity_logger():
    """Start the background activity logger thread"""
    global _activity_logger_thread, _activity_logger_running
    
    if _activity_logger_running:
        return  # Already running
    
    _activity_logger_running = True
    _activity_logger_thread = threading.Thread(target=_activity_logger_worker, daemon=True)
    _activity_logger_thread.start()
    logger.info("Activity logger background thread started")

def stop_activity_logger():
    """Stop the background activity logger thread"""
    global _activity_logger_running
    
    if not _activity_logger_running:
        return
    
    _activity_logger_running = False
    if _activity_logger_thread:
        _activity_logger_thread.join(timeout=5)
    logger.info("Activity logger background thread stopped")


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
            timeout=CONNECTION_TIMEOUT,
            isolation_level=None  # Autocommit mode to reduce locking
        )
        # Production-optimized pragmas for better concurrency
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=20000")  # Increased cache size
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA mmap_size=268435456")  # 256MB
        conn.execute("PRAGMA busy_timeout=2000")  # 2 second timeout for faster failure detection
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA read_uncommitted=1")  # Allow dirty reads for better concurrency
        conn.execute("PRAGMA locking_mode=NORMAL")  # Use normal locking
        # WAL checkpoint optimization
        conn.execute("PRAGMA wal_autocheckpoint=1000")  # More frequent checkpoints
        # Enable query planner optimizations
        conn.execute("PRAGMA optimize")
        return conn
    
    @contextmanager
    def get_connection(self):
        """Get a connection from the pool (context manager)"""
        conn = None
        try:
            conn = self.pool.get(timeout=CONNECTION_TIMEOUT)
            # Test the connection before yielding
            try:
                conn.execute("SELECT 1").fetchone()
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e).lower():
                    # Create a new connection if the pooled one is locked
                    logger.warning("Pooled connection is locked, creating new connection")
                    conn.close()
                    conn = self._create_connection()
                else:
                    # For other errors, close and create new connection
                    logger.warning(f"Connection test failed: {e}, creating new connection")
                    conn.close()
                    conn = self._create_connection()
            yield conn
        except Empty:
            logger.error("Connection pool exhausted - consider increasing pool size")
            raise DatabaseError("Database connection pool exhausted")
        finally:
            if conn:
                try:
                    # Ensure connection is in a good state before returning to pool
                    conn.execute("SELECT 1").fetchone()
                    self.pool.put(conn)
                except sqlite3.OperationalError:
                    # If connection is bad, close it and don't return to pool
                    logger.warning("Removing bad connection from pool")
                    conn.close()
    
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


# PostgreSQL connection pool class
class PostgreSQLConnectionPool:
    """Thread-safe connection pool for PostgreSQL"""
    
    def __init__(self, database_url, pool_size=POOL_SIZE):
        from psycopg2.pool import ThreadedConnectionPool
        import threading
        self.database_url = database_url
        self.pool_size = pool_size
        self.lock = threading.Lock()
        self.all_connections = []
        try:
            self.pool = ThreadedConnectionPool(1, pool_size, database_url)
            logger.info(f"Initialized PostgreSQL connection pool with {pool_size} max connections")
        except Exception as e:
            logger.error(f"Failed to create PostgreSQL connection pool: {e}")
            raise DatabaseError(f"Failed to initialize PostgreSQL pool: {e}")
    
    @contextmanager
    def get_connection(self):
        """Get a connection from the pool (context manager)"""
        conn = None
        try:
            conn = self.pool.getconn()
            if conn is None:
                raise DatabaseError("Failed to get connection from PostgreSQL pool")
            # Test connection
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            yield conn
        except Exception as e:
            logger.error(f"PostgreSQL connection error: {e}")
            raise DatabaseError(f"PostgreSQL connection failed: {e}")
        finally:
            if conn:
                try:
                    self.pool.putconn(conn)
                except Exception as e:
                    logger.error(f"Error returning connection to pool: {e}")
                    try:
                        conn.close()
                    except:
                        pass
    
    def close_all(self):
        """Close all connections in the pool"""
        if hasattr(self, 'pool') and self.pool:
            try:
                self.pool.closeall()
                logger.info("Closed all PostgreSQL connections")
            except Exception as e:
                logger.error(f"Error closing PostgreSQL pool: {e}")


# Global connection pool
_connection_pool = None


def get_pool():
    """Get or create the global connection pool"""
    global _connection_pool
    if _connection_pool is None:
        if USE_POSTGRES:
            # PostgreSQL support - create PostgreSQL pool
            try:
                from psycopg2.pool import ThreadedConnectionPool
                _connection_pool = PostgreSQLConnectionPool(DATABASE_URL)
                logger.info("✅ Using PostgreSQL - user data will persist across deployments")
            except Exception as e:
                logger.error(f"Failed to create PostgreSQL pool: {e}")
                logger.warning("⚠️  Falling back to SQLite - user data will NOT persist on deployments")
                logger.warning("⚠️  See docs/deployment/DATABASE_PERSISTENCE_SETUP.md for setup instructions")
                _connection_pool = DatabaseConnectionPool(DB_FILE)
        else:
            logger.warning("⚠️  Using SQLite - user data will NOT persist on deployments")
            logger.warning("⚠️  Set DATABASE_URL to use PostgreSQL for persistent storage")
            _connection_pool = DatabaseConnectionPool(DB_FILE)
    return _connection_pool

def maintain_database():
    """Perform database maintenance to prevent locking issues"""
    try:
        with get_pool().get_connection() as conn:
            c = conn.cursor()
            # Analyze database for better query planning
            c.execute("ANALYZE")
            # Clean up any pending transactions
            c.execute("PRAGMA optimize")
            # Check database integrity
            c.execute("PRAGMA integrity_check")
            logger.info("Database maintenance completed")
    except Exception as e:
        logger.error(f"Database maintenance failed: {e}")

def get_pool_status():
    """Get current pool status for monitoring"""
    try:
        pool = get_pool()
        return {
            "pool_size": pool.pool_size,
            "available_connections": pool.pool.qsize(),
            "total_connections": len(pool.all_connections),
            "pool_utilization": f"{((pool.pool_size - pool.pool.qsize()) / pool.pool_size) * 100:.1f}%"
        }
    except Exception as e:
        logger.error(f"Failed to get pool status: {e}")
        return {"error": str(e)}

def cleanup_old_connections():
    """Clean up old or problematic connections from the pool"""
    try:
        pool = get_pool()
        if USE_POSTGRES and isinstance(pool, PostgreSQLConnectionPool):
            logger.info("Skipping SQLite-style connection cleanup for PostgreSQL pool")
            return
        with pool.lock:
            # Test all connections and remove bad ones
            good_connections = []
            for conn in pool.all_connections:
                try:
                    conn.execute("SELECT 1").fetchone()
                    good_connections.append(conn)
                except Exception:
                    conn.close()
                    logger.warning("Removed bad connection from pool")
            
            # Rebuild the pool with good connections
            pool.all_connections = good_connections
            pool.pool = Queue(maxsize=pool.pool_size)
            for conn in good_connections:
                pool.pool.put(conn)
            
            logger.info(f"Cleaned up connection pool, {len(good_connections)} connections remaining")
    except Exception as e:
        logger.error(f"Connection cleanup failed: {e}")

def reset_connection_pool():
    """Reset the entire connection pool when locking issues persist"""
    try:
        global _connection_pool
        if _connection_pool:
            logger.warning("Resetting connection pool due to persistent locking issues")
            _connection_pool.close_all()
            _connection_pool = None
        
        # Create a new pool
        if USE_POSTGRES:
            _connection_pool = PostgreSQLConnectionPool(DATABASE_URL)
        else:
            _connection_pool = DatabaseConnectionPool(DB_FILE)
        logger.info("Connection pool reset successfully")
    except Exception as e:
        logger.error(f"Connection pool reset failed: {e}")


def retry_db_operation(operation_func, max_retries=5, base_delay=0.1):
    """
    Retry database operations with exponential backoff for handling locking issues
    
    Args:
        operation_func: Function to execute (should return a result)
        max_retries: Maximum number of retry attempts
        base_delay: Base delay in seconds for exponential backoff
    
    Returns:
        Result of the operation or None if all retries failed
    """
    import time
    import random
    
    for attempt in range(max_retries):
        try:
            return operation_func()
        except sqlite3.OperationalError as e:
            error_msg = str(e).lower()
            if "database is locked" in error_msg or "database table is locked" in error_msg:
                if attempt < max_retries - 1:
                    # Exponential backoff with jitter
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 0.2)
                    logger.warning(f"Database locked, retrying in {delay:.2f}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(delay)
                    continue
                else:
                    logger.error(f"Database locked after {max_retries} attempts")
                    # Try to reset connection pool on final failure
                    try:
                        reset_connection_pool()
                    except Exception as reset_error:
                        logger.error(f"Connection pool reset failed: {reset_error}")
                    return None
            elif "database is busy" in error_msg:
                if attempt < max_retries - 1:
                    # Shorter delay for busy database
                    delay = base_delay * (1.5 ** attempt) + random.uniform(0, 0.1)
                    logger.warning(f"Database busy, retrying in {delay:.2f}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(delay)
                    continue
                else:
                    logger.error(f"Database busy after {max_retries} attempts")
                    return None
            else:
                logger.error(f"Database error: {e}")
                return None
        except sqlite3.DatabaseError as e:
            logger.error(f"Database integrity error: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error in database operation: {e}")
            return None
    
    logger.warning(f"Database operation failed after {max_retries} attempts")
    return None


@log_errors()
def init_db():
    """Initialize database with all required tables and indexes"""
    try:
        with get_pool().get_connection() as conn:
            c = conn.cursor()
            if USE_POSTGRES:
                c = _PostgresCursorWrapper(c)
            
            # Users table with enhanced fields
            c.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    role TEXT DEFAULT 'user',
                    verified BOOLEAN DEFAULT 0,
                    active BOOLEAN DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_login DATETIME,
                    login_count INTEGER DEFAULT 0,
                    phone_number TEXT,
                    email_notifications BOOLEAN DEFAULT 1,
                    sms_notifications BOOLEAN DEFAULT 0
                )
            """)
            
            # Add notification columns if they don't exist (for existing databases)
            try:
                c.execute("ALTER TABLE users ADD COLUMN phone_number TEXT")
                logger.info("Added phone_number column to users table")
            except Exception as e:
                if not _ignore_duplicate_schema_error(conn, e):
                    raise
            
            try:
                c.execute("ALTER TABLE users ADD COLUMN tos_agreed BOOLEAN DEFAULT 0")
                logger.info("Added tos_agreed column to users table")
            except Exception as e:
                if not _ignore_duplicate_schema_error(conn, e):
                    raise
            
            try:
                c.execute("ALTER TABLE users ADD COLUMN tos_agreed_at DATETIME")
                logger.info("Added tos_agreed_at column to users table")
            except Exception as e:
                if not _ignore_duplicate_schema_error(conn, e):
                    raise
            
            try:
                c.execute("ALTER TABLE users ADD COLUMN email_notifications BOOLEAN DEFAULT 1")
                logger.info("Added email_notifications column to users table")
            except Exception as e:
                if not _ignore_duplicate_schema_error(conn, e):
                    raise
            
            try:
                c.execute("ALTER TABLE users ADD COLUMN sms_notifications BOOLEAN DEFAULT 0")
                logger.info("Added sms_notifications column to users table")
            except Exception as e:
                if not _ignore_duplicate_schema_error(conn, e):
                    raise
            
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
            
            # Seller listings table - for items users want to sell
            c.execute("""
                CREATE TABLE IF NOT EXISTS seller_listings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    price INTEGER NOT NULL,
                    original_cost INTEGER,
                    category TEXT,
                    location TEXT,
                    images TEXT,
                    marketplaces TEXT,
                    status TEXT DEFAULT 'draft',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    posted_at DATETIME,
                    sold_at DATETIME,
                    sold_on_marketplace TEXT,
                    actual_sale_price INTEGER,
                    craigslist_url TEXT,
                    facebook_url TEXT,
                    ksl_url TEXT,
                    FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)
            
            # Add new columns to existing tables if they don't exist
            try:
                c.execute("ALTER TABLE seller_listings ADD COLUMN sold_at DATETIME")
                logger.info("Added sold_at column to seller_listings table")
            except Exception as e:
                if not _ignore_duplicate_schema_error(conn, e):
                    raise
            
            try:
                c.execute("ALTER TABLE seller_listings ADD COLUMN sold_on_marketplace TEXT")
                logger.info("Added sold_on_marketplace column to seller_listings table")
            except Exception as e:
                if not _ignore_duplicate_schema_error(conn, e):
                    raise
            
            try:
                c.execute("ALTER TABLE seller_listings ADD COLUMN actual_sale_price INTEGER")
                logger.info("Added actual_sale_price column to seller_listings table")
            except Exception as e:
                if not _ignore_duplicate_schema_error(conn, e):
                    raise
            
            try:
                c.execute("ALTER TABLE seller_listings ADD COLUMN original_cost INTEGER")
                logger.info("Added original_cost column to seller_listings table")
            except Exception as e:
                if not _ignore_duplicate_schema_error(conn, e):
                    raise
            
            c.execute("""
                CREATE TABLE IF NOT EXISTS keyword_trends (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    keyword TEXT,
                    count INTEGER,
                    avg_price REAL,
                    date DATE,
                    source TEXT,
                    user_id TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (username) ON DELETE CASCADE
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
            
            # Subscription tables
            c.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    tier TEXT DEFAULT 'free',
                    status TEXT DEFAULT 'active',
                    stripe_customer_id TEXT,
                    stripe_subscription_id TEXT,
                    current_period_start DATETIME,
                    current_period_end DATETIME,
                    cancel_at_period_end BOOLEAN DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)
            
            c.execute("""
                CREATE TABLE IF NOT EXISTS subscription_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    tier TEXT NOT NULL,
                    action TEXT NOT NULL,
                    stripe_event_id TEXT,
                    details TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)
            
            # Email verification tokens
            c.execute("""
                CREATE TABLE IF NOT EXISTS email_verification_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    token TEXT UNIQUE NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    expires_at DATETIME NOT NULL,
                    used BOOLEAN DEFAULT 0,
                    FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)
            
            # Password reset tokens
            c.execute("""
                CREATE TABLE IF NOT EXISTS password_reset_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    token TEXT UNIQUE NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    expires_at DATETIME NOT NULL,
                    used BOOLEAN DEFAULT 0,
                    FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)
            
            # Security events table
            c.execute("""
                CREATE TABLE IF NOT EXISTS security_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ip_address TEXT NOT NULL,
                    path TEXT NOT NULL,
                    user_agent TEXT,
                    reason TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Favorites/Bookmarks
            c.execute("""
                CREATE TABLE IF NOT EXISTS favorites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    listing_id INTEGER NOT NULL,
                    notes TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(username, listing_id),
                    FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE,
                    FOREIGN KEY (listing_id) REFERENCES listings (id) ON DELETE CASCADE
                )
            """)
            
            # Saved searches
            c.execute("""
                CREATE TABLE IF NOT EXISTS saved_searches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    name TEXT NOT NULL,
                    keywords TEXT,
                    min_price INTEGER,
                    max_price INTEGER,
                    sources TEXT,
                    location TEXT,
                    radius INTEGER,
                    notify_new BOOLEAN DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_run DATETIME,
                    FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)
            
            # Price alerts
            c.execute("""
                CREATE TABLE IF NOT EXISTS price_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    keywords TEXT NOT NULL,
                    threshold_price INTEGER NOT NULL,
                    alert_type TEXT DEFAULT 'under',
                    active BOOLEAN DEFAULT 1,
                    last_triggered DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)
            
            # Add subscription columns to users if they don't exist (backward compatibility)
            try:
                c.execute("ALTER TABLE users ADD COLUMN subscription_tier TEXT DEFAULT 'free'")
                logger.info("Added subscription_tier column to users table")
            except sqlite3.OperationalError:
                pass  # Column already exists
            
            # Add user_id column to keyword_trends if it doesn't exist
            try:
                c.execute("ALTER TABLE keyword_trends ADD COLUMN user_id TEXT")
                logger.info("Added user_id column to keyword_trends table")
            except sqlite3.OperationalError:
                pass  # Column already exists
            
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
                "CREATE INDEX IF NOT EXISTS idx_trends_user_id ON keyword_trends(user_id)",
                "CREATE INDEX IF NOT EXISTS idx_market_stats_date ON market_stats(date)",
                "CREATE INDEX IF NOT EXISTS idx_rate_limits_username ON rate_limits(username)",
                "CREATE INDEX IF NOT EXISTS idx_rate_limits_endpoint ON rate_limits(endpoint)",
                "CREATE INDEX IF NOT EXISTS idx_settings_username ON settings(username)",
                "CREATE INDEX IF NOT EXISTS idx_seller_listings_username ON seller_listings(username)",
                "CREATE INDEX IF NOT EXISTS idx_seller_listings_status ON seller_listings(status)",
                "CREATE INDEX IF NOT EXISTS idx_seller_listings_created ON seller_listings(created_at)",
                "CREATE INDEX IF NOT EXISTS idx_subscriptions_username ON subscriptions(username)",
                "CREATE INDEX IF NOT EXISTS idx_subscriptions_tier ON subscriptions(tier)",
                "CREATE INDEX IF NOT EXISTS idx_subscriptions_status ON subscriptions(status)",
                "CREATE INDEX IF NOT EXISTS idx_subscriptions_customer_id ON subscriptions(stripe_customer_id)",
                "CREATE INDEX IF NOT EXISTS idx_subscription_history_username ON subscription_history(username)",
                "CREATE INDEX IF NOT EXISTS idx_email_verification_token ON email_verification_tokens(token)",
                "CREATE INDEX IF NOT EXISTS idx_email_verification_username ON email_verification_tokens(username)",
                "CREATE INDEX IF NOT EXISTS idx_password_reset_token ON password_reset_tokens(token)",
                "CREATE INDEX IF NOT EXISTS idx_password_reset_username ON password_reset_tokens(username)",
                "CREATE INDEX IF NOT EXISTS idx_favorites_username ON favorites(username)",
                "CREATE INDEX IF NOT EXISTS idx_favorites_listing ON favorites(listing_id)",
                "CREATE INDEX IF NOT EXISTS idx_saved_searches_username ON saved_searches(username)",
                "CREATE INDEX IF NOT EXISTS idx_price_alerts_username ON price_alerts(username)",
                "CREATE INDEX IF NOT EXISTS idx_price_alerts_active ON price_alerts(active)",
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
            SELECT username, email, password, verified, role, active, 
                   created_at, last_login, login_count 
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
                INSERT INTO users (username, email, password, role, verified, created_at) 
                VALUES (?, ?, ?, ?, 0, ?)
            """, (username, email, password_hash, role, datetime.now()))
            conn.commit()
            logger.info(f"Created new user: {username} with role: {role} (unverified)")
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
def _update_user_login_and_log_activity_sync(username, ip_address=None, user_agent=None):
    """Synchronous version - used by background worker only"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        try:
            # Update login tracking
            c.execute("""
                UPDATE users 
                SET last_login = ?, login_count = login_count + 1 
                WHERE username = ?
            """, (datetime.now(), username))
            
            # Log activity
            c.execute("""
                INSERT INTO user_activity (username, action, details, ip_address, user_agent, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (username, 'login', 'User logged in', ip_address, user_agent, datetime.now()))
            
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e

@log_errors()
def update_user_login_and_log_activity(username, ip_address=None, user_agent=None):
    """Async version - queues the operation for background processing"""
    try:
        event_data = {
            'type': 'login',
            'username': username,
            'ip_address': ip_address,
            'user_agent': user_agent
        }
        
        # Try to add to queue without blocking
        try:
            _activity_log_queue.put_nowait(event_data)
        except Exception:
            # Queue is full, log to file instead
            logger.warning(f"Activity log queue full. Login: {username}")
    except Exception as e:
        # Don't let logging errors block the login
        logger.error(f"Error queuing login activity: {e}")


@log_errors()
def record_tos_agreement(username):
    """Record that a user has agreed to the Terms of Service"""
    try:
        with get_pool().get_connection() as conn:
            c = conn.cursor()
            c.execute("""
                UPDATE users 
                SET tos_agreed = 1, tos_agreed_at = ? 
                WHERE username = ?
            """, (datetime.now(), username))
            conn.commit()
            logger.info(f"ToS agreement recorded for user: {username}")
            return True
    except Exception as e:
        logger.error(f"Failed to record ToS agreement for {username}: {e}")
        return False


@log_errors()
def get_tos_agreement(username):
    """Check if a user has agreed to the Terms of Service"""
    try:
        with get_pool().get_connection() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT tos_agreed, tos_agreed_at 
                FROM users 
                WHERE username = ?
            """, (username,))
            result = c.fetchone()
            if result:
                return {
                    'agreed': bool(result[0]),
                    'agreed_at': result[1]
                }
            return None
    except Exception as e:
        logger.error(f"Failed to get ToS agreement for {username}: {e}")
        return None


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
def get_all_user_emails():
    """Get summary email info for all users (admin directory)"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT username, email, verified, email_notifications, active, created_at
            FROM users
            ORDER BY created_at DESC
        """)
        return c.fetchall()


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
# NOTIFICATION PREFERENCES
# ======================

@log_errors()
def get_notification_preferences(username):
    """
    Get notification preferences for a user
    
    Returns:
        dict: {
            'email': email_address,
            'phone_number': phone_number,
            'email_notifications': bool,
            'sms_notifications': bool
        }
    """
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT email, phone_number, email_notifications, sms_notifications 
            FROM users 
            WHERE username = ?
        """, (username,))
        row = c.fetchone()
        if row:
            return {
                'email': row[0],
                'phone_number': row[1],
                'email_notifications': bool(row[2]),
                'sms_notifications': bool(row[3])
            }
        return None


@log_errors()
def update_notification_preferences(username, email_notifications=None, sms_notifications=None, phone_number=None):
    """
    Update notification preferences for a user
    
    Args:
        username: Username
        email_notifications: Enable/disable email notifications (bool, optional)
        sms_notifications: Enable/disable SMS notifications (bool, optional)
        phone_number: Phone number for SMS (str, optional)
    """
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        updates = []
        params = []
        
        if email_notifications is not None:
            updates.append("email_notifications = ?")
            params.append(1 if email_notifications else 0)
        
        if sms_notifications is not None:
            updates.append("sms_notifications = ?")
            params.append(1 if sms_notifications else 0)
        
        if phone_number is not None:
            updates.append("phone_number = ?")
            params.append(phone_number)
        
        if updates:
            params.append(username)
            query = f"UPDATE users SET {', '.join(updates)} WHERE username = ?"
            c.execute(query, params)
            conn.commit()
            logger.info(f"Updated notification preferences for user {username}")
        else:
            logger.warning(f"No notification preferences to update for user {username}")


@log_errors()
def get_users_with_notifications_enabled():
    """
    Get all active users who have at least one notification type enabled
    
    Returns:
        list: List of dicts containing user info and notification preferences
    """
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT username, email, phone_number, email_notifications, sms_notifications
            FROM users
            WHERE active = 1 AND (email_notifications = 1 OR sms_notifications = 1)
        """)
        rows = c.fetchall()
        return [
            {
                'username': row[0],
                'email': row[1],
                'phone_number': row[2],
                'email_notifications': bool(row[3]),
                'sms_notifications': bool(row[4])
            }
            for row in rows
        ]


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

        # Automatically align refresh interval with subscription tier
        try:
            from subscriptions import SubscriptionManager  # Imported lazily to avoid circular deps

            tier = 'free'
            if username:
                subscription = get_user_subscription(username)
                tier = subscription.get('tier', 'free')

            interval_seconds = max(1, SubscriptionManager.get_refresh_interval(tier))
            settings['interval'] = str(interval_seconds)
        except Exception as e:
            logger.warning(f"Failed to apply subscription interval for {username or 'global'} settings: {e}")
            settings.setdefault('interval', '60')

        return settings


@log_errors()
def update_setting(key, value, username=None):
    """Update setting for a specific user, or global setting if username is None"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()

        # Force refresh interval to align with subscription tier
        if key == 'interval':
            try:
                from subscriptions import SubscriptionManager  # Lazy import to avoid circular deps

                tier = 'free'
                if username:
                    subscription = get_user_subscription(username)
                    tier = subscription.get('tier', 'free')

                interval_seconds = max(1, SubscriptionManager.get_refresh_interval(tier))
                value = str(interval_seconds)
            except Exception as e:
                logger.warning(f"Failed to enforce subscription interval for {username or 'global'}: {e}")
                value = str(value)
        else:
            value = str(value)

        c.execute("""
            INSERT OR REPLACE INTO settings (username, key, value, updated_at) 
            VALUES (?, ?, ?, ?)
        """, (username, key, value, datetime.now()))
        conn.commit()


# ======================
# USER ACTIVITY LOGGING
# ======================

@log_errors()
def get_recent_failed_logins(username, ip_address, hours=1):
    """Get recent failed login attempts for security monitoring"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        cutoff_time = datetime.now() - timedelta(hours=hours)
        c.execute("""
            SELECT username, action, ip_address, timestamp
            FROM user_activity 
            WHERE (username = ? OR ip_address = ?) 
            AND action = 'login_failed' 
            AND timestamp > ?
            ORDER BY timestamp DESC
        """, (username, ip_address, cutoff_time))
        return c.fetchall()

@log_errors()
def _log_user_activity_sync(username, action, details=None, ip_address=None, user_agent=None):
    """Synchronous version - used by background worker only"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        # Check if user exists before logging activity
        c.execute("SELECT username FROM users WHERE username = ?", (username,))
        user_exists = c.fetchone()
        
        if not user_exists and action in ['login_failed', 'login_attempt']:
            # For failed login attempts, we can log even for non-existent users
            # by temporarily disabling foreign key constraints
            c.execute("PRAGMA foreign_keys=OFF")
            c.execute("""
                INSERT INTO user_activity (username, action, details, ip_address, user_agent, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (username, action, details, ip_address, user_agent, datetime.now()))
            c.execute("PRAGMA foreign_keys=ON")
        elif user_exists:
            # Normal logging for existing users
            c.execute("""
                INSERT INTO user_activity (username, action, details, ip_address, user_agent, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (username, action, details, ip_address, user_agent, datetime.now()))
        else:
            # Skip logging for non-existent users on other actions
            logger.warning(f"Skipping activity log for non-existent user: {username}")
            return
        
        conn.commit()

def log_user_activity(username, action, details=None, ip_address=None, user_agent=None):
    """Async version - queues the operation for background processing"""
    try:
        event_data = {
            'type': 'activity',
            'username': username,
            'action': action,
            'details': details,
            'ip_address': ip_address,
            'user_agent': user_agent
        }
        
        # Try to add to queue without blocking
        try:
            _activity_log_queue.put_nowait(event_data)
        except Exception:
            # Queue is full, log to file instead
            logger.warning(f"Activity log queue full. Activity: {username} - {action}")
    except Exception as e:
        # Don't let logging errors block the request
        logger.error(f"Error queuing user activity: {e}")


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
    import time
    import random
    
    max_retries = 5
    base_delay = 0.1  # Base delay in seconds
    
    for attempt in range(max_retries):
        try:
            with get_pool().get_connection() as conn:
                # Use immediate transaction mode to avoid locking
                conn.execute("BEGIN IMMEDIATE")
                c = conn.cursor()
                
                now = datetime.now()
                
                # Use UPSERT (INSERT OR REPLACE) to handle race conditions
                # First, try to get existing record
                c.execute("""
                    SELECT request_count, window_start 
                    FROM rate_limits 
                    WHERE username = ? AND endpoint = ?
                """, (username, endpoint))
                
                result = c.fetchone()
                
                if result:
                    request_count, window_start = result
                    window_start = datetime.fromisoformat(window_start)
                    
                    # Check if we're still in the same window
                    time_diff = (now - window_start).total_seconds() / 60
                    
                    if time_diff < window_minutes:
                        # Still in same window
                        if request_count >= max_requests:
                            conn.rollback()
                            logger.warning(f"Rate limit exceeded for {username} on {endpoint}")
                            return False, 0
                        
                        # Increment count atomically
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
                    # First request - use INSERT OR IGNORE to handle race conditions
                    try:
                        c.execute("""
                            INSERT INTO rate_limits (username, endpoint, request_count, window_start) 
                            VALUES (?, ?, 1, ?)
                        """, (username, endpoint, now))
                        conn.commit()
                        return True, max_requests - 1
                    except sqlite3.IntegrityError:
                        # Race condition - another thread inserted the record
                        # Rollback and retry
                        conn.rollback()
                        if attempt < max_retries - 1:
                            time.sleep(base_delay * (2 ** attempt) + random.uniform(0, 0.1))
                            continue
                        else:
                            # Last attempt - just return allowed
                            logger.warning(f"Rate limit check failed after {max_retries} attempts for {username}")
                            return True, max_requests - 1
                        
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e).lower():
                if attempt < max_retries - 1:
                    # Exponential backoff with jitter
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 0.1)
                    logger.warning(f"Database locked, retrying in {delay:.2f}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(delay)
                    continue
                else:
                    logger.error(f"Database locked after {max_retries} attempts for {username}")
                    # Return allowed to avoid blocking legitimate users
                    return True, max_requests - 1
            else:
                logger.error(f"Database error in check_rate_limit: {e}")
                return True, max_requests - 1
        except Exception as e:
            logger.error(f"Unexpected error in check_rate_limit: {e}")
            return True, max_requests - 1
    
    # Fallback - return allowed if all retries failed
    logger.warning(f"Rate limit check failed after {max_retries} attempts for {username}")
    return True, max_requests - 1


@log_errors()
def reset_rate_limit(username, endpoint=None):
    """Reset rate limit for a user (admin function)"""
    def _reset_operation():
        with get_pool().get_connection() as conn:
            c = conn.cursor()
            if endpoint:
                c.execute("DELETE FROM rate_limits WHERE username = ? AND endpoint = ?", (username, endpoint))
            else:
                c.execute("DELETE FROM rate_limits WHERE username = ?", (username,))
            conn.commit()
            logger.info(f"Reset rate limits for user: {username}")
            return True
    
    return retry_db_operation(_reset_operation)


# ======================
# LISTINGS MANAGEMENT
# ======================

@log_errors()
def save_listing(title, price, link, image_url=None, source=None, user_id=None):
    """Save a listing to the database"""
    is_new_listing = False
    listing_id = None
    
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        try:
            # Use a transaction to ensure atomicity
            # First, try to insert the listing
            c.execute("""
                INSERT OR IGNORE INTO listings (title, price, link, image_url, source, created_at, user_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (title, price, link, image_url, source, datetime.now(), user_id))
            
            # Check if we got a new row (lastrowid > 0 means successful insert)
            listing_id = c.lastrowid
            if listing_id > 0:
                # New listing was successfully inserted
                is_new_listing = True
            else:
                # Insert was ignored (duplicate), get the existing listing ID
                c.execute("SELECT id FROM listings WHERE link = ?", (link,))
                existing = c.fetchone()
                if existing:
                    listing_id = existing[0]
                else:
                    # This shouldn't happen, but handle it gracefully
                    logger.warning(f"Failed to insert listing and couldn't find existing: {link}")
                    conn.rollback()
                    return None
            
            conn.commit()
            
        except Exception as e:
            logger.error(f"Error saving listing: {e}")
            conn.rollback()
            return None
        
        # Save analytics data if we have a valid listing ID
        if listing_id and is_new_listing:
            try:
                # Extract keywords from title
                title_lower = title.lower()
                car_keywords = ['firebird', 'camaro', 'corvette', 'mustang', 'charger', 'challenger', 
                               'trans am', 'gto', 'nova', 'chevelle', 'impala', 'monte carlo']
                
                for keyword in car_keywords:
                    if keyword in title_lower:
                        # Determine price range (inclusive boundaries)
                        if price <= 5000:
                            price_range = "Under $5K"
                        elif price <= 10000:
                            price_range = "$5K-$10K"
                        elif price <= 20000:
                            price_range = "$10K-$20K"
                        elif price <= 30000:
                            price_range = "$20K-$30K"
                        else:
                            price_range = "Over $30K"
                        
                        # Determine category
                        category = "Classic Cars" if any(k in title_lower for k in ['firebird', 'camaro', 'corvette', 'trans am', 'gto', 'nova', 'chevelle', 'impala', 'monte carlo']) else "Modern Cars"
                        
                        save_listing_analytics(listing_id, keyword, category, price_range, source)
            except Exception as e:
                logger.error(f"Error saving analytics for listing {listing_id}: {e}")
        
        # Send notifications for new listings
        if is_new_listing:
            try:
                # Import here to avoid circular imports
                from notifications import notify_new_listing
                
                # Get all users with notifications enabled
                users = get_users_with_notifications_enabled()
                
                # Track notification results
                notification_results = {
                    'total': len(users),
                    'success': 0,
                    'failed': 0,
                    'failed_users': []
                }
                
                # Send notifications to each user
                for user in users:
                    try:
                        notify_new_listing(
                            user_email=user['email'],
                            user_phone=user['phone_number'],
                            email_enabled=user['email_notifications'],
                            sms_enabled=user['sms_notifications'],
                            listing_title=title,
                            listing_price=price,
                            listing_url=link,
                            listing_source=source or 'unknown'
                        )
                        notification_results['success'] += 1
                    except Exception as e:
                        notification_results['failed'] += 1
                        notification_results['failed_users'].append(user['username'])
                        logger.error(f"Error sending notification to user {user['username']}: {e}")
                        # Continue to next user even if one fails
                
                # Log summary
                if notification_results['failed'] > 0:
                    logger.warning(f"Notification summary for listing {listing_id}: {notification_results['success']}/{notification_results['total']} succeeded. Failed for: {', '.join(notification_results['failed_users'])}")
                else:
                    logger.info(f"All {notification_results['success']} notifications sent successfully for listing {listing_id}")
                        
            except Exception as e:
                logger.error(f"Error processing notifications for listing {listing_id}: {e}")
                # Don't fail the listing save if notifications fail
        
        return listing_id


@log_errors()
def get_listings(limit=100, user_id=None):
    """Get listings from database, optionally filtered by user"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        if user_id:
            c.execute("""
                SELECT id, title, price, link, image_url, source, created_at 
                FROM listings 
                WHERE user_id = ? 
                ORDER BY created_at DESC 
                LIMIT ?
            """, (user_id, limit))
        else:
            c.execute("""
                SELECT id, title, price, link, image_url, source, created_at 
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


@log_errors()
def get_listings_paginated(limit=50, offset=0, user_id=None):
    """Get paginated listings with offset"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        if user_id:
            c.execute("""
                SELECT id, title, price, link, image_url, source, created_at 
                FROM listings 
                WHERE user_id = ?
                ORDER BY created_at DESC 
                LIMIT ? OFFSET ?
            """, (user_id, limit, offset))
        else:
            c.execute("""
                SELECT id, title, price, link, image_url, source, created_at 
                FROM listings 
                ORDER BY created_at DESC 
                LIMIT ? OFFSET ?
            """, (limit, offset))
        rows = c.fetchall()
        return rows


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
def get_keyword_trends(days=30, keyword=None, user_id=None):
    """Get keyword trends over time"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        if keyword:
            c.execute("""
                SELECT date, keyword, count, avg_price, source
                FROM keyword_trends 
                WHERE date >= date('now', ? || ' days')
                  AND keyword = ?
                  AND user_id = ?
                ORDER BY date DESC
            """, (f'-{days}', keyword, user_id))
        else:
            c.execute("""
                SELECT date, keyword, count, avg_price, source
                FROM keyword_trends 
                WHERE date >= date('now', ? || ' days')
                  AND user_id = ?
                ORDER BY date DESC, count DESC
            """, (f'-{days}', user_id))
        
        rows = c.fetchall()
        return rows


@log_errors()
def get_price_analytics(days=30, source=None, keyword=None, user_id=None):
    """Get price analytics over time"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        # Build query with optional filters
        if keyword and source:
            c.execute("""
                SELECT DATE(l.created_at) as date, 
                       COUNT(*) as count,
                       AVG(l.price) as avg_price,
                       MIN(l.price) as min_price,
                       MAX(l.price) as max_price,
                       l.source
                FROM listings l
                JOIN listing_analytics la ON l.id = la.listing_id
                WHERE l.created_at >= datetime('now', ? || ' days')
                  AND l.source = ?
                  AND la.keyword = ?
                  AND l.user_id = ?
                GROUP BY DATE(l.created_at), l.source
                ORDER BY date DESC
            """, (f'-{days}', source, keyword, user_id))
        elif keyword:
            c.execute("""
                SELECT DATE(l.created_at) as date, 
                       COUNT(*) as count,
                       AVG(l.price) as avg_price,
                       MIN(l.price) as min_price,
                       MAX(l.price) as max_price,
                       l.source
                FROM listings l
                JOIN listing_analytics la ON l.id = la.listing_id
                WHERE l.created_at >= datetime('now', ? || ' days')
                  AND la.keyword = ?
                  AND l.user_id = ?
                GROUP BY DATE(l.created_at), l.source
                ORDER BY date DESC
            """, (f'-{days}', keyword, user_id))
        elif source:
            c.execute("""
                SELECT DATE(created_at) as date, 
                       COUNT(*) as count,
                       AVG(price) as avg_price,
                       MIN(price) as min_price,
                       MAX(price) as max_price,
                       source
                FROM listings 
                WHERE created_at >= datetime('now', ? || ' days')
                  AND source = ?
                  AND user_id = ?
                GROUP BY DATE(created_at), source
                ORDER BY date DESC
            """, (f'-{days}', source, user_id))
        else:
            c.execute("""
                SELECT DATE(created_at) as date, 
                       COUNT(*) as count,
                       AVG(price) as avg_price,
                       MIN(price) as min_price,
                       MAX(price) as max_price,
                       source
                FROM listings 
                WHERE created_at >= datetime('now', ? || ' days')
                  AND user_id = ?
                GROUP BY DATE(created_at), source
                ORDER BY date DESC
            """, (f'-{days}', user_id))
        
        rows = c.fetchall()
        return rows


@log_errors()
def get_source_comparison(days=30, keyword=None, user_id=None):
    """Compare performance across different sources"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        if keyword:
            c.execute("""
                SELECT l.source,
                       COUNT(*) as total_listings,
                       AVG(l.price) as avg_price,
                       MIN(l.price) as min_price,
                       MAX(l.price) as max_price,
                       COUNT(DISTINCT DATE(l.created_at)) as active_days
                FROM listings l
                JOIN listing_analytics la ON l.id = la.listing_id
                WHERE l.created_at >= datetime('now', ? || ' days')
                  AND la.keyword = ?
                  AND l.user_id = ?
                GROUP BY l.source
                ORDER BY total_listings DESC
            """, (f'-{days}', keyword, user_id))
        else:
            c.execute("""
                SELECT source,
                       COUNT(*) as total_listings,
                       AVG(price) as avg_price,
                       MIN(price) as min_price,
                       MAX(price) as max_price,
                       COUNT(DISTINCT DATE(created_at)) as active_days
                FROM listings 
                WHERE created_at >= datetime('now', ? || ' days')
                  AND user_id = ?
                GROUP BY source
                ORDER BY total_listings DESC
            """, (f'-{days}', user_id))
        
        rows = c.fetchall()
        return rows


@log_errors()
def get_keyword_analysis(days=30, limit=20, keyword=None, user_id=None):
    """Get top keywords and their performance"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        if keyword:
            # Return only the specified keyword
            c.execute("""
                SELECT la.keyword,
                       COUNT(*) as frequency,
                       AVG(l.price) as avg_price,
                       MIN(l.price) as min_price,
                       MAX(l.price) as max_price,
                       COUNT(DISTINCT la.source) as sources_count
                FROM listing_analytics la
                JOIN listings l ON la.listing_id = l.id
                WHERE la.created_at >= datetime('now', ? || ' days')
                  AND la.keyword = ?
                  AND l.user_id = ?
                GROUP BY la.keyword
            """, (f'-{days}', keyword, user_id))
        else:
            c.execute("""
                SELECT la.keyword,
                       COUNT(*) as frequency,
                       AVG(l.price) as avg_price,
                       MIN(l.price) as min_price,
                       MAX(l.price) as max_price,
                       COUNT(DISTINCT la.source) as sources_count
                FROM listing_analytics la
                JOIN listings l ON la.listing_id = l.id
                WHERE la.created_at >= datetime('now', ? || ' days')
                  AND l.user_id = ?
                GROUP BY la.keyword
                ORDER BY frequency DESC
                LIMIT ?
            """, (f'-{days}', user_id, limit))
        
        rows = c.fetchall()
        return rows


@log_errors()
def get_hourly_activity(days=7, keyword=None, user_id=None):
    """Get listing activity by hour of day"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        if keyword:
            c.execute("""
                SELECT strftime('%H', l.created_at) as hour,
                       COUNT(*) as count,
                       l.source
                FROM listings l
                JOIN listing_analytics la ON l.id = la.listing_id
                WHERE l.created_at >= datetime('now', ? || ' days')
                  AND la.keyword = ?
                  AND l.user_id = ?
                GROUP BY strftime('%H', l.created_at), l.source
                ORDER BY hour
            """, (f'-{days}', keyword, user_id))
        else:
            c.execute("""
                SELECT strftime('%H', created_at) as hour,
                       COUNT(*) as count,
                       source
                FROM listings 
                WHERE created_at >= datetime('now', ? || ' days')
                  AND user_id = ?
                GROUP BY strftime('%H', created_at), source
                ORDER BY hour
            """, (f'-{days}', user_id))
        
        rows = c.fetchall()
        return rows


@log_errors()
def get_price_distribution(days=30, bins=10, keyword=None, user_id=None):
    """Get price distribution data for histograms"""
    # Validate bins parameter to prevent division by zero
    if bins <= 0:
        logger.warning(f"Invalid bins parameter: {bins}, using default of 10")
        bins = 10
    
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        # Get min and max prices with optional keyword filter
        if keyword:
            c.execute("""
                SELECT MIN(l.price) as min_price, MAX(l.price) as max_price
                FROM listings l
                JOIN listing_analytics la ON l.id = la.listing_id
                WHERE l.created_at >= datetime('now', ? || ' days')
                  AND l.price > 0
                  AND la.keyword = ?
                  AND l.user_id = ?
            """, (f'-{days}', keyword, user_id))
        else:
            c.execute("""
                SELECT MIN(price) as min_price, MAX(price) as max_price
                FROM listings 
                WHERE created_at >= datetime('now', ? || ' days')
                  AND price > 0
                  AND user_id = ?
            """, (f'-{days}', user_id))
        
        result = c.fetchone()
        if not result or not result[0] or not result[1]:
            return []
        
        min_price, max_price = result
        
        # Handle edge case: all listings have the same price
        if min_price == max_price:
            return [{
                'range': f"${min_price:.0f}",
                'count': 1,
                'start': min_price,
                'end': max_price
            }]
        
        # Calculate bin size (bins is already validated to be > 0)
        bin_size = (max_price - min_price) / bins
        
        # Additional safety check
        if bin_size <= 0:
            logger.warning("Invalid bin_size calculated, returning empty distribution")
            return []
        
        price_ranges = []
        for i in range(bins):
            start = min_price + (i * bin_size)
            end = min_price + ((i + 1) * bin_size)
            
            # For the last bin, include the maximum price (fix off-by-one error)
            is_last_bin = (i == bins - 1)
            
            if keyword:
                if is_last_bin:
                    c.execute("""
                        SELECT COUNT(*) as count
                        FROM listings l
                        JOIN listing_analytics la ON l.id = la.listing_id
                        WHERE l.created_at >= datetime('now', ? || ' days')
                          AND l.price >= ? AND l.price <= ?
                          AND la.keyword = ?
                          AND l.user_id = ?
                    """, (f'-{days}', start, end, keyword, user_id))
                else:
                    c.execute("""
                        SELECT COUNT(*) as count
                        FROM listings l
                        JOIN listing_analytics la ON l.id = la.listing_id
                        WHERE l.created_at >= datetime('now', ? || ' days')
                          AND l.price >= ? AND l.price < ?
                          AND la.keyword = ?
                          AND l.user_id = ?
                    """, (f'-{days}', start, end, keyword, user_id))
            else:
                if is_last_bin:
                    c.execute("""
                        SELECT COUNT(*) as count
                        FROM listings 
                        WHERE created_at >= datetime('now', ? || ' days')
                          AND price >= ? AND price <= ?
                          AND user_id = ?
                    """, (f'-{days}', start, end, user_id))
                else:
                    c.execute("""
                        SELECT COUNT(*) as count
                        FROM listings 
                        WHERE created_at >= datetime('now', ? || ' days')
                          AND price >= ? AND price < ?
                          AND user_id = ?
                    """, (f'-{days}', start, end, user_id))
            
            count = c.fetchone()[0]
            price_ranges.append({
                'range': f"${start:.0f}-${end:.0f}",
                'count': count,
                'start': start,
                'end': end
            })
        
        return price_ranges


@log_errors()
def update_keyword_trends(user_id=None):
    """Update keyword trends from recent listings"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        # Get recent listings and extract keywords
        if user_id:
            c.execute("""
                SELECT id, title, price, source, created_at, user_id
                FROM listings 
                WHERE created_at >= datetime('now', '-1 day')
                  AND user_id = ?
            """, (user_id,))
        else:
            c.execute("""
                SELECT id, title, price, source, created_at, user_id
                FROM listings 
                WHERE created_at >= datetime('now', '-1 day')
            """)
        
        listings = c.fetchall()
        
        # Simple keyword extraction - group by user_id
        user_keywords = {}
        for listing in listings:
            listing_id, title, price, source, created_at, listing_user_id = listing
            title_lower = title.lower()
            
            if listing_user_id not in user_keywords:
                user_keywords[listing_user_id] = {}
            
            car_keywords = ['firebird', 'camaro', 'corvette', 'mustang', 'charger', 'challenger', 
                           'trans am', 'gto', 'nova', 'chevelle', 'impala', 'monte carlo']
            
            for keyword in car_keywords:
                if keyword in title_lower:
                    if keyword not in user_keywords[listing_user_id]:
                        user_keywords[listing_user_id][keyword] = {'count': 0, 'total_price': 0, 'sources': set()}
                    user_keywords[listing_user_id][keyword]['count'] += 1
                    user_keywords[listing_user_id][keyword]['total_price'] += price
                    user_keywords[listing_user_id][keyword]['sources'].add(source)
        
        # Save keyword trends per user
        today = datetime.now().date()
        for listing_user_id, keywords in user_keywords.items():
            for keyword, data in keywords.items():
                avg_price = data['total_price'] / data['count']
                for source in data['sources']:
                    c.execute("""
                        INSERT OR REPLACE INTO keyword_trends (keyword, count, avg_price, date, source, user_id)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (keyword, data['count'], avg_price, today, source, listing_user_id))
        
        conn.commit()


@log_errors()
def get_market_insights(days=30, keyword=None, user_id=None):
    """Get comprehensive market insights"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        # Build query with optional keyword filter
        if keyword:
            # Overall stats with keyword filter
            c.execute("""
                SELECT COUNT(*) as total_listings,
                       AVG(l.price) as avg_price,
                       MIN(l.price) as min_price,
                       MAX(l.price) as max_price,
                       COUNT(DISTINCT l.source) as sources_count
                FROM listings l
                JOIN listing_analytics la ON l.id = la.listing_id
                WHERE l.created_at >= datetime('now', ? || ' days')
                  AND la.keyword = ?
                  AND l.user_id = ?
            """, (f'-{days}', keyword, user_id))
        else:
            # Overall stats without filter
            c.execute("""
                SELECT COUNT(*) as total_listings,
                       AVG(price) as avg_price,
                       MIN(price) as min_price,
                       MAX(price) as max_price,
                       COUNT(DISTINCT source) as sources_count
                FROM listings 
                WHERE created_at >= datetime('now', ? || ' days')
                  AND user_id = ?
            """, (f'-{days}', user_id))
        
        overall_stats = c.fetchone()
        
        # Top performing keywords
        if keyword:
            # Only show the selected keyword
            c.execute("""
                SELECT la.keyword, COUNT(*) as count, AVG(l.price) as avg_price
                FROM listing_analytics la
                JOIN listings l ON la.listing_id = l.id
                WHERE la.created_at >= datetime('now', ? || ' days')
                  AND la.keyword = ?
                  AND l.user_id = ?
                GROUP BY la.keyword
                LIMIT 5
            """, (f'-{days}', keyword, user_id))
        else:
            c.execute("""
                SELECT la.keyword, COUNT(*) as count, AVG(l.price) as avg_price
                FROM listing_analytics la
                JOIN listings l ON la.listing_id = l.id
                WHERE la.created_at >= datetime('now', ? || ' days')
                  AND l.user_id = ?
                GROUP BY la.keyword
                ORDER BY count DESC
                LIMIT 5
            """, (f'-{days}', user_id))
        
        top_keywords = c.fetchall()
        
        # Source performance
        if keyword:
            c.execute("""
                SELECT l.source, COUNT(*) as count, AVG(l.price) as avg_price
                FROM listings l
                JOIN listing_analytics la ON l.id = la.listing_id
                WHERE l.created_at >= datetime('now', ? || ' days')
                  AND la.keyword = ?
                  AND l.user_id = ?
                GROUP BY l.source
                ORDER BY count DESC
            """, (f'-{days}', keyword, user_id))
        else:
            c.execute("""
                SELECT source, COUNT(*) as count, AVG(price) as avg_price
                FROM listings 
                WHERE created_at >= datetime('now', ? || ' days')
                  AND user_id = ?
                GROUP BY source
                ORDER BY count DESC
            """, (f'-{days}', user_id))
        
        source_performance = c.fetchall()
        
        return {
            'overall_stats': overall_stats,
            'top_keywords': top_keywords,
            'source_performance': source_performance
        }


# ======================
# SELLER LISTINGS
# ======================

@log_errors()
def create_seller_listing(username, title, description, price, category, location, images, marketplaces, original_cost=None):
    """Create a new seller listing"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO seller_listings (username, title, description, price, original_cost, category, location, images, marketplaces)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (username, title, description, price, original_cost, category, location, images, marketplaces))
        conn.commit()
        return c.lastrowid


@log_errors()
def get_seller_listings(username=None, status=None, limit=100):
    """Get seller listings for a user or all listings"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        query = "SELECT * FROM seller_listings WHERE 1=1"
        params = []
        
        if username:
            query += " AND username = ?"
            params.append(username)
        
        if status:
            query += " AND status = ?"
            params.append(status)
        
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        
        c.execute(query, params)
        rows = c.fetchall()
        
        # Convert to list of dicts for easier handling
        columns = [desc[0] for desc in c.description]
        return [dict(zip(columns, row)) for row in rows]


@log_errors()
def get_seller_listing_by_id(listing_id):
    """Get a specific seller listing by ID"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM seller_listings WHERE id = ?", (listing_id,))
        row = c.fetchone()
        if row:
            columns = [desc[0] for desc in c.description]
            return dict(zip(columns, row))
        return None


@log_errors()
def update_seller_listing(listing_id, **kwargs):
    """Update a seller listing"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        # Build update query dynamically based on provided kwargs
        allowed_fields = ['title', 'description', 'price', 'original_cost', 'category', 'location', 'images', 'marketplaces', 'status']
        updates = []
        values = []
        
        for field in allowed_fields:
            if field in kwargs:
                updates.append(f"{field} = ?")
                values.append(kwargs[field])
        
        if not updates:
            return False
        
        # Always update updated_at
        updates.append("updated_at = CURRENT_TIMESTAMP")
        
        query = f"UPDATE seller_listings SET {', '.join(updates)} WHERE id = ?"
        values.append(listing_id)
        
        c.execute(query, values)
        conn.commit()
        return c.rowcount > 0


@log_errors()
def delete_seller_listing(listing_id, username):
    """Delete a seller listing (only if owned by user)"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM seller_listings WHERE id = ? AND username = ?", (listing_id, username))
        conn.commit()
        return c.rowcount > 0


@log_errors()
def update_seller_listing_urls(listing_id, craigslist_url=None, facebook_url=None, ksl_url=None):
    """Update marketplace URLs after posting"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        updates = []
        values = []
        
        if craigslist_url is not None:
            updates.append("craigslist_url = ?")
            values.append(craigslist_url)
        
        if facebook_url is not None:
            updates.append("facebook_url = ?")
            values.append(facebook_url)
        
        if ksl_url is not None:
            updates.append("ksl_url = ?")
            values.append(ksl_url)
        
        if updates:
            updates.append("posted_at = CURRENT_TIMESTAMP")
            updates.append("status = 'posted'")
            query = f"UPDATE seller_listings SET {', '.join(updates)} WHERE id = ?"
            values.append(listing_id)
            
            c.execute(query, values)
            conn.commit()
            return True
        
        return False


@log_errors()
def update_seller_listing_status(listing_id, username, status, sold_on_marketplace=None, actual_sale_price=None):
    """Update the status of a seller listing"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        # Build update query based on what's being updated
        updates = ["status = ?", "updated_at = CURRENT_TIMESTAMP"]
        values = [status]
        
        # If marking as sold, update additional fields
        if status == 'sold':
            updates.append("sold_at = CURRENT_TIMESTAMP")
            if sold_on_marketplace:
                updates.append("sold_on_marketplace = ?")
                values.append(sold_on_marketplace)
            if actual_sale_price is not None:
                updates.append("actual_sale_price = ?")
                values.append(actual_sale_price)
        
        # Add WHERE clause parameters
        values.extend([listing_id, username])
        
        query = f"UPDATE seller_listings SET {', '.join(updates)} WHERE id = ? AND username = ?"
        c.execute(query, values)
        
        conn.commit()
        return c.rowcount > 0


@log_errors()
def get_seller_listing_stats(username):
    """Get statistics about user's seller listings"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        c.execute("""
            SELECT 
                COUNT(*) as total_listings,
                SUM(CASE WHEN status = 'draft' THEN 1 ELSE 0 END) as draft_count,
                SUM(CASE WHEN status = 'posted' THEN 1 ELSE 0 END) as posted_count,
                SUM(CASE WHEN status = 'sold' THEN 1 ELSE 0 END) as sold_count,
                SUM(CASE WHEN status = 'sold' THEN COALESCE(actual_sale_price, price) ELSE 0 END) as gross_revenue,
                SUM(CASE WHEN status = 'sold' AND original_cost IS NOT NULL THEN COALESCE(actual_sale_price, price) - original_cost ELSE 0 END) as true_profit,
                SUM(CASE WHEN status = 'sold' AND original_cost IS NOT NULL THEN original_cost ELSE 0 END) as total_costs,
                SUM(CASE WHEN status = 'sold' THEN price ELSE 0 END) as original_value,
                AVG(price) as avg_listing_price,
                AVG(CASE WHEN status = 'sold' THEN COALESCE(actual_sale_price, price) END) as avg_sale_price
            FROM seller_listings
            WHERE username = ?
        """, (username,))
        
        row = c.fetchone()
        
        # Validate row structure before accessing indices
        if not row or len(row) < 10:
            logger.error(f"Invalid seller listing stats row structure: {row}")
            return {
                'total_listings': 0,
                'draft_count': 0,
                'posted_count': 0,
                'sold_count': 0,
                'gross_revenue': 0,
                'true_profit': 0,
                'total_costs': 0,
                'net_revenue': 0,
                'avg_listing_price': 0,
                'avg_sale_price': 0,
                'marketplace_breakdown': {}
            }
        
        gross_revenue = row[4] if row[4] is not None else 0
        true_profit = row[5] if row[5] is not None else 0  # Actual profit: (sale price - original cost)
        total_costs = row[6] if row[6] is not None else 0
        original_value = row[7] if row[7] is not None else 0
        net_revenue = gross_revenue - original_value  # Price adjustments: (sale price - listing price)
        
        # Get marketplace breakdown for sold items
        c.execute("""
            SELECT 
                sold_on_marketplace,
                COUNT(*) as count,
                SUM(COALESCE(actual_sale_price, price)) as revenue
            FROM seller_listings
            WHERE username = ? AND status = 'sold' AND sold_on_marketplace IS NOT NULL
            GROUP BY sold_on_marketplace
        """, (username,))
        
        marketplace_data = {}
        for mp_row in c.fetchall():
            marketplace = mp_row[0]
            marketplace_data[marketplace] = {
                'count': mp_row[1],
                'revenue': mp_row[2] or 0
            }
        
        return {
            'total_listings': row[0] or 0,
            'draft_count': row[1] or 0,
            'posted_count': row[2] or 0,
            'sold_count': row[3] or 0,
            'gross_revenue': gross_revenue,  # Total money received
            'true_profit': true_profit,  # Actual profit after costs
            'total_costs': total_costs,  # Total original costs
            'net_revenue': net_revenue,  # Price adjustment profit/loss
            'avg_listing_price': row[8] or 0,
            'avg_sale_price': row[9] or 0,
            'marketplace_breakdown': marketplace_data
        }


# ======================
# SUBSCRIPTION MANAGEMENT
# ======================

@log_errors()
def get_user_subscription(username):
    """Get user's subscription information"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT tier, status, stripe_customer_id, stripe_subscription_id, 
                   current_period_start, current_period_end, cancel_at_period_end,
                   created_at, updated_at
            FROM subscriptions
            WHERE username = ?
        """, (username,))
        
        row = c.fetchone()
        if row:
            return {
                'tier': row[0],
                'status': row[1],
                'stripe_customer_id': row[2],
                'stripe_subscription_id': row[3],
                'current_period_start': row[4],
                'current_period_end': row[5],
                'cancel_at_period_end': row[6],
                'created_at': row[7],
                'updated_at': row[8]
            }
        
        # Return default free tier if no subscription found
        return {
            'tier': 'free',
            'status': 'active',
            'stripe_customer_id': None,
            'stripe_subscription_id': None,
            'current_period_start': None,
            'current_period_end': None,
            'cancel_at_period_end': False,
            'created_at': None,
            'updated_at': None
        }


@log_errors()
def create_or_update_subscription(username, tier, status='active', stripe_customer_id=None, 
                                   stripe_subscription_id=None, current_period_start=None,
                                   current_period_end=None, cancel_at_period_end=False):
    """Create or update user's subscription"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        # Check if subscription exists
        c.execute("SELECT id FROM subscriptions WHERE username = ?", (username,))
        existing = c.fetchone()
        
        if existing:
            # Update existing subscription
            c.execute("""
                UPDATE subscriptions 
                SET tier = ?, status = ?, stripe_customer_id = ?, stripe_subscription_id = ?,
                    current_period_start = ?, current_period_end = ?, cancel_at_period_end = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE username = ?
            """, (tier, status, stripe_customer_id, stripe_subscription_id,
                  current_period_start, current_period_end, cancel_at_period_end, username))
        else:
            # Create new subscription
            c.execute("""
                INSERT INTO subscriptions (username, tier, status, stripe_customer_id, 
                                          stripe_subscription_id, current_period_start, 
                                          current_period_end, cancel_at_period_end)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (username, tier, status, stripe_customer_id, stripe_subscription_id,
                  current_period_start, current_period_end, cancel_at_period_end))
        
        # Also update the users table for quick access
        c.execute("UPDATE users SET subscription_tier = ? WHERE username = ?", (tier, username))
        
        conn.commit()
        return True


@log_errors()
def log_security_event(ip, path, user_agent, reason, timestamp=None):
    """Log security events for monitoring and analysis with enhanced error handling"""
    if timestamp is None:
        timestamp = datetime.now()
    
    try:
        with get_pool().get_connection() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO security_events (ip_address, path, user_agent, reason, timestamp)
                VALUES (?, ?, ?, ?, ?)
            """, (ip, path, user_agent, reason, timestamp))
            conn.commit()
            return True
    except sqlite3.OperationalError as e:
        if "database is locked" in str(e).lower():
            logger.warning(f"Database locked while logging security event for IP {ip}")
            raise  # Re-raise to trigger retry mechanism
        else:
            logger.error(f"Database error logging security event: {e}")
            raise
    except Exception as e:
        logger.error(f"Unexpected error logging security event: {e}")
        raise


@log_errors()
def get_security_events(limit=100, hours=24):
    """Get recent security events"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        cutoff_time = datetime.now() - timedelta(hours=hours)
        c.execute("""
            SELECT ip_address, path, user_agent, reason, timestamp
            FROM security_events
            WHERE timestamp > ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (cutoff_time, limit))
        
        rows = c.fetchall()
        return [{
            'ip_address': row[0],
            'path': row[1],
            'user_agent': row[2],
            'reason': row[3],
            'timestamp': datetime.fromisoformat(row[4]) if isinstance(row[4], str) else row[4]
        } for row in rows]


@log_errors()
def log_subscription_event(username, tier, action, stripe_event_id=None, details=None):
    """Log subscription-related events"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO subscription_history (username, tier, action, stripe_event_id, details)
            VALUES (?, ?, ?, ?, ?)
        """, (username, tier, action, stripe_event_id, details))
        conn.commit()
        return True


@log_errors()
def get_subscription_history(username, limit=50):
    """Get subscription history for a user"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT tier, action, stripe_event_id, details, created_at
            FROM subscription_history
            WHERE username = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (username, limit))
        
        rows = c.fetchall()
        return [{
            'tier': row[0],
            'action': row[1],
            'stripe_event_id': row[2],
            'details': row[3],
            'created_at': row[4]
        } for row in rows]


@log_errors()
def cancel_subscription(username):
    """Cancel a user's subscription (sets to free tier)"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            UPDATE subscriptions 
            SET tier = 'free', status = 'cancelled', cancel_at_period_end = 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE username = ?
        """, (username,))
        
        # Update users table
        c.execute("UPDATE users SET subscription_tier = 'free' WHERE username = ?", (username,))
        
        conn.commit()
        return True


@log_errors()
def get_all_subscriptions(tier=None, status=None):
    """Get all subscriptions with optional filtering"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        query = "SELECT username, tier, status, stripe_customer_id, current_period_end, created_at FROM subscriptions WHERE 1=1"
        params = []
        
        if tier:
            query += " AND tier = ?"
            params.append(tier)
        
        if status:
            query += " AND status = ?"
            params.append(status)
        
        query += " ORDER BY created_at DESC"
        
        c.execute(query, params)
        rows = c.fetchall()
        
        return [{
            'username': row[0],
            'tier': row[1],
            'status': row[2],
            'stripe_customer_id': row[3],
            'current_period_end': row[4],
            'created_at': row[5]
        } for row in rows]


@log_errors()
def get_subscription_by_customer_id(stripe_customer_id):
    """Get subscription by Stripe customer ID"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT username, tier, status, stripe_subscription_id, 
                   current_period_start, current_period_end
            FROM subscriptions
            WHERE stripe_customer_id = ?
        """, (stripe_customer_id,))
        
        row = c.fetchone()
        if row:
            return {
                'username': row[0],
                'tier': row[1],
                'status': row[2],
                'stripe_subscription_id': row[3],
                'current_period_start': row[4],
                'current_period_end': row[5]
            }
        return None


@log_errors()
def get_subscription_stats():
    """Get subscription statistics for admin dashboard"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        c.execute("""
            SELECT 
                COUNT(*) as total_subscriptions,
                SUM(CASE WHEN tier = 'free' THEN 1 ELSE 0 END) as free_count,
                SUM(CASE WHEN tier = 'standard' THEN 1 ELSE 0 END) as standard_count,
                SUM(CASE WHEN tier = 'pro' THEN 1 ELSE 0 END) as pro_count,
                SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) as active_count,
                SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) as cancelled_count
            FROM subscriptions
        """)
        
        row = c.fetchone()
        return {
            'total_subscriptions': row[0] or 0,
            'free_count': row[1] or 0,
            'standard_count': row[2] or 0,
            'pro_count': row[3] or 0,
            'active_count': row[4] or 0,
            'cancelled_count': row[5] or 0
        }


# ======================
# CLEANUP
# ======================
# EMAIL VERIFICATION & PASSWORD RESET
# ======================

@log_errors()
def create_verification_token(username, token, expiration_hours=24):
    """Create an email verification token"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        expires_at = datetime.now() + timedelta(hours=expiration_hours)
        c.execute("""
            INSERT INTO email_verification_tokens (username, token, expires_at)
            VALUES (?, ?, ?)
        """, (username, token, expires_at))
        conn.commit()
        return True


@log_errors()
def verify_email_token(token):
    """Verify an email token and mark user as verified"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        # Check if token exists and is valid
        c.execute("""
            SELECT username, expires_at, used
            FROM email_verification_tokens
            WHERE token = ?
        """, (token,))
        
        result = c.fetchone()
        if not result:
            return False, "Invalid verification token"
        
        username, expires_at, used = result
        
        if used:
            return False, "Token already used"
        
        # Check expiration
        expires_at = datetime.fromisoformat(expires_at)
        if datetime.now() > expires_at:
            return False, "Token has expired"
        
        # Mark token as used
        c.execute("""
            UPDATE email_verification_tokens
            SET used = 1
            WHERE token = ?
        """, (token,))
        
        # Mark user as verified
        c.execute("""
            UPDATE users
            SET verified = 1
            WHERE username = ?
        """, (username,))
        
        conn.commit()
        logger.info(f"Email verified for user: {username}")
        return True, username


@log_errors()
def create_password_reset_token(username, token, expiration_hours=1):
    """Create a password reset token"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        expires_at = datetime.now() + timedelta(hours=expiration_hours)
        c.execute("""
            INSERT INTO password_reset_tokens (username, token, expires_at)
            VALUES (?, ?, ?)
        """, (username, token, expires_at))
        conn.commit()
        return True


@log_errors()
def verify_password_reset_token(token):
    """Verify a password reset token"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        c.execute("""
            SELECT username, expires_at, used
            FROM password_reset_tokens
            WHERE token = ?
        """, (token,))
        
        result = c.fetchone()
        if not result:
            return False, None
        
        username, expires_at, used = result
        
        if used:
            return False, None
        
        expires_at = datetime.fromisoformat(expires_at)
        if datetime.now() > expires_at:
            return False, None
        
        return True, username


@log_errors()
def use_password_reset_token(token):
    """Mark a password reset token as used"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            UPDATE password_reset_tokens
            SET used = 1
            WHERE token = ?
        """, (token,))
        conn.commit()
        return True


@log_errors()
def reset_user_password(username, new_password_hash):
    """Reset a user's password"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            UPDATE users
            SET password = ?
            WHERE username = ?
        """, (new_password_hash, username))
        conn.commit()
        logger.info(f"Password reset for user: {username}")
        return True


# ======================
# FAVORITES / BOOKMARKS
# ======================

@log_errors()
def add_favorite(username, listing_id, notes=None):
    """Add a listing to user's favorites"""
    try:
        with get_pool().get_connection() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO favorites (username, listing_id, notes)
                VALUES (?, ?, ?)
            """, (username, listing_id, notes))
            conn.commit()
            logger.info(f"Added favorite for {username}: listing {listing_id}")
            return True
    except sqlite3.IntegrityError:
        # Already favorited
        return False


@log_errors()
def remove_favorite(username, listing_id):
    """Remove a listing from user's favorites"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            DELETE FROM favorites
            WHERE username = ? AND listing_id = ?
        """, (username, listing_id))
        conn.commit()
        return c.rowcount > 0


@log_errors()
def get_favorites(username, limit=100):
    """Get user's favorite listings"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT l.id, l.title, l.price, l.link, l.image_url, l.source, l.created_at,
                   f.notes, f.created_at as favorited_at
            FROM favorites f
            JOIN listings l ON f.listing_id = l.id
            WHERE f.username = ?
            ORDER BY f.created_at DESC
            LIMIT ?
        """, (username, limit))
        
        rows = c.fetchall()
        return [{
            'id': row[0],
            'title': row[1],
            'price': row[2],
            'link': row[3],
            'image_url': row[4],
            'source': row[5],
            'created_at': row[6],
            'notes': row[7],
            'favorited_at': row[8]
        } for row in rows]


@log_errors()
def is_favorited(username, listing_id):
    """Check if a listing is favorited by user"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT 1 FROM favorites
            WHERE username = ? AND listing_id = ?
        """, (username, listing_id))
        return c.fetchone() is not None


@log_errors()
def update_favorite_notes(username, listing_id, notes):
    """Update notes for a favorite"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            UPDATE favorites
            SET notes = ?
            WHERE username = ? AND listing_id = ?
        """, (notes, username, listing_id))
        conn.commit()
        return c.rowcount > 0


# ======================
# SAVED SEARCHES
# ======================

@log_errors()
def create_saved_search(username, name, keywords=None, min_price=None, max_price=None, 
                       sources=None, location=None, radius=None, notify_new=True):
    """Create a saved search"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO saved_searches 
            (username, name, keywords, min_price, max_price, sources, location, radius, notify_new)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (username, name, keywords, min_price, max_price, sources, location, radius, notify_new))
        conn.commit()
        return c.lastrowid


@log_errors()
def get_saved_searches(username):
    """Get all saved searches for a user"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT id, name, keywords, min_price, max_price, sources, location, radius,
                   notify_new, created_at, last_run
            FROM saved_searches
            WHERE username = ?
            ORDER BY created_at DESC
        """, (username,))
        
        rows = c.fetchall()
        return [{
            'id': row[0],
            'name': row[1],
            'keywords': row[2],
            'min_price': row[3],
            'max_price': row[4],
            'sources': row[5],
            'location': row[6],
            'radius': row[7],
            'notify_new': row[8],
            'created_at': row[9],
            'last_run': row[10]
        } for row in rows]


@log_errors()
def delete_saved_search(search_id, username):
    """Delete a saved search"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            DELETE FROM saved_searches
            WHERE id = ? AND username = ?
        """, (search_id, username))
        conn.commit()
        return c.rowcount > 0


@log_errors()
def update_saved_search_last_run(search_id):
    """Update the last run timestamp for a saved search"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            UPDATE saved_searches
            SET last_run = ?
            WHERE id = ?
        """, (datetime.now(), search_id))
        conn.commit()


# ======================
# PRICE ALERTS
# ======================

@log_errors()
def create_price_alert(username, keywords, threshold_price, alert_type='under'):
    """Create a price alert"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO price_alerts (username, keywords, threshold_price, alert_type)
            VALUES (?, ?, ?, ?)
        """, (username, keywords, threshold_price, alert_type))
        conn.commit()
        return c.lastrowid


@log_errors()
def get_price_alerts(username):
    """Get all price alerts for a user"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT id, keywords, threshold_price, alert_type, active, last_triggered, created_at
            FROM price_alerts
            WHERE username = ?
            ORDER BY created_at DESC
        """, (username,))
        
        rows = c.fetchall()
        return [{
            'id': row[0],
            'keywords': row[1],
            'threshold_price': row[2],
            'alert_type': row[3],
            'active': row[4],
            'last_triggered': row[5],
            'created_at': row[6]
        } for row in rows]


@log_errors()
def delete_price_alert(alert_id, username):
    """Delete a price alert"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            DELETE FROM price_alerts
            WHERE id = ? AND username = ?
        """, (alert_id, username))
        conn.commit()
        return c.rowcount > 0


@log_errors()
def toggle_price_alert(alert_id, username):
    """Toggle a price alert active status"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            UPDATE price_alerts
            SET active = NOT active
            WHERE id = ? AND username = ?
        """, (alert_id, username))
        conn.commit()
        return c.rowcount > 0


@log_errors()
def update_price_alert_triggered(alert_id):
    """Update the last triggered timestamp"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            UPDATE price_alerts
            SET last_triggered = ?
            WHERE id = ?
        """, (datetime.now(), alert_id))
        conn.commit()


@log_errors()
def get_active_price_alerts():
    """Get all active price alerts"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT id, username, keywords, threshold_price, alert_type, last_triggered
            FROM price_alerts
            WHERE active = 1
        """)
        
        rows = c.fetchall()
        return [{
            'id': row[0],
            'username': row[1],
            'keywords': row[2],
            'threshold_price': row[3],
            'alert_type': row[4],
            'last_triggered': row[5]
        } for row in rows]


# ======================

def close_database():
    """Close all database connections"""
    global _connection_pool
    if _connection_pool:
        _connection_pool.close_all()
        _connection_pool = None
    
    # Stop the activity logger
    stop_activity_logger()


# Start the activity logger when module is imported
start_activity_logger()
