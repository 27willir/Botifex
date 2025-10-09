"""
Swagger API Documentation Configuration
Provides interactive API documentation using Flasgger
"""

from flasgger import Swagger

SWAGGER_TEMPLATE = {
    "swagger": "2.0",
    "info": {
        "title": "Super-Bot API",
        "description": "Marketplace monitoring and automation API",
        "version": "2.0.0",
        "contact": {
            "name": "Super-Bot Support",
            "url": "https://github.com/your-repo"
        },
        "license": {
            "name": "MIT",
            "url": "https://opensource.org/licenses/MIT"
        }
    },
    "host": "localhost:5000",
    "basePath": "/",
    "schemes": ["http", "https"],
    "securityDefinitions": {
        "SessionAuth": {
            "type": "apiKey",
            "name": "session",
            "in": "cookie",
            "description": "Session-based authentication using Flask-Login"
        }
    },
    "security": [
        {"SessionAuth": []}
    ],
    "tags": [
        {
            "name": "Authentication",
            "description": "User authentication and verification"
        },
        {
            "name": "Favorites",
            "description": "Listing favorites and bookmarks"
        },
        {
            "name": "Saved Searches",
            "description": "Saved search management"
        },
        {
            "name": "Price Alerts",
            "description": "Price monitoring and alerts"
        },
        {
            "name": "Listings",
            "description": "Marketplace listings"
        },
        {
            "name": "Analytics",
            "description": "Market analytics and insights"
        },
        {
            "name": "Export",
            "description": "Data export and GDPR compliance"
        },
        {
            "name": "Seller",
            "description": "Seller listing management"
        },
        {
            "name": "Subscriptions",
            "description": "Subscription management"
        }
    ]
}

SWAGGER_CONFIG = {
    "headers": [],
    "specs": [
        {
            "endpoint": 'apispec',
            "route": '/apispec.json',
            "rule_filter": lambda rule: True,
            "model_filter": lambda tag: True,
        }
    ],
    "static_url_path": "/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/api-docs"
}


def init_swagger(app):
    """Initialize Swagger documentation"""
    swagger = Swagger(app, template=SWAGGER_TEMPLATE, config=SWAGGER_CONFIG)
    return swagger


# ======================
# SAMPLE SWAGGER SPECS
# ======================

# These can be added as docstrings to API functions

FAVORITES_GET_SPEC = """
Get user's favorite listings
---
tags:
  - Favorites
security:
  - SessionAuth: []
parameters:
  - name: limit
    in: query
    type: integer
    default: 100
    description: Maximum number of favorites to return
responses:
  200:
    description: List of favorites
    schema:
      type: object
      properties:
        favorites:
          type: array
          items:
            type: object
            properties:
              id:
                type: integer
              title:
                type: string
              price:
                type: integer
              link:
                type: string
              source:
                type: string
              notes:
                type: string
              favorited_at:
                type: string
        count:
          type: integer
  401:
    description: Unauthorized
  500:
    description: Server error
"""

FAVORITES_POST_SPEC = """
Add a listing to favorites
---
tags:
  - Favorites
security:
  - SessionAuth: []
parameters:
  - name: listing_id
    in: path
    type: integer
    required: true
    description: ID of the listing to favorite
  - name: body
    in: body
    schema:
      type: object
      properties:
        notes:
          type: string
          description: Optional notes about the listing
responses:
  200:
    description: Added to favorites
    schema:
      type: object
      properties:
        message:
          type: string
        favorited:
          type: boolean
  401:
    description: Unauthorized
  500:
    description: Server error
"""

PRICE_ALERT_POST_SPEC = """
Create a new price alert
---
tags:
  - Price Alerts
security:
  - SessionAuth: []
parameters:
  - name: body
    in: body
    required: true
    schema:
      type: object
      required:
        - keywords
        - threshold_price
      properties:
        keywords:
          type: string
          description: Keywords to monitor
          example: "Corvette Z06"
        threshold_price:
          type: integer
          description: Price threshold
          example: 25000
        alert_type:
          type: string
          enum: [under, over]
          default: under
          description: Alert when price is under or over threshold
responses:
  201:
    description: Alert created
    schema:
      type: object
      properties:
        message:
          type: string
        alert_id:
          type: integer
  400:
    description: Bad request
  401:
    description: Unauthorized
  500:
    description: Server error
"""

EXPORT_USER_DATA_SPEC = """
Export complete user data (GDPR compliance)
---
tags:
  - Export
security:
  - SessionAuth: []
responses:
  200:
    description: Complete user data export
    schema:
      type: object
      properties:
        user_profile:
          type: object
        settings:
          type: object
        favorites:
          type: array
        saved_searches:
          type: array
        price_alerts:
          type: array
        activity_log:
          type: array
        subscription:
          type: object
        exported_at:
          type: string
  401:
    description: Unauthorized
  429:
    description: Rate limit exceeded (3 requests per hour)
  500:
    description: Server error
"""

PAGINATION_SPEC = """
Get paginated listings
---
tags:
  - Listings
security:
  - SessionAuth: []
parameters:
  - name: page
    in: query
    type: integer
    default: 1
    description: Page number (starts at 1)
  - name: per_page
    in: query
    type: integer
    default: 50
    description: Items per page (1-200)
responses:
  200:
    description: Paginated listings
    schema:
      type: object
      properties:
        listings:
          type: array
        pagination:
          type: object
          properties:
            page:
              type: integer
            per_page:
              type: integer
            total_items:
              type: integer
            total_pages:
              type: integer
            has_next:
              type: boolean
            has_prev:
              type: boolean
            next_page:
              type: integer
            prev_page:
              type: integer
  400:
    description: Bad request
  401:
    description: Unauthorized
  500:
    description: Server error
"""


__all__ = [
    'init_swagger',
    'SWAGGER_TEMPLATE',
    'SWAGGER_CONFIG',
]

