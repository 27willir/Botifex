"""
Subscription Management Module
Handles Stripe integration and subscription tier enforcement
"""

import os
import stripe
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# Initialize Stripe
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET')

# Create a dedicated logger for subscriptions to avoid circular imports
logger = logging.getLogger('superbot.subscriptions')

# Validate Stripe configuration
def validate_stripe_config():
    """Validate Stripe configuration on startup"""
    issues = []
    
    if not stripe.api_key:
        issues.append("STRIPE_SECRET_KEY not configured")
        logger.warning("Stripe API key not configured - subscription features will not work")
    
    if not STRIPE_WEBHOOK_SECRET:
        issues.append("STRIPE_WEBHOOK_SECRET not configured")
        logger.warning("Stripe webhook secret not configured - webhooks will not work")
    
    required_price_ids = {
        'standard': os.getenv('STRIPE_STANDARD_PRICE_ID'),
        'pro': os.getenv('STRIPE_PRO_PRICE_ID')
    }
    
    for tier, price_id in required_price_ids.items():
        if not price_id:
            issues.append(f"STRIPE_{tier.upper()}_PRICE_ID not configured")
            logger.warning(f"Missing STRIPE_{tier.upper()}_PRICE_ID in environment - {tier} tier checkout will not work")
    
    if issues:
        logger.warning(f"Stripe configuration issues found: {', '.join(issues)}")
        return False, issues
    
    logger.info("Stripe configuration validated successfully")
    return True, []

# Subscription Tiers Configuration
SUBSCRIPTION_TIERS = {
    'free': {
        'name': 'Free',
        'price': 0,
        'price_id': None,  # No Stripe price ID for free tier
        'features': {
            'max_keywords': 2,
            'refresh_interval': 600,  # 10 minutes in seconds
            'platforms': ['craigslist', 'ebay'],  # Free platforms
            'max_platforms': 2,
            'analytics': False,
            'selling': False,
            'notifications': False,
            'priority_support': False,
            'poshmark': False,  # Poshmark is pro-only
            'mercari': False  # Mercari is pro-only
        }
    },
    'standard': {
        'name': 'Standard',
        'price': 9.99,
        'price_id': os.getenv('STRIPE_STANDARD_PRICE_ID'),  # Set this in .env
        'features': {
            'max_keywords': 10,
            'refresh_interval': 300,  # 5 minutes in seconds
            'platforms': ['craigslist', 'facebook', 'ksl', 'ebay'],  # All platforms except Poshmark and Mercari
            'max_platforms': 4,
            'analytics': 'limited',  # Limited analytics
            'selling': False,
            'notifications': True,
            'priority_support': False,
            'poshmark': False,  # Poshmark is pro-only
            'mercari': False  # Mercari is pro-only
        }
    },
    'pro': {
        'name': 'Pro',
        'price': 39.99,
        'price_id': os.getenv('STRIPE_PRO_PRICE_ID'),  # Set this in .env
        'features': {
            'max_keywords': -1,  # Unlimited (-1 indicates no limit)
            'refresh_interval': 60,  # 60 seconds
            'platforms': ['craigslist', 'facebook', 'ksl', 'ebay', 'poshmark', 'mercari'],  # All platforms including Poshmark and Mercari
            'max_platforms': -1,  # Unlimited
            'analytics': True,  # Full analytics
            'selling': True,
            'notifications': True,
            'priority_support': True,
            'poshmark': True,  # Poshmark is pro-only
            'mercari': True  # Mercari is pro-only
        }
    }
}

