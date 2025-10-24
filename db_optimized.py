# db_optimized.py - Optimized database module to prevent locking issues
import sqlite3
import threading
import time
import random
from datetime import datetime, timedelta
from contextlib import contextmanager
from queue import Queue, Empty
from error_handling import ErrorHandler, log_errors, DatabaseError
from utils import logger

DB_FILE = "superbot.db"

# Optimized connection pool configuration
POOL_SIZE = 20  # Reduced from 50 to prevent over-connection
CONNECTION_TIMEOUT = 30  # Reduced timeout
MAX_RETRIES = 3  # Reduced retries to fail faster
BASE_DELAY = 0.05  # Faster retry delays

class OptimizedDatabaseConnectionPool:
    """Optimized connection pool to prevent database locking"""
    
    def __init__(self, database, pool_size=POOL_SIZE):
        self.database = database
        self.pool_size = pool_size
        self.pool = Queue(maxsize=pool_size)
        self.all_connections = []
        self.lock = threading.Lock()
        self.connection_count = 0
        self.max_connections = pool_size * 2  # Allow temporary overflow
        self._initialize_pool()
    
    def _initialize_pool(self):
        """Initialize the connection pool with optimized settings"""
        for _ in range(self.pool_size):
            conn = self._create_connection()
            self.pool.put(conn)
            self.all_connections.append(conn)
        logger.info(f"Initialized optimized database connection pool with {self.pool_size} connections")
    
    def _create_connection(self):
        """Create a new database connection with optimal settings for concurrency"""
        conn = sqlite3.connect(
            self.database,
            check_same_thread=False,
            timeout=5,  # Shorter timeout
            isolation_level=None  # Autocommit mode
        )
        
        # Optimized PRAGMA settings for high concurrency
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=1000")  # 1 second timeout
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=10000")  # Reduced cache size
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA read_uncommitted=1")
        conn.execute("PRAGMA locking_mode=NORMAL")
        conn.execute("PRAGMA wal_autocheckpoint=1000")  # More frequent WAL checkpoints
        conn.execute("PRAGMA optimize")
        
        return conn
    
    @contextmanager
    def get_connection(self):
        """Get a connection from the pool with improved error handling"""
        conn = None
        start_time = time.time()
        
        try:
            # Try to get connection from pool with timeout
            conn = self.pool.get(timeout=CONNECTION_TIMEOUT)
            
            # Quick connection test
            try:
                conn.execute("SELECT 1").fetchone()
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e).lower():
                    # Don't return locked connections to pool
                    conn.close()
                    conn = None
                    raise DatabaseError("Database is locked")
            
            yield conn
            
        except Empty:
            # Pool exhausted - create temporary connection if under limit
            with self.lock:
                if self.connection_count < self.max_connections:
                    conn = self._create_connection()
                    self.connection_count += 1
                    logger.warning(f"Created temporary connection ({self.connection_count}/{self.max_connections})")
                else:
                    raise DatabaseError("Database connection pool exhausted")
            
            try:
                yield conn
            finally:
                if conn:
                    conn.close()
                    with self.lock:
                        self.connection_count -= 1
                        
        except Exception as e:
            logger.error(f"Database connection error: {e}")
            raise
            
        finally:
            if conn and hasattr(self, 'pool'):
                try:
                    # Only return healthy connections to pool
                    conn.execute("SELECT 1").fetchone()
                    self.pool.put(conn)
                except Exception:
                    # Bad connection - close it
                    conn.close()
                    with self.lock:
                        if self.connection_count > 0:
                            self.connection_count -= 1
    
    def close_all(self):
        """Close all connections in the pool"""
        with self.lock:
            for conn in self.all_connections:
                try:
                    conn.close()
                except Exception as e:
                    logger.error(f"Error closing connection: {e}")
            self.all_connections.clear()
            self.connection_count = 0
            logger.info("Closed all database connections")

# Global connection pool instance
_connection_pool = None

def get_pool():
    """Get the global connection pool instance"""
    global _connection_pool
    if _connection_pool is None:
        _connection_pool = OptimizedDatabaseConnectionPool(DB_FILE)
    return _connection_pool

