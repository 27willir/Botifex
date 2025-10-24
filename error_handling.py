# error_handling.py
"""
Centralized error handling utilities for the super-bot application.
Provides consistent error handling, logging, and recovery mechanisms.
"""

import json
import logging
import traceback
import time
from functools import wraps
from typing import Any, Callable, Optional, Type, Union
from pathlib import Path

# Import the logger from utils
from utils import logger

class ErrorHandler:
    """Centralized error handling class with retry and recovery mechanisms."""
    
    @staticmethod
    def handle_database_error(func: Callable, *args, **kwargs) -> Any:
        """Handle database-related errors with retry logic."""
        import sqlite3
        import random
        
        max_retries = 5
        base_delay = 0.1
        
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except sqlite3.OperationalError as e:
                error_msg = str(e).lower()
                if "database is locked" in error_msg or "database table is locked" in error_msg:
                    if attempt < max_retries - 1:
                        # Exponential backoff with jitter for locking errors
                        delay = base_delay * (2 ** attempt) + random.uniform(0, 0.2)
                        logger.warning(f"Database locked, retrying in {delay:.2f}s (attempt {attempt + 1}/{max_retries})")
                        time.sleep(delay)
                        continue
                    else:
                        logger.error(f"Database locked after {max_retries} attempts")
                        raise
                elif "database is busy" in error_msg:
                    if attempt < max_retries - 1:
                        # Shorter delay for busy database
                        delay = base_delay * (1.5 ** attempt) + random.uniform(0, 0.1)
                        logger.warning(f"Database busy, retrying in {delay:.2f}s (attempt {attempt + 1}/{max_retries})")
                        time.sleep(delay)
                        continue
                    else:
                        logger.error(f"Database busy after {max_retries} attempts")
                        raise
                else:
                    logger.error(f"Database error: {e}")
                    raise
            except sqlite3.DatabaseError as e:
                logger.error(f"Database integrity error: {e}")
                raise
            except Exception as e:
                logger.error(f"Database operation failed (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(base_delay * (attempt + 1))
                else:
                    logger.error(f"Database operation failed after {max_retries} attempts: {e}")
                    # Try to perform database maintenance on final failure
                    try:
                        from db_enhanced import maintain_database, cleanup_old_connections
                        cleanup_old_connections()
                        maintain_database()
                        logger.info("Performed database maintenance after operation failure")
                    except Exception as maintenance_error:
                        logger.error(f"Database maintenance failed: {maintenance_error}")
                    raise
    
    @staticmethod
    def handle_network_error(func: Callable, *args, **kwargs) -> Any:
        """Handle network-related errors with retry logic."""
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except (ConnectionError, TimeoutError, OSError) as e:
                logger.warning(f"Network operation failed (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay * (attempt + 1))
                else:
                    logger.error(f"Network operation failed after {max_retries} attempts: {e}")
                    raise
            except Exception as e:
                logger.error(f"Unexpected error in network operation: {e}")
                raise
    
    @staticmethod
    def handle_scraper_error(func: Callable, *args, **kwargs) -> Any:
        """Handle scraper-specific errors with recovery."""
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Scraper operation failed: {e}")
            logger.debug(f"Scraper error traceback: {traceback.format_exc()}")
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
    """Decorator to log errors with context."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                log = logger_instance or logger
                log.error(f"Error in {func.__name__}: {e}")
                log.debug(f"Error traceback: {traceback.format_exc()}")
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
