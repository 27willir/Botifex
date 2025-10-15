# Facebook Marketplace Dynamic Radius Feature

## Overview
The Facebook Marketplace scraper now supports **ANY city worldwide** using geocoding to convert city names to coordinates. Users can enter any location name and their desired search radius.

## Features

### 🌍 Universal Location Support
- **Works with ANY city** - no need to be in a predefined list
- Uses OpenStreetMap's geocoding service (Nominatim) to convert city names to coordinates
- Supports international cities (e.g., "London", "Tokyo", "Sydney", "Paris")
- Automatic caching to improve performance and reduce API calls

### 📍 Dynamic Radius Configuration
- Users set radius in **miles** (e.g., 10, 25, 50, 100, 200)
- Automatically converts to kilometers for Facebook's API
- No hardcoded limits - use any radius you need

### 🔄 Smart Fallback System
- Primary: Geocoding (works for any location)
- Fallback: Location IDs (for common cities if geocoding fails)
- Default: Boise with 50-mile radius

## How It Works

### 1. User Sets Location
Users enter any city name in their settings:
- "New York"
- "Miami, FL"
- "Austin, Texas"
- "Vancouver, BC"
- "London, UK"
- "Melbourne, Australia"

### 2. Geocoding Process
1. System checks geocoding cache for the location
2. If not cached, uses Nominatim to get coordinates
3. Caches the result for future use
4. Logs the coordinates for transparency

### 3. URL Building
The system builds a Facebook Marketplace URL with:
- Latitude/longitude from geocoding
- Search radius in kilometers
- User's search keywords
- Price filters

### Example Flow
```
User Input: "Austin, Texas" + 40 miles radius
    ↓
Geocoding: (30.2672, -97.7431)
    ↓
Facebook URL: ...latitude=30.2672&longitude=-97.7431&radius=64...
```

## Usage

### Basic Configuration
```json
{
  "location": "Nashville",
  "radius": 60
}
```

### With State/Country
```json
{
  "location": "Portland, Oregon",
  "radius": 25
}
```

### International
```json
{
  "location": "Toronto, Canada",
  "radius": 30
}
```

## Technical Details

### Dependencies
- **geopy**: Python geocoding library
- **Nominatim**: Free OpenStreetMap geocoding service
- Thread-safe caching for performance

### Geocoding Cache
- Stores location → coordinates mapping
- Thread-safe with locking mechanism
- Persists during scraper runtime
- Reduces API calls and improves speed

### URL Structure (Coordinates-based)
```
https://www.facebook.com/marketplace/category/vehicles?
  query={keywords}&
  latitude={lat}&
  longitude={lon}&
  radius={km}
```

### URL Structure (Fallback)
```
https://www.facebook.com/marketplace/{location_id}/?
  query={keywords}&
  radius={km}
```

### Error Handling
- Geocoding timeout → uses fallback
- Service unavailable → uses fallback
- Invalid location → uses default (Boise)
- All errors logged for debugging

## Advantages

### ✅ Before This Update
- Limited to 10 hardcoded cities
- Users had to match exact city names
- No international support
- Required code changes to add cities

### ✅ After This Update
- **Unlimited cities** worldwide
- Natural language location input
- International support
- No code changes needed

## Performance

### Caching Strategy
- First lookup: ~1-2 seconds (geocoding API call)
- Subsequent lookups: Instant (cached)
- Cache is thread-safe for concurrent scrapers

### Rate Limiting
- Nominatim has a 1 request/second limit
- Our caching prevents hitting this limit
- Each location is only geocoded once per runtime

## Examples

### US Cities
```
"Seattle"
"Los Angeles" 
"Chicago"
"Boston, MA"
"San Diego, California"
```

### International
```
"London, England"
"Vancouver, British Columbia"
"Sydney, Australia"
"Tokyo, Japan"
"Berlin, Germany"
```

### Specific Areas
```
"Brooklyn, New York"
"Orange County, California"
"North Dallas, Texas"
```

## Logging

The scraper provides detailed logging:
```
Geocoded 'Austin, Texas' to (30.2672, -97.7431)
Facebook Marketplace: searching Austin, Texas within 40 miles
```

## Troubleshooting

### Location Not Found
If geocoding fails, the system:
1. Logs a warning
2. Checks fallback location IDs
3. Uses Boise as ultimate default

### Slow Geocoding
- First lookup may take 1-2 seconds
- Subsequent lookups are instant (cached)
- Consider pre-warming cache for common locations

## Future Enhancements

Potential improvements:
- Persistent cache (save to disk)
- Custom geocoding providers
- Location validation in UI
- Coordinate input option