def reset_connection_pool():
    """Reset the connection pool"""
    global _connection_pool
    if _connection_pool:
        _connection_pool.close_all()
        _connection_pool = None
    logger.info("Connection pool reset successfully")

def optimized_retry_db_operation(operation_func, max_retries=MAX_RETRIES, base_delay=BASE_DELAY):
    """
    Optimized retry mechanism with faster failure and better error handling
    """
    for attempt in range(max_retries):
        try:
            return operation_func()
        except sqlite3.OperationalError as e:
            error_msg = str(e).lower()
            if "database is locked" in error_msg:
                if attempt < max_retries - 1:
                    # Faster retry with shorter delays
                    delay = base_delay * (1.5 ** attempt) + random.uniform(0, 0.05)
                    logger.warning(f"Database locked, retrying in {delay:.3f}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(delay)
                    continue
                else:
                    logger.error(f"Database locked after {max_retries} attempts - failing fast")
                    return None
            elif "database is busy" in error_msg:
                if attempt < max_retries - 1:
                    delay = base_delay * (1.2 ** attempt) + random.uniform(0, 0.02)
                    logger.warning(f"Database busy, retrying in {delay:.3f}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(delay)
                    continue
                else:
                    logger.error(f"Database busy after {max_retries} attempts")
                    return None
            else:
                # Other database errors - don't retry
                logger.error(f"Database error: {e}")
                return None
        except Exception as e:
            logger.error(f"Unexpected error in database operation: {e}")
            return None
    
    return None

# Database initialization with optimized settings
@log_errors()
def initialize_database():
    """Initialize database with optimized settings"""
    try:
        with get_pool().get_connection() as conn:
            c = conn.cursor()
            
            # Set optimal database settings
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.execute("PRAGMA cache_size=10000")
            c.execute("PRAGMA temp_store=MEMORY")
            c.execute("PRAGMA busy_timeout=1000")
            c.execute("PRAGMA wal_autocheckpoint=1000")
            
            # Create tables with optimized indexes
            c.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    verified BOOLEAN DEFAULT 0,
                    role TEXT DEFAULT 'user',
                    active BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_login TIMESTAMP,
                    login_count INTEGER DEFAULT 0
                )
            """)
            
            # Create optimized indexes
            c.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_users_active ON users(active)")
            
            # Rate limits table with optimized structure
            c.execute("""
                CREATE TABLE IF NOT EXISTS rate_limits (
                    username TEXT NOT NULL,
                    endpoint TEXT NOT NULL,
                    request_count INTEGER DEFAULT 0,
                    window_start TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (username, endpoint)
                )
            """)
            
            c.execute("CREATE INDEX IF NOT EXISTS idx_rate_limits_lookup ON rate_limits(username, endpoint)")
            
            conn.commit()
            logger.info("Database initialized successfully with optimized settings")
            return True
            
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        return False

# Optimized user functions
@log_errors()
def get_user_by_username_optimized(username):
    """Optimized user lookup with better error handling"""
    def _get_user():
        with get_pool().get_connection() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT username, email, password, verified, role, active, created_at, last_login, login_count 
                FROM users 
                WHERE username = ? AND active = 1
            """, (username,))
            result = c.fetchone()
            if result:
                return {
                    'username': result[0],
                    'email': result[1],
                    'password': result[2],
                    'verified': bool(result[3]),
                    'role': result[4],
                    'active': bool(result[5]),
                    'created_at': result[6],
                    'last_login': result[7],
                    'login_count': result[8]
                }
            return None
    
    return optimized_retry_db_operation(_get_user)

# Database health check
@log_errors()
def check_database_health():
    """Check database health and connection pool status"""
    try:
        with get_pool().get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT 1")
            result = c.fetchone()
            
            if result:
                logger.info("Database health check passed")
                return True
            else:
                logger.error("Database health check failed")
                return False
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False

# Connection pool monitoring
def get_connection_pool_status():
    """Get current connection pool status"""
    global _connection_pool
    if _connection_pool:
        return {
            'pool_size': _connection_pool.pool_size,
            'active_connections': _connection_pool.connection_count,
            'pool_available': _connection_pool.pool.qsize(),
            'max_connections': _connection_pool.max_connections
        }
    return None
