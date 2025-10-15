"""
Shared location and distance utilities for all scrapers.
Provides geocoding and distance calculation functionality.
"""
import threading
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
    
    # Add predefined coordinates for common locations to avoid geocoding
    predefined_coords = {
        'boise': (43.6150, -116.2023),
        'boise, id': (43.6150, -116.2023),
        'salt lake city': (40.7608, -111.8910),
        'salt lake city, ut': (40.7608, -111.8910),
        'portland': (45.5152, -122.6784),
        'portland, or': (45.5152, -122.6784),
        'seattle': (47.6062, -122.3321),
        'seattle, wa': (47.6062, -122.3321),
        'san francisco': (37.7749, -122.4194),
        'san francisco, ca': (37.7749, -122.4194),
        'los angeles': (34.0522, -118.2437),
        'los angeles, ca': (34.0522, -118.2437),
        'denver': (39.7392, -104.9903),
        'denver, co': (39.7392, -104.9903),
        'phoenix': (33.4484, -112.0740),
        'phoenix, az': (33.4484, -112.0740),
        'las vegas': (36.1699, -115.1398),
        'las vegas, nv': (36.1699, -115.1398)
    }
    
    # Check if we have predefined coordinates
    if location_key in predefined_coords:
        coords = predefined_coords[location_key]
        with _geocode_lock:
            geocode_cache[location_key] = coords
        logger.debug(f"Using predefined coordinates for '{location_name}': {coords}")
        return coords
    
    try:
        # Try to geocode the location with a shorter timeout
        # Set recursion limit temporarily
        import sys
        old_limit = sys.getrecursionlimit()
        sys.setrecursionlimit(100)
        
        try:
            location = geolocator.geocode(location_name, timeout=5)
            if location:
                coords = (location.latitude, location.longitude)
                # Cache the result
                with _geocode_lock:
                    geocode_cache[location_key] = coords
                logger.debug(f"Geocoded '{location_name}' to {coords}")
                return coords
            else:
                logger.warning(f"Could not geocode location: {location_name}")
                return None
        finally:
            sys.setrecursionlimit(old_limit)
            
    except RecursionError as e:
        logger.error(f"Recursion error in geocoding for '{location_name}': {e}")
        return None
    except (GeocoderTimedOut, GeocoderServiceError) as e:
        logger.warning(f"Geocoding service error for '{location_name}': {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error geocoding '{location_name}': {e}")
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

