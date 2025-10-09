# cache_manager.py - Simple in-memory caching for improved performance
from datetime import datetime, timedelta
from threading import Lock
from utils import logger


class CacheManager:
    """Thread-safe in-memory cache manager"""
    
    def __init__(self):
        self.cache = {}
        self.lock = Lock()
        self.default_ttl = 300  # 5 minutes default TTL
    
    def get(self, key):
        """Get value from cache if it exists and hasn't expired"""
        with self.lock:
            if key in self.cache:
                value, expiry = self.cache[key]
                if datetime.now() < expiry:
                    logger.debug(f"Cache hit for key: {key}")
                    return value
                else:
                    # Expired, remove it
                    del self.cache[key]
                    logger.debug(f"Cache expired for key: {key}")
            return None
    
    def set(self, key, value, ttl=None):
        """Set value in cache with TTL (time to live in seconds)"""
        ttl = ttl if ttl is not None else self.default_ttl
        expiry = datetime.now() + timedelta(seconds=ttl)
        
        with self.lock:
            self.cache[key] = (value, expiry)
            logger.debug(f"Cache set for key: {key} (TTL: {ttl}s)")
    
    def delete(self, key):
        """Delete a specific key from cache"""
        with self.lock:
            if key in self.cache:
                del self.cache[key]
                logger.debug(f"Cache deleted for key: {key}")
    
    def clear(self):
        """Clear all cache"""
        with self.lock:
            self.cache.clear()
            logger.info("Cache cleared")
    
    def clear_pattern(self, pattern):
        """Clear all keys matching a pattern"""
        with self.lock:
            keys_to_delete = [k for k in self.cache.keys() if pattern in k]
            for key in keys_to_delete:
                del self.cache[key]
            logger.debug(f"Cleared {len(keys_to_delete)} cache keys matching pattern: {pattern}")
    
    def get_stats(self):
        """Get cache statistics"""
        with self.lock:
            total_keys = len(self.cache)
            expired_keys = 0
            now = datetime.now()
            
            for key, (value, expiry) in self.cache.items():
                if expiry < now:
                    expired_keys += 1
            
            return {
                'total_keys': total_keys,
                'expired_keys': expired_keys,
                'active_keys': total_keys - expired_keys
            }
    
    def cleanup_expired(self):
        """Remove all expired entries from cache"""
        with self.lock:
            now = datetime.now()
            expired_keys = [k for k, (v, exp) in self.cache.items() if exp < now]
            
            for key in expired_keys:
                del self.cache[key]
            
            if expired_keys:
                logger.info(f"Cleaned up {len(expired_keys)} expired cache entries")
            
            return len(expired_keys)


# Global cache instance
_cache = CacheManager()


def get_cache():
    """Get the global cache instance"""
    return _cache


# Convenience functions

def cache_get(key):
    """Get value from cache"""
    return get_cache().get(key)


def cache_set(key, value, ttl=None):
    """Set value in cache"""
    return get_cache().set(key, value, ttl)


def cache_delete(key):
    """Delete value from cache"""
    return get_cache().delete(key)


def cache_clear():
    """Clear all cache"""
    return get_cache().clear()


def cache_user_data(username):
    """Clear all cached data for a specific user"""
    get_cache().clear_pattern(f"user:{username}")


# Decorator for caching function results

from functools import wraps


def cached(key_prefix, ttl=300):
    """
    Decorator to cache function results
    
    Usage:
        @cached('listings', ttl=60)
        def get_listings(user_id):
            return expensive_database_call(user_id)
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Build cache key from function name and arguments
            cache_key = f"{key_prefix}:{f.__name__}:{str(args)}:{str(kwargs)}"
            
            # Try to get from cache
            result = cache_get(cache_key)
            if result is not None:
                return result
            
            # Call function and cache result
            result = f(*args, **kwargs)
            cache_set(cache_key, result, ttl)
            
            return result
        
        return decorated_function
    return decorator
