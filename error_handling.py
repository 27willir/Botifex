# error_handling.py
"""
Centralized error handling utilities for the super-bot application.
Provides consistent error handling, logging, and recovery mechanisms.
"""

import json
import logging
import traceback
import time
import threading
from functools import wraps
from typing import Any, Callable, Optional, Type, Union
from pathlib import Path

# Import the logger from utils
from utils import logger

# Thread-local storage for recursion protection
_error_handling_lock = threading.local()

class ErrorHandler:
    """Centralized error handling class with retry and recovery mechanisms."""
    
    @staticmethod
    def handle_database_error(func: Callable, *args, **kwargs) -> Any:
        """Handle database-related errors with retry logic and recursion protection."""
        import sqlite3
        import random
        import sys
        
        max_retries = 5
        base_delay = 0.1
        
        # Check for recursion depth to prevent infinite loops
        recursion_marker = getattr(_error_handling_lock, 'db_error_depth', 0)
        if recursion_marker > 10:
            print(f"ERROR: Maximum recursion depth exceeded in database error handler", file=sys.stderr)
            raise RecursionError("Maximum database error handler recursion depth exceeded")
        
        _error_handling_lock.db_error_depth = recursion_marker + 1
        
        try:
            for attempt in range(max_retries):
                try:
                    result = func(*args, **kwargs)
                    _error_handling_lock.db_error_depth = recursion_marker
                    return result
                except sqlite3.OperationalError as e:
                    error_msg = str(e).lower()
                    if "database is locked" in error_msg or "database table is locked" in error_msg:
                        if attempt < max_retries - 1:
                            # Exponential backoff with jitter for locking errors
                            delay = base_delay * (2 ** attempt) + random.uniform(0, 0.2)
                            try:
                                logger.warning(f"Database locked, retrying in {delay:.2f}s (attempt {attempt + 1}/{max_retries})")
                            except:
                                print(f"Database locked, retrying in {delay:.2f}s (attempt {attempt + 1}/{max_retries})", file=sys.stderr)
                            time.sleep(delay)
                            continue
                        else:
                            try:
                                logger.error(f"Database locked after {max_retries} attempts")
                            except:
                                print(f"Database locked after {max_retries} attempts", file=sys.stderr)
                            raise
                    elif "database is busy" in error_msg:
                        if attempt < max_retries - 1:
                            # Shorter delay for busy database
                            delay = base_delay * (1.5 ** attempt) + random.uniform(0, 0.1)
                            try:
                                logger.warning(f"Database busy, retrying in {delay:.2f}s (attempt {attempt + 1}/{max_retries})")
                            except:
                                print(f"Database busy, retrying in {delay:.2f}s (attempt {attempt + 1}/{max_retries})", file=sys.stderr)
                            time.sleep(delay)
                            continue
                        else:
                            try:
                                logger.error(f"Database busy after {max_retries} attempts")
                            except:
                                print(f"Database busy after {max_retries} attempts", file=sys.stderr)
                            raise
                    else:
                        try:
                            logger.error(f"Database error: {e}")
                        except:
                            print(f"Database error: {e}", file=sys.stderr)
                        raise
                except sqlite3.DatabaseError as e:
                    try:
                        logger.error(f"Database integrity error: {e}")
                    except:
                        print(f"Database integrity error: {e}", file=sys.stderr)
                    raise
                except Exception as e:
                    try:
                        logger.error(f"Database operation failed (attempt {attempt + 1}/{max_retries}): {e}")
                    except:
                        print(f"Database operation failed (attempt {attempt + 1}/{max_retries}): {e}", file=sys.stderr)
                    if attempt < max_retries - 1:
                        time.sleep(base_delay * (attempt + 1))
                    else:
                        # Try to perform database maintenance on final failure (avoid recursion)
                        if recursion_marker == 0:
                            try:
                                from db_enhanced import maintain_database, cleanup_old_connections
                                cleanup_old_connections()
                                maintain_database()
                                try:
                                    logger.info("Performed database maintenance after operation failure")
                                except:
                                    print("Performed database maintenance after operation failure", file=sys.stderr)
                            except Exception as maintenance_error:
                                print(f"Database maintenance failed: {maintenance_error}", file=sys.stderr)
                        raise
        finally:
            _error_handling_lock.db_error_depth = recursion_marker
    
    @staticmethod
    def handle_network_error(func: Callable, *args, **kwargs) -> Any:
        """Handle network-related errors with retry logic and recursion protection."""
        import sys
        max_retries = 3
        retry_delay = 2
        
        # Check for recursion depth
        recursion_marker = getattr(_error_handling_lock, 'network_error_depth', 0)
        if recursion_marker > 5:
            print(f"ERROR: Maximum recursion depth exceeded in network error handler", file=sys.stderr)
            raise RecursionError("Maximum network error handler recursion depth exceeded")
        
        _error_handling_lock.network_error_depth = recursion_marker + 1
        
        try:
            for attempt in range(max_retries):
                try:
                    result = func(*args, **kwargs)
                    _error_handling_lock.network_error_depth = recursion_marker
                    return result
                except (ConnectionError, TimeoutError, OSError) as e:
                    try:
                        logger.warning(f"Network operation failed (attempt {attempt + 1}/{max_retries}): {e}")
                    except:
                        print(f"Network operation failed (attempt {attempt + 1}/{max_retries}): {e}", file=sys.stderr)
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay * (attempt + 1))
                    else:
                        try:
                            logger.error(f"Network operation failed after {max_retries} attempts: {e}")
                        except:
                            print(f"Network operation failed after {max_retries} attempts: {e}", file=sys.stderr)
                        raise
                except Exception as e:
                    try:
                        logger.error(f"Unexpected error in network operation: {e}")
                    except:
                        print(f"Unexpected error in network operation: {e}", file=sys.stderr)
                    raise
        finally:
            _error_handling_lock.network_error_depth = recursion_marker
    
    @staticmethod
    def handle_scraper_error(func: Callable, *args, **kwargs) -> Any:
        """Handle scraper-specific errors with recovery and recursion protection."""
        import sys
        try:
            return func(*args, **kwargs)
        except RecursionError as e:
            # Handle recursion errors specially - don't try to log them
            print(f"RECURSION ERROR in scraper: {e}", file=sys.stderr)
            return []
        except Exception as e:
            try:
                logger.error(f"Scraper operation failed: {e}")
                logger.debug(f"Scraper error traceback: {traceback.format_exc()}")
            except:
                print(f"Scraper operation failed: {e}", file=sys.stderr)
            # Return empty result instead of crashing
            return []
    
    @staticmethod
    def handle_file_operation(func: Callable, *args, **kwargs) -> Any:
        """Handle file operation errors with proper logging."""
        try:
            return func(*args, **kwargs)
        except FileNotFoundError as e:
            logger.warning(f"File not found: {e}")
            return None
        except PermissionError as e:
            logger.error(f"Permission denied for file operation: {e}")
            raise
        except OSError as e:
            logger.error(f"File system error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected file operation error: {e}")
            raise

