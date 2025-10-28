"""
Shared location and distance utilities for all scrapers.
Provides geocoding and distance calculation functionality.
"""
import threading
import time
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
from geopy.distance import geodesic
from utils import logger

# ======================
# GEOCODING SETUP
# ======================
geolocator = Nominatim(user_agent="super-bot-marketplace-scraper")
geocode_cache = {}  # Cache for geocoded locations
_geocode_lock = threading.Lock()  # Thread safety for geocoding
_geocode_retry_count = {}  # Track retry attempts per location
_max_retries = 3  # Maximum retry attempts

# ======================
# GEOCODING FUNCTIONS
# ======================
def geocode_location(location_name):
    """
    Convert a city name to coordinates using geocoding.
    Returns (latitude, longitude) or None if geocoding fails.
    Uses caching to avoid repeated API calls and retry limits to prevent recursion.
    """
    location_key = location_name.lower().strip()
    
    # Check cache first
    with _geocode_lock:
        if location_key in geocode_cache:
            return geocode_cache[location_key]
        
        # Check if we've exceeded retry limit for this location
        if location_key in _geocode_retry_count and _geocode_retry_count[location_key] >= _max_retries:
            # Use print instead of logger to avoid recursion
            import sys
            print(f"Geocoding retry limit exceeded for '{location_name}', using default coordinates", file=sys.stderr, flush=True)
            # Use default coordinates for Boise, ID as fallback
            default_coords = (43.6150, -116.2023)
            geocode_cache[location_key] = default_coords
            return default_coords
    
    try:
        # Try to geocode the location
        location = geolocator.geocode(location_name, timeout=10)
        if location:
            coords = (location.latitude, location.longitude)
            # Cache the result and reset retry count
            with _geocode_lock:
                geocode_cache[location_key] = coords
                _geocode_retry_count[location_key] = 0  # Reset retry count on success
            # Avoid logger to prevent recursion
            return coords
        else:
            # Increment retry count
            with _geocode_lock:
                _geocode_retry_count[location_key] = _geocode_retry_count.get(location_key, 0) + 1
            return None
    except RecursionError as e:
        # Handle recursion errors specially - don't try to log them
        import sys
        print(f"RECURSION ERROR in geocoding '{location_name}': {e}", file=sys.stderr, flush=True)
        with _geocode_lock:
            _geocode_retry_count[location_key] = _max_retries  # Max out retries to prevent further attempts
        return None
    except (GeocoderTimedOut, GeocoderServiceError) as e:
        # Use print instead of logger to avoid recursion
        import sys
        print(f"Geocoding service error for '{location_name}': {e}", file=sys.stderr, flush=True)
        # Increment retry count
        with _geocode_lock:
            _geocode_retry_count[location_key] = _geocode_retry_count.get(location_key, 0) + 1
        return None
    except Exception as e:
        # Use print instead of logger to avoid recursion
        import sys
        print(f"Unexpected error geocoding '{location_name}': {e}", file=sys.stderr, flush=True)
        # Increment retry count
        with _geocode_lock:
            _geocode_retry_count[location_key] = _geocode_retry_count.get(location_key, 0) + 1
        return None

def calculate_distance(coord1, coord2):
    """
    Calculate distance between two coordinates in miles.
    Args:
        coord1: (latitude, longitude) tuple
        coord2: (latitude, longitude) tuple
    Returns:
        Distance in miles (float)
    """
    try:
        distance_km = geodesic(coord1, coord2).kilometers
        distance_miles = distance_km * 0.621371  # Convert km to miles
        return distance_miles
    except Exception as e:
        # Use print instead of logger to avoid recursion
        import sys
        print(f"Error calculating distance: {e}", file=sys.stderr, flush=True)
        return None

def get_location_coords(location_name):
    """
    Get coordinates for a location name (with caching).
    Returns (latitude, longitude) or None if not found.
    """
    if not location_name or not isinstance(location_name, str):
        # Use print instead of logger to avoid recursion
        import sys
        print(f"Invalid location name provided to get_location_coords", file=sys.stderr, flush=True)
        return None
    
    try:
        return geocode_location(location_name)
    except Exception as e:
        # Use print instead of logger to avoid recursion
        import sys
        print(f"Error in get_location_coords for '{location_name}': {e}", file=sys.stderr, flush=True)
        return None

def is_within_radius(coord1, coord2, radius_miles):
    """
    Check if two coordinates are within a specified radius.
    Args:
        coord1: (latitude, longitude) tuple for location 1
        coord2: (latitude, longitude) tuple for location 2
        radius_miles: Maximum distance in miles
    Returns:
        True if within radius, False otherwise
    """
    distance = calculate_distance(coord1, coord2)
    if distance is None:
        return False
    return distance <= radius_miles

def miles_to_km(miles):
    """Convert miles to kilometers."""
    return miles * 1.60934

def km_to_miles(km):
    """Convert kilometers to miles."""
    return km * 0.621371

def reset_geocode_retry_count(location_name=None):
    """
    Reset retry count for a specific location or all locations.
    Useful for recovery after fixing geocoding issues.
    """
    import sys
    with _geocode_lock:
        if location_name:
            location_key = location_name.lower().strip()
            if location_key in _geocode_retry_count:
                _geocode_retry_count[location_key] = 0
                print(f"Reset retry count for '{location_name}'", file=sys.stderr, flush=True)
        else:
            _geocode_retry_count.clear()
            print("Reset retry counts for all locations", file=sys.stderr, flush=True)

def get_geocode_status():
    """
    Get current geocoding status including retry counts and cache size.
    Useful for debugging geocoding issues.
    """
    with _geocode_lock:
        return {
            "cache_size": len(geocode_cache),
            "retry_counts": dict(_geocode_retry_count),
            "max_retries": _max_retries
        }

