# Direct Selling Feature Documentation

## Overview

The Direct Selling feature allows users to create and manage listings to sell items on supported marketplaces (Craigslist, Facebook Marketplace, and KSL Classifieds) all from one centralized interface.

## Features Implemented

### 1. **Database Structure**
- Added `seller_listings` table to store user-created listings
- Tracks listing details, marketplace selections, posting status, and URLs
- Supports draft and posted statuses
- User-specific listings with proper foreign key relationships

### 2. **Selling Page** (`/selling`)
A dedicated, modern UI page similar to the analytics page featuring:

#### Statistics Dashboard
- **Total Listings**: Shows total number of listings created
- **Drafts**: Number of listings in draft status
- **Posted**: Number of successfully posted listings
- **Average Price**: Average price across all user listings

#### Create Listing Form
Fields available:
- **Title** (required): Item title
- **Price** (required): Item price in dollars
- **Category**: Select from predefined categories (vehicles, electronics, furniture, etc.)
- **Location**: City and state information
- **Description**: Detailed item description
- **Marketplaces** (required): Checkbox selection for Craigslist, Facebook, and/or KSL

#### Your Listings Section
- Displays all user-created listings
- Shows listing details, selected marketplaces, and status
- Action buttons:
  - **Post**: Prepare listing for posting (for draft listings)
  - **Edit**: Modify listing details (coming soon)
  - **Delete**: Remove listing from database

### 3. **API Endpoints**

All endpoints require authentication and follow REST conventions:

#### `GET /api/seller-listings`
Get all listings for the current user
- Query params: `status` (optional) - filter by 'draft' or 'posted'
- Returns: `{ listings: [...] }`

#### `GET /api/seller-listings/<id>`
Get a specific listing by ID
- Returns: `{ listing: {...} }`
- Error: 404 if not found, 403 if not owned by user

#### `POST /api/seller-listings`
Create a new listing
- Body: JSON with listing details
- Returns: `{ message: "...", listing_id: <id> }`

#### `PUT /api/seller-listings/<id>`
Update an existing listing
- Body: JSON with fields to update
- Returns: `{ message: "..." }`

#### `DELETE /api/seller-listings/<id>`
Delete a listing
- Returns: `{ message: "..." }`

#### `POST /api/seller-listings/<id>/post`
Post a listing to selected marketplaces
- Returns: Information about posting status
- Note: Currently returns a message about manual posting (see Future Enhancements)

#### `GET /api/seller-listings/stats`
Get user's listing statistics
- Returns: `{ stats: { total_listings, draft_count, posted_count, avg_price } }`

### 4. **Security Features**
- All inputs are sanitized using `SecurityConfig.sanitize_input()`
- Price validation ensures non-negative integers
- User authorization checks ensure users can only access their own listings
- CSRF protection on all POST/PUT/DELETE endpoints
- Rate limiting on all API endpoints

### 5. **Database Functions**

New functions added to `db_enhanced.py`:
- `create_seller_listing()`: Create a new listing
- `get_seller_listings()`: Retrieve listings with filtering
- `get_seller_listing_by_id()`: Get a specific listing
- `update_seller_listing()`: Update listing fields
- `delete_seller_listing()`: Delete a listing
- `update_seller_listing_urls()`: Update marketplace URLs after posting
- `get_seller_listing_stats()`: Get user statistics

### 6. **Navigation**
Added "Sell Items" link in the main dashboard sidebar with dollar sign icon

## How to Use

1. **Access the Selling Page**
   - Log in to your Super Bot account
   - Click "Sell Items" in the left sidebar
   - Or navigate to `/selling`

2. **Create a New Listing**
   - Fill in the item title (required)
   - Enter the price (required)
   - Select a category (optional but recommended)
   - Add location information (optional)
   - Write a detailed description (optional)
   - Select at least one marketplace (required)
   - Click "Create Listing"

3. **Manage Your Listings**
   - View all your listings in the "Your Listings" section
   - Click "Post" to prepare a draft listing for posting
   - Click "Delete" to remove a listing
   - Each listing shows its status (draft/posted) and selected marketplaces

4. **View Your Statistics**
   - Statistics cards at the top show your listing activity
   - Track total listings, drafts, posted items, and average price

## Database Schema

```sql
CREATE TABLE seller_listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    price INTEGER NOT NULL,
    category TEXT,
    location TEXT,
    images TEXT,
    marketplaces TEXT,
    status TEXT DEFAULT 'draft',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    posted_at DATETIME,
    craigslist_url TEXT,
    facebook_url TEXT,
    ksl_url TEXT,
    FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
)
```

## Future Enhancements

### Planned Features
1. **Direct API Integration**
   - Automated posting to Craigslist (via unofficial API or automation)
   - Facebook Marketplace API integration
   - KSL Classifieds API integration

2. **Image Upload**
   - Support for uploading multiple images per listing
   - Image storage and management
   - Image preview in listing cards

3. **Edit Functionality**
   - Modal dialog for editing existing listings
   - Update all fields without deleting and recreating

4. **Listing Templates**
   - Save commonly used listing formats
   - Quick fill for similar items

5. **Posting History**
   - Track when listings were posted
   - View posting success/failure logs
   - Repost expired listings

6. **Marketplace-Specific Fields**
   - Custom fields per marketplace (e.g., vehicle VIN for automotive categories)
   - Marketplace-specific categories and requirements

7. **Scheduled Posting**
   - Schedule listings to post at specific times
   - Automatic reposting at intervals

8. **Analytics**
   - Track views and engagement per listing
   - Compare performance across marketplaces
   - Pricing recommendations based on market data

## Technical Notes

### Status Values
- `draft`: Listing created but not yet posted
- `posted`: Listing has been posted to one or more marketplaces

### Marketplace Values
Stored as comma-separated string:
- `craigslist`
- `facebook`
- `ksl`

### Category Options
- vehicles
- electronics
- furniture
- clothing
- sports
- home
- toys
- books
- other

## Troubleshooting

### Listing Creation Fails
- Ensure all required fields (title, price, marketplaces) are filled
- Check that price is a valid positive number
- Verify at least one marketplace is selected

### Cannot See Listings
- Listings are user-specific - you can only see your own
- Check browser console for JavaScript errors
- Refresh the page to reload listings

### Posting Doesn't Work
- Currently, direct posting requires additional API setup
- Use the listing information to manually post to each marketplace
- Future updates will add automated posting

## Development Notes

### Files Modified
- `db_enhanced.py`: Added seller_listings table and database functions
- `db.py`: Exported new seller listing functions
- `app.py`: Added /selling route and API endpoints
- `templates/selling.html`: Created new selling page UI
- `templates/index.html`: Added navigation link

### Design Patterns
- RESTful API design
- Separation of concerns (database, routes, templates)
- Security-first approach with input validation
- Consistent UI design matching existing pages
- Responsive design for mobile devices

## Support

For issues, questions, or feature requests related to the selling feature, please check:
- Application logs: `logs/superbot.log`
- Browser console for JavaScript errors
- Database structure via SQLite browser

---

**Version**: 1.0  
**Last Updated**: October 2025  
**Status**: Production Ready

