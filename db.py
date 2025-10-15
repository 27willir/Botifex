# db.py - Compatibility layer for backward compatibility
# This module re-exports all functions from db_enhanced for scrapers and legacy code

from db_enhanced import (
    # Database initialization
    init_db,
    close_database,
    get_pool,
    
    # User management
    get_user_by_username,
    get_user_by_email,
    create_user_db,
    update_user_login,
    get_all_users,
    get_user_count,
    update_user_role,
    deactivate_user,
    
    # Email verification and password reset
    create_verification_token,
    verify_email_token,
    create_password_reset_token,
    verify_password_reset_token,
    use_password_reset_token,
    reset_user_password,
    
    # Favorites
    add_favorite,
    remove_favorite,
    get_favorites,
    is_favorited,
    update_favorite_notes,
    
    # Saved searches
    create_saved_search,
    get_saved_searches,
    delete_saved_search,
    update_saved_search_last_run,
    
    # Price alerts
    create_price_alert,
    get_price_alerts,
    delete_price_alert,
    toggle_price_alert,
    update_price_alert_triggered,
    get_active_price_alerts,
    
    # Pagination
    get_listings_paginated,
    
    # Notification preferences
    get_notification_preferences,
    update_notification_preferences,
    get_users_with_notifications_enabled,
    
    # Settings management
    get_settings,
    update_setting,
    
    # User activity
    log_user_activity,
    get_user_activity,
    get_recent_activity,
    
    # Rate limiting
    check_rate_limit,
    reset_rate_limit,
    
    # Listings
    save_listing,
    get_listings,
    get_listing_count,
    
    # Analytics
    save_listing_analytics,
    get_keyword_trends,
    get_price_analytics,
    get_source_comparison,
    get_keyword_analysis,
    get_hourly_activity,
    get_price_distribution,
    update_keyword_trends,
    get_market_insights,
    
    # Seller listings
    create_seller_listing,
    get_seller_listings,
    get_seller_listing_by_id,
    update_seller_listing,
    delete_seller_listing,
    update_seller_listing_urls,
    get_seller_listing_stats,
    
    # Subscription management
    get_user_subscription,
    create_or_update_subscription,
    log_subscription_event,
    get_subscription_history,
    cancel_subscription,
    get_all_subscriptions,
    get_subscription_stats,
    get_subscription_by_customer_id,
    
    # Terms of Service
    record_tos_agreement,
)

# Re-export all functions for backward compatibility
__all__ = [
    'init_db',
    'close_database',
    'get_pool',
    'get_user_by_username',
    'get_user_by_email',
    'create_user_db',
    'update_user_login',
    'get_all_users',
    'get_user_count',
    'update_user_role',
    'deactivate_user',
    'get_notification_preferences',
    'update_notification_preferences',
    'get_users_with_notifications_enabled',
    'get_settings',
    'update_setting',
    'log_user_activity',
    'get_user_activity',
    'get_recent_activity',
    'check_rate_limit',
    'reset_rate_limit',
    'save_listing',
    'get_listings',
    'get_listing_count',
    'save_listing_analytics',
    'get_keyword_trends',
    'get_price_analytics',
    'get_source_comparison',
    'get_keyword_analysis',
    'get_hourly_activity',
    'get_price_distribution',
    'update_keyword_trends',
    'get_market_insights',
    'create_seller_listing',
    'get_seller_listings',
    'get_seller_listing_by_id',
    'update_seller_listing',
    'delete_seller_listing',
    'update_seller_listing_urls',
    'get_seller_listing_stats',
    'get_user_subscription',
    'create_or_update_subscription',
    'log_subscription_event',
    'get_subscription_history',
    'cancel_subscription',
    'get_all_subscriptions',
    'get_subscription_stats',
    'get_subscription_by_customer_id',
    'record_tos_agreement',
    'create_verification_token',
    'verify_email_token',
    'create_password_reset_token',
    'verify_password_reset_token',
    'use_password_reset_token',
    'reset_user_password',
    'add_favorite',
    'remove_favorite',
    'get_favorites',
    'is_favorited',
    'update_favorite_notes',
    'create_saved_search',
    'get_saved_searches',
    'delete_saved_search',
    'update_saved_search_last_run',
    'create_price_alert',
    'get_price_alerts',
    'delete_price_alert',
    'toggle_price_alert',
    'update_price_alert_triggered',
    'get_active_price_alerts',
    'get_listings_paginated',
]