class SubscriptionManager:
    """Manages subscription-related operations"""
    
    @staticmethod
    def get_tier_info(tier_name):
        """Get information about a subscription tier"""
        return SUBSCRIPTION_TIERS.get(tier_name, SUBSCRIPTION_TIERS['free'])
    
    @staticmethod
    def get_user_tier_features(tier_name):
        """Get features for a user's subscription tier"""
        tier = SUBSCRIPTION_TIERS.get(tier_name, SUBSCRIPTION_TIERS['free'])
        return tier['features']
    
    @staticmethod
    def can_use_feature(tier_name, feature):
        """Check if a tier can use a specific feature"""
        features = SubscriptionManager.get_user_tier_features(tier_name)
        feature_value = features.get(feature, False)
        
        # Handle boolean features
        if isinstance(feature_value, bool):
            return feature_value
        
        # Handle string features (like 'limited')
        if isinstance(feature_value, str):
            return len(feature_value) > 0  # Non-empty strings are truthy
        
        return bool(feature_value)
    
    @staticmethod
    def get_keyword_limit(tier_name):
        """Get maximum keywords allowed for a tier"""
        features = SubscriptionManager.get_user_tier_features(tier_name)
        max_keywords = features.get('max_keywords', 2)
        return float('inf') if max_keywords == -1 else max_keywords
    
    @staticmethod
    def get_refresh_interval(tier_name):
        """Get minimum refresh interval for a tier (in seconds)"""
        features = SubscriptionManager.get_user_tier_features(tier_name)
        return features.get('refresh_interval', 600)
    
    @staticmethod
    def get_allowed_platforms(tier_name):
        """Get list of allowed platforms for a tier"""
        features = SubscriptionManager.get_user_tier_features(tier_name)
        return features.get('platforms', ['craigslist'])
    
    @staticmethod
    def get_max_platforms(tier_name):
        """Get maximum number of platforms for a tier"""
        features = SubscriptionManager.get_user_tier_features(tier_name)
        max_platforms = features.get('max_platforms', 1)
        return float('inf') if max_platforms == -1 else max_platforms
    
    @staticmethod
    def validate_keyword_count(tier_name, keyword_count):
        """Validate if keyword count is within tier limits"""
        max_keywords = SubscriptionManager.get_keyword_limit(tier_name)
        if max_keywords == float('inf'):
            return True, None
        
        if keyword_count > max_keywords:
            return False, f"Your {tier_name} plan allows up to {max_keywords} keywords. Please upgrade for more."
        
        return True, None
    
    @staticmethod
    def validate_refresh_interval(tier_name, interval_seconds):
        """Validate if refresh interval meets tier requirements"""
        min_interval = SubscriptionManager.get_refresh_interval(tier_name)
        
        if interval_seconds < min_interval:
            min_minutes = min_interval // 60
            return False, f"Your {tier_name} plan allows minimum {min_minutes} minute refresh interval. Please upgrade for faster updates."
        
        return True, None
    
    @staticmethod
    def validate_platform_access(tier_name, platforms):
        """Validate if platforms are allowed for tier"""
        allowed_platforms = SubscriptionManager.get_allowed_platforms(tier_name)
        max_platforms = SubscriptionManager.get_max_platforms(tier_name)
        
        # Check platform count
        if max_platforms != float('inf') and len(platforms) > max_platforms:
            return False, f"Your {tier_name} plan allows up to {max_platforms} platform(s). Please upgrade for more."
        
        # Check if platforms are allowed
        for platform in platforms:
            if platform not in allowed_platforms:
                return False, f"Platform '{platform}' is not available in your {tier_name} plan. Please upgrade."
        
        return True, None


