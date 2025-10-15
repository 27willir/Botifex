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

# Cache failed geocoding attempts to avoid hammering the service on repeated failures
_geocode_fail_cache = {}  # {location_key: last_failure_epoch_seconds}
_geocode_fail_ttl_seconds = 600  # 10 minutes

# Minimal fallback coordinates for common cities when geocoding is unavailable
_fallback_coords = {
    "boise": (43.6150, -116.2023),
    "salt lake city": (40.7608, -111.8910),
    "portland": (45.5152, -122.6784),
    "seattle": (47.6062, -122.3321),
    "phoenix": (33.4484, -112.0740),
    "los angeles": (34.0522, -118.2437),
    "las vegas": (36.1699, -115.1398),
    "denver": (39.7392, -104.9903),
    "san francisco": (37.7749, -122.4194),
    "sacramento": (38.5816, -121.4944),
}

# ======================
# GEOCODING FUNCTIONS
# ======================
def geocode_location(location_name):
    """
    Convert a city name to coordinates using geocoding.
    Returns (latitude, longitude) or None if geocoding fails.
    Uses caching to avoid repeated API calls.
    """
    location_key = location_name.lower().strip()
    
    # Check cache first
    with _geocode_lock:
        if location_key in geocode_cache:
            return geocode_cache[location_key]
        # If we recently failed for this location, avoid retrying immediately
        last_fail_ts = _geocode_fail_cache.get(location_key)
        if last_fail_ts is not None and (time.time() - last_fail_ts) < _geocode_fail_ttl_seconds:
            # Use fallback coords if available
            if location_key in _fallback_coords:
                return _fallback_coords[location_key]
            return None
    
    try:
        # Try to geocode the location
        location = geolocator.geocode(location_name, timeout=10)
        if location:
            coords = (location.latitude, location.longitude)
            # Cache the result
            with _geocode_lock:
                geocode_cache[location_key] = coords
                _geocode_fail_cache.pop(location_key, None)
            logger.debug(f"Geocoded '{location_name}' to {coords}")
            return coords
        else:
            logger.warning(f"Could not geocode location: {location_name}")
            # Remember failure and attempt fallback
            with _geocode_lock:
                _geocode_fail_cache[location_key] = time.time()
            if location_key in _fallback_coords:
                return _fallback_coords[location_key]
            return None
    except (GeocoderTimedOut, GeocoderServiceError, RecursionError) as e:
        # Treat recursion from underlying library as a service error
        logger.warning(f"Geocoding service error for '{location_name}': {e}")
        with _geocode_lock:
            _geocode_fail_cache[location_key] = time.time()
        if location_key in _fallback_coords:
            return _fallback_coords[location_key]
        return None
    except Exception as e:
        logger.error(f"Unexpected error geocoding '{location_name}': {e}")
        with _geocode_lock:
            _geocode_fail_cache[location_key] = time.time()
        if location_key in _fallback_coords:
            return _fallback_coords[location_key]
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
        logger.error(f"Error calculating distance: {e}")
        return None

def get_location_coords(location_name):
    """
    Get coordinates for a location name (with caching).
    Returns (latitude, longitude) or None if not found.
    """
    return geocode_location(location_name)

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

