# db.py
import sqlite3
from datetime import datetime
from error_handling import ErrorHandler, log_errors, DatabaseError
from utils import logger

DB_FILE = "superbot.db"

@log_errors()
def init_db():
    try:
        conn = sqlite3.connect(DB_FILE)
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
                created_at DATETIME
            )
        """)
        
        # Settings table - now supports user-specific settings
        c.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT,
                key TEXT,
                value TEXT,
                UNIQUE(username, key)
            )
        """)
        
        # Users table for authentication
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE,
                email TEXT,
                password TEXT,
                verified BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
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
                FOREIGN KEY (listing_id) REFERENCES listings (id)
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
                FOREIGN KEY (listing_id) REFERENCES listings (id)
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
        
        # Create indexes for better performance
        c.execute("CREATE INDEX IF NOT EXISTS idx_listings_created_at ON listings(created_at)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_listings_source ON listings(source)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_listings_price ON listings(price)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_analytics_keyword ON listing_analytics(keyword)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_analytics_date ON listing_analytics(created_at)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_trends_date ON keyword_trends(date)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_trends_keyword ON keyword_trends(keyword)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_market_stats_date ON market_stats(date)")
        
        conn.commit()
        conn.close()
        logger.info("Database initialized successfully")
    except sqlite3.Error as e:
        logger.error(f"Database initialization error: {e}")
        raise DatabaseError(f"Failed to initialize database: {e}")
    except Exception as e:
        logger.error(f"Unexpected error initializing database: {e}")
        raise

def get_settings(username=None):
    """Get settings for a specific user, or global settings if username is None"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    if username:
        c.execute("SELECT key, value FROM settings WHERE username = ?", (username,))
    else:
        c.execute("SELECT key, value FROM settings WHERE username IS NULL")
    settings = dict(c.fetchall())
    conn.close()
    return settings

def update_setting(key, value, username=None):
    """Update setting for a specific user, or global setting if username is None"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (username, key, value) VALUES (?, ?, ?)", (username, key, value))
    conn.commit()
    conn.close()

def get_user_by_username(username):
    """Get user by username"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT username, email, password, verified FROM users WHERE username = ?", (username,))
    user = c.fetchone()
    conn.close()
    return user

def create_user_db(username, email, password_hash):
    """Create a new user in the database"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (username, email, password) VALUES (?, ?, ?)", 
                 (username, email, password_hash))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False  # User already exists
    finally:
        conn.close()

def get_all_users():
    """Get all users from database"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT username, email, password, verified FROM users")
    users = c.fetchall()
    conn.close()
    return users

def save_listing(title, price, link, image_url=None, source=None):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Insert the listing
    c.execute("""
        INSERT OR IGNORE INTO listings (title, price, link, image_url, source, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (title, price, link, image_url, source, datetime.now()))
    
    # Get the listing ID for analytics
    listing_id = c.lastrowid
    if listing_id == 0:  # If no new row was inserted (duplicate)
        c.execute("SELECT id FROM listings WHERE link = ?", (link,))
        result = c.fetchone()
        listing_id = result[0] if result else None
    
    conn.commit()
    conn.close()
    
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

def get_listings(limit=100):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT title, price, link, image_url, source, created_at FROM listings ORDER BY created_at DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return rows

# ======================
# ANALYTICS FUNCTIONS
# ======================

def save_listing_analytics(listing_id, keyword, category, price_range, source):
    """Save analytics data for a listing"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        INSERT INTO listing_analytics (listing_id, keyword, category, price_range, source, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (listing_id, keyword, category, price_range, source, datetime.now()))
    conn.commit()
    conn.close()

def get_keyword_trends(days=30, keyword=None):
    """Get keyword trends over time"""
    conn = sqlite3.connect(DB_FILE)
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
    conn.close()
    return rows

def get_price_analytics(days=30, source=None):
    """Get price analytics over time"""
    conn = sqlite3.connect(DB_FILE)
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
    conn.close()
    return rows

def get_source_comparison(days=30):
    """Compare performance across different sources"""
    conn = sqlite3.connect(DB_FILE)
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
    conn.close()
    return rows

def get_keyword_analysis(days=30, limit=20):
    """Get top keywords and their performance"""
    conn = sqlite3.connect(DB_FILE)
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
    conn.close()
    return rows

def get_hourly_activity(days=7):
    """Get listing activity by hour of day"""
    conn = sqlite3.connect(DB_FILE)
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
    conn.close()
    return rows

def get_price_distribution(days=30, bins=10):
    """Get price distribution data for histograms"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        SELECT MIN(price) as min_price, MAX(price) as max_price
        FROM listings 
        WHERE created_at >= datetime('now', '-{} days') AND price > 0
    """.format(days))
    
    result = c.fetchone()
    if not result or not result[0] or not result[1]:
        conn.close()
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
    
    conn.close()
    return price_ranges

def update_keyword_trends():
    """Update keyword trends from recent listings"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Get recent listings and extract keywords
    c.execute("""
        SELECT id, title, price, source, created_at
        FROM listings 
        WHERE created_at >= datetime('now', '-1 day')
    """)
    
    listings = c.fetchall()
    
    # Simple keyword extraction (can be enhanced)
    keywords = {}
    for listing in listings:
        listing_id, title, price, source, created_at = listing
        title_lower = title.lower()
        
        # Extract common car-related keywords
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
    conn.close()

def get_market_insights(days=30):
    """Get comprehensive market insights"""
    conn = sqlite3.connect(DB_FILE)
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
    
    conn.close()
    
    return {
        'overall_stats': overall_stats,
        'top_keywords': top_keywords,
        'source_performance': source_performance
    }