class StripeManager:
    """Handles Stripe payment integration"""
    
    @staticmethod
    def create_checkout_session(tier_name, user_email, username, success_url, cancel_url):
        """Create a Stripe checkout session for subscription"""
        try:
            # Validate Stripe configuration first
            if not stripe.api_key:
                logger.error("Stripe API key not configured")
                return None, "Payment system not configured"
            
            tier = SUBSCRIPTION_TIERS.get(tier_name)
            if not tier or not tier['price_id']:
                logger.error(f"Invalid tier or missing price_id for tier: {tier_name}")
                return None, "Invalid subscription tier"
            
            # Create session with timeout to prevent hanging
            session = stripe.checkout.Session.create(
                customer_email=user_email,
                line_items=[{
                    'price': tier['price_id'],
                    'quantity': 1,
                }],
                mode='subscription',
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    'username': username,
                    'tier': tier_name
                },
                subscription_data={
                    'metadata': {
                        'username': username,
                        'tier': tier_name
                    }
                }
            )
            
            logger.info(f"Created checkout session for {username} - {tier_name}: {session.id}")
            return session, None
            
        except stripe.error.StripeError as e:
            # Use basic logging to avoid recursion
            print(f"Stripe error creating checkout session: {e}")
            return None, str(e)
        except RecursionError as e:
            # Handle recursion error specifically
            print(f"Recursion error in Stripe checkout: {e}")
            return None, "System error - please try again"
        except Exception as e:
            # Use basic logging to avoid recursion
            print(f"Error creating checkout session: {e}")
            return None, str(e)
    
    @staticmethod
    def create_customer_portal_session(customer_id, return_url):
        """Create a Stripe customer portal session for managing subscription"""
        try:
            session = stripe.billing_portal.Session.create(
                customer=customer_id,
                return_url=return_url,
            )
            logger.info(f"Created portal session for customer: {customer_id}")
            return session, None
            
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error creating portal session: {e}")
            return None, str(e)
        except Exception as e:
            logger.error(f"Error creating portal session: {e}")
            return None, str(e)
    
    @staticmethod
    def cancel_subscription(subscription_id):
        """Cancel a Stripe subscription"""
        try:
            subscription = stripe.Subscription.delete(subscription_id)
            logger.info(f"Cancelled subscription: {subscription_id}")
            return True, None
            
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error cancelling subscription: {e}")
            return False, str(e)
        except Exception as e:
            logger.error(f"Error cancelling subscription: {e}")
            return False, str(e)
    
    @staticmethod
    def get_subscription(subscription_id):
        """Get subscription details from Stripe"""
        try:
            subscription = stripe.Subscription.retrieve(subscription_id)
            return subscription, None
            
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error retrieving subscription: {e}")
            return None, str(e)
        except Exception as e:
            logger.error(f"Error retrieving subscription: {e}")
            return None, str(e)
    
    @staticmethod
    def verify_webhook_signature(payload, sig_header):
        """Verify Stripe webhook signature"""
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, STRIPE_WEBHOOK_SECRET
            )
            return event, None
        except ValueError as e:
            logger.error(f"Invalid payload: {e}")
            return None, "Invalid payload"
        except stripe.error.SignatureVerificationError as e:
            logger.error(f"Invalid signature: {e}")
            return None, "Invalid signature"
    
    @staticmethod
    def handle_webhook_event(event):
        """Handle Stripe webhook events"""
        event_type = event['type']
        data = event['data']['object']
        
        logger.info(f"Processing webhook event: {event_type}")
        
        handlers = {
            'checkout.session.completed': StripeManager._handle_checkout_completed,
            'customer.subscription.updated': StripeManager._handle_subscription_updated,
            'customer.subscription.deleted': StripeManager._handle_subscription_deleted,
            'invoice.payment_succeeded': StripeManager._handle_payment_succeeded,
            'invoice.payment_failed': StripeManager._handle_payment_failed,
        }
        
        handler = handlers.get(event_type)
        if handler:
            return handler(data)
        else:
            logger.info(f"Unhandled webhook event type: {event_type}")
            return {'status': 'unhandled', 'event_type': event_type}
    
    @staticmethod
    def _handle_checkout_completed(session):
        """Handle successful checkout"""
        username = session['metadata'].get('username')
        tier = session['metadata'].get('tier')
        subscription_id = session.get('subscription')
        customer_id = session.get('customer')
        
        logger.info(f"Checkout completed for {username} - tier: {tier}")
        
        return {
            'status': 'success',
            'username': username,
            'tier': tier,
            'subscription_id': subscription_id,
            'customer_id': customer_id
        }
    
    @staticmethod
    def _handle_subscription_updated(subscription):
        """Handle subscription update"""
        customer_id = subscription.get('customer')
        status = subscription.get('status')
        
        logger.info(f"Subscription updated for customer {customer_id} - status: {status}")
        
        return {
            'status': 'updated',
            'customer_id': customer_id,
            'subscription_status': status
        }
    
    @staticmethod
    def _handle_subscription_deleted(subscription):
        """Handle subscription cancellation"""
        customer_id = subscription.get('customer')
        
        logger.info(f"Subscription deleted for customer {customer_id}")
        
        return {
            'status': 'deleted',
            'customer_id': customer_id
        }
    
    @staticmethod
    def _handle_payment_succeeded(invoice):
        """Handle successful payment"""
        customer_id = invoice.get('customer')
        subscription_id = invoice.get('subscription')
        
        logger.info(f"Payment succeeded for customer {customer_id}")
        
        return {
            'status': 'payment_success',
            'customer_id': customer_id,
            'subscription_id': subscription_id
        }
    
    @staticmethod
    def _handle_payment_failed(invoice):
        """Handle failed payment"""
        customer_id = invoice.get('customer')
        subscription_id = invoice.get('subscription')
        
        logger.warning(f"Payment failed for customer {customer_id}")
        
        return {
            'status': 'payment_failed',
            'customer_id': customer_id,
            'subscription_id': subscription_id
        }


def get_all_tiers():
    """Get all available subscription tiers"""
    return SUBSCRIPTION_TIERS


def format_price(price):
    """Format price for display"""
    if price == 0:
        return "Free"
    return f"${price:.2f}/mo"

