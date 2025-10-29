"""
Subscription Management Module
Handles Stripe integration and subscription tier enforcement
"""

import os
import stripe
import logging
import sys
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# Initialize Stripe with specific configuration to avoid recursion
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET')

# Configure Stripe to use minimal retries and logging to prevent recursion issues
stripe.max_network_retries = 1  # Reduce retries to prevent timeout/recursion
stripe.enable_telemetry = False  # Disable telemetry to reduce HTTP calls

# Create a dedicated logger for subscriptions to avoid circular imports
# Set propagate to False to prevent triggering parent logger handlers
logger = logging.getLogger('superbot.subscriptions')
logger.propagate = False  # CRITICAL: Don't propagate to parent logger to avoid recursion

# Add a simple handler that writes directly to stderr to avoid Flask logging system
if not logger.handlers:
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s subscriptions: %(message)s'))
    logger.addHandler(stderr_handler)
    logger.setLevel(logging.INFO)

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
            'platforms': ['craigslist', 'ebay'],  # Free users can only access Craigslist and eBay
            'max_platforms': 2,
            'analytics': False,
            'selling': False,
            'notifications': False,
            'priority_support': False,
            'poshmark': False,  # Poshmark is pro-only
            'mercari': False,  # Mercari is pro-only
            'facebook': False,  # Facebook requires Standard or Pro
            'ksl': False  # KSL requires Standard or Pro
        }
    },
    'standard': {
        'name': 'Standard',
        'price': 9.99,
        'price_id': os.getenv('STRIPE_STANDARD_PRICE_ID'),  # Set this in .env
        'features': {
            'max_keywords': 10,
            'refresh_interval': 300,  # 5 minutes in seconds
            'platforms': ['craigslist', 'facebook', 'ksl', 'ebay'],  # Standard includes Facebook and KSL
            'max_platforms': 4,
            'analytics': 'limited',  # Limited analytics
            'selling': False,
            'notifications': True,
            'priority_support': False,
            'poshmark': False,  # Poshmark is pro-only
            'mercari': False,  # Mercari is pro-only
            'facebook': True,  # Facebook included in Standard
            'ksl': True  # KSL included in Standard
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
            'mercari': True,  # Mercari is pro-only
            'facebook': True,  # Facebook included in Pro
            'ksl': True  # KSL included in Pro
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
        import sys
        
        # Store original logging state to restore later
        original_logging_disabled = logging.root.manager.disable
        stripe_logger = logging.getLogger('stripe')
        urllib3_logger = logging.getLogger('urllib3')
        original_stripe_level = stripe_logger.level
        original_stripe_handlers = stripe_logger.handlers.copy()
        original_stripe_propagate = stripe_logger.propagate
        
        # Also silence urllib3 which Stripe uses
        original_urllib3_level = urllib3_logger.level
        original_urllib3_propagate = urllib3_logger.propagate
        
        try:
            # Validate Stripe configuration first
            if not stripe.api_key:
                print("ERROR: Stripe API key not configured", file=sys.stderr)
                return None, "Payment system not configured"
            
            tier = SUBSCRIPTION_TIERS.get(tier_name)
            if not tier or not tier['price_id']:
                print(f"ERROR: Invalid tier or missing price_id for tier: {tier_name}", file=sys.stderr)
                return None, "Invalid subscription tier"
            
            print(f"INFO: Starting Stripe checkout for {username} - {tier_name}", file=sys.stderr)
            
            # CRITICAL: Completely disable logging during Stripe API call to prevent recursion
            # Disable ALL Python logging temporarily
            logging.disable(logging.CRITICAL)
            
            # Also explicitly configure Stripe and urllib3 loggers to be silent
            stripe_logger.setLevel(logging.CRITICAL)
            stripe_logger.handlers = []
            stripe_logger.propagate = False
            
            urllib3_logger.setLevel(logging.CRITICAL)
            urllib3_logger.propagate = False
            
            # Set recursion limit higher temporarily to allow Stripe's internal operations
            import sys as sys_module
            old_recursion_limit = sys_module.getrecursionlimit()
            sys_module.setrecursionlimit(3000)  # Increase from default 1000
            
            try:
                # Create session - Flask 3.x handles context isolation properly
                print("INFO: Making Stripe API call...", file=sys.stderr)
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
                print("INFO: Stripe API call successful", file=sys.stderr)
                
            finally:
                # Restore recursion limit
                sys_module.setrecursionlimit(old_recursion_limit)
                
                # Re-enable logging
                logging.disable(original_logging_disabled)
                stripe_logger.setLevel(original_stripe_level)
                stripe_logger.handlers = original_stripe_handlers
                stripe_logger.propagate = original_stripe_propagate
                urllib3_logger.setLevel(original_urllib3_level)
                urllib3_logger.propagate = original_urllib3_propagate
            
            print(f"SUCCESS: Created checkout session for {username} - {tier_name}: {session.id}", file=sys.stderr)
            return session, None
            
        except stripe.error.StripeError as e:
            # Use stderr to avoid Flask logging system completely
            print(f"STRIPE ERROR creating checkout session: {type(e).__name__}: {str(e)[:200]}", file=sys.stderr)
            return None, str(e)
        except RecursionError as e:
            # Handle recursion error specifically - use stderr
            print(f"RECURSION ERROR in Stripe checkout: {str(e)[:200]}", file=sys.stderr)
            print(f"  Recursion occurred at depth near limit", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr, limit=10)  # Limit traceback to prevent more recursion
            return None, "System error - please try again"
        except Exception as e:
            # Use stderr to avoid Flask logging system completely
            print(f"EXCEPTION creating checkout session: {type(e).__name__}: {str(e)[:200]}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
            return None, str(e)
        finally:
            # Ensure logging is always restored even if there's an error
            try:
                logging.disable(original_logging_disabled)
                stripe_logger.setLevel(original_stripe_level)
                stripe_logger.handlers = original_stripe_handlers
                stripe_logger.propagate = original_stripe_propagate
                urllib3_logger.setLevel(original_urllib3_level)
                urllib3_logger.propagate = original_urllib3_propagate
            except:
                pass  # If restoration fails, don't throw another error
    
    @staticmethod
    def create_customer_portal_session(customer_id, return_url):
        """Create a Stripe customer portal session for managing subscription"""
        import sys
        
        try:
            # Apply similar protection as checkout to prevent recursion
            # (lighter version since this is less frequently called)
            original_logging_disabled = logging.root.manager.disable
            logging.disable(logging.CRITICAL)
            
            try:
                session = stripe.billing_portal.Session.create(
                    customer=customer_id,
                    return_url=return_url
                )
            finally:
                logging.disable(original_logging_disabled)
            
            print(f"SUCCESS: Created portal session for customer: {customer_id}", file=sys.stderr)
            return session, None
            
        except stripe.error.StripeError as e:
            print(f"STRIPE ERROR creating portal session: {type(e).__name__}: {str(e)[:200]}", file=sys.stderr)
            return None, str(e)
        except Exception as e:
            print(f"EXCEPTION creating portal session: {type(e).__name__}: {str(e)[:200]}", file=sys.stderr)
            return None, str(e)
    
    @staticmethod
    def cancel_subscription(subscription_id):
        """Cancel a Stripe subscription"""
        import sys
        
        try:
            # Apply logging protection to prevent recursion
            original_logging_disabled = logging.root.manager.disable
            logging.disable(logging.CRITICAL)
            
            try:
                subscription = stripe.Subscription.delete(subscription_id)
            finally:
                logging.disable(original_logging_disabled)
            
            print(f"SUCCESS: Cancelled subscription: {subscription_id}", file=sys.stderr)
            return True, None
            
        except stripe.error.StripeError as e:
            print(f"STRIPE ERROR cancelling subscription: {type(e).__name__}: {str(e)[:200]}", file=sys.stderr)
            return False, str(e)
        except Exception as e:
            print(f"EXCEPTION cancelling subscription: {type(e).__name__}: {str(e)[:200]}", file=sys.stderr)
            return False, str(e)
    
    @staticmethod
    def get_subscription(subscription_id):
        """Get subscription details from Stripe"""
        import sys
        
        try:
            # Apply logging protection to prevent recursion
            original_logging_disabled = logging.root.manager.disable
            logging.disable(logging.CRITICAL)
            
            try:
                subscription = stripe.Subscription.retrieve(subscription_id)
            finally:
                logging.disable(original_logging_disabled)
            
            return subscription, None
            
        except stripe.error.StripeError as e:
            print(f"STRIPE ERROR retrieving subscription: {type(e).__name__}: {str(e)[:200]}", file=sys.stderr)
            return None, str(e)
        except Exception as e:
            print(f"EXCEPTION retrieving subscription: {type(e).__name__}: {str(e)[:200]}", file=sys.stderr)
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