def retry_on_failure(max_retries: int = 3, delay: float = 1.0, 
                    exceptions: tuple = (Exception,)):
    """Decorator to retry function on failure."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if attempt < max_retries - 1:
                        logger.warning(f"Attempt {attempt + 1} failed for {func.__name__}: {e}")
                        time.sleep(delay * (attempt + 1))
                    else:
                        logger.error(f"All {max_retries} attempts failed for {func.__name__}: {e}")
                        raise
            return None
        return wrapper
    return decorator

def log_errors(logger_instance: Optional[logging.Logger] = None):
    """Decorator to log errors with context and recursion protection.
    
    WARNING: Do NOT use this decorator on functions that already use logger internally.
    This is meant for simple functions that need error logging but don't log themselves.
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except RecursionError as e:
                # Handle recursion errors without logging (would make it worse)
                import sys
                print(f"RECURSION ERROR in {func.__name__}: {e}", file=sys.stderr, flush=True)
                raise
            except Exception as e:
                # Prevent infinite recursion if logging itself fails
                if getattr(_error_handling_lock, 'in_error_handler', False):
                    # Already handling an error, print to stderr and don't try to log
                    import sys
                    print(f"NESTED ERROR in {func.__name__}: {e}", file=sys.stderr, flush=True)
                    raise
                
                _error_handling_lock.in_error_handler = True
                try:
                    log = logger_instance or logger
                    # Only log the error message, skip debug traceback to reduce complexity
                    log.error(f"Error in {func.__name__}: {e}")
                except Exception as log_error:
                    # If logging fails, print to stderr and continue
                    import sys
                    print(f"LOGGING ERROR in {func.__name__}: {e}", file=sys.stderr, flush=True)
                    print(f"Logger exception: {log_error}", file=sys.stderr, flush=True)
                finally:
                    _error_handling_lock.in_error_handler = False
                raise
        return wrapper
    return decorator

def safe_execute(func: Callable, default_return: Any = None, 
                should_log_errors: bool = True) -> Any:
    """Safely execute a function with error handling."""
    try:
        return func()
    except Exception as e:
        if should_log_errors:
            logger.error(f"Safe execution failed for {func.__name__}: {e}")
        return default_return

class ScraperError(Exception):
    """Custom exception for scraper-specific errors."""
    pass

class DatabaseError(Exception):
    """Custom exception for database-related errors."""
    pass

class NetworkError(Exception):
    """Custom exception for network-related errors."""
    pass

def validate_input(value: Any, expected_type: Type, field_name: str) -> Any:
    """Validate input with proper error handling."""
    if not isinstance(value, expected_type):
        raise ValueError(f"Invalid {field_name}: expected {expected_type.__name__}, got {type(value).__name__}")
    return value

def safe_json_operation(operation: str, path: Union[str, Path], data: Any = None) -> Any:
    """Safely perform JSON operations with error handling."""
    path = Path(path)
    
    try:
        if operation == "read":
            if not path.exists():
                logger.warning(f"JSON file not found: {path}")
                return {}
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        elif operation == "write":
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error for {path}: {e}")
        return {} if operation == "read" else False
    except Exception as e:
        logger.error(f"JSON operation failed for {path}: {e}")
        return {} if operation == "read" else False
