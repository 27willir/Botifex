# Subscription System Setup Guide

## Overview

Super-Bot now includes a comprehensive subscription-based platform with three tiers:

### Subscription Tiers

#### 1. **Free Plan** ($0/month)
- 2 keywords
- 10 minute refresh interval
- 1 platform (Craigslist only)
- No analytics
- No selling feature
- No notifications

#### 2. **Standard Plan** ($9.99/month)
- 10 keywords
- 5 minute refresh interval
- All platforms (Craigslist, Facebook, KSL)
- Limited analytics
- No selling feature
- Email & SMS notifications enabled

#### 3. **Pro Plan** ($39.99/month)
- Unlimited keywords
- 60 second (1 minute) refresh interval
- All platforms (Craigslist, Facebook, KSL)
- Full analytics
- Selling feature enabled
- Email & SMS notifications
- Priority support

## Stripe Setup Instructions

### 1. Create a Stripe Account
1. Go to [https://stripe.com](https://stripe.com) and sign up
2. Verify your email and complete account setup
3. Navigate to the Stripe Dashboard

### 2. Get API Keys
1. In the Stripe Dashboard, go to **Developers > API keys**
2. Copy your **Publishable key** (starts with `pk_test_` or `pk_live_`)
3. Copy your **Secret key** (starts with `sk_test_` or `sk_live_`)
4. Add these to your `.env` file:
   ```
   STRIPE_SECRET_KEY=sk_test_your_key_here
   STRIPE_PUBLISHABLE_KEY=pk_test_your_key_here
   ```

### 3. Create Products and Prices
1. Go to **Products** in the Stripe Dashboard
2. Click **+ Add Product**

**For Standard Plan:**
- Name: `Super-Bot Standard Plan`
- Description: `10 keywords, 5 min refresh, all platforms, limited analytics`
- Pricing:
  - Model: Recurring
  - Price: $9.99
  - Billing period: Monthly
- Click **Save product**
- Copy the **Price ID** (starts with `price_`)
- Add to `.env`: `STRIPE_STANDARD_PRICE_ID=price_your_id_here`

**For Pro Plan:**
- Name: `Super-Bot Pro Plan`
- Description: `Unlimited keywords, 60 sec refresh, all features`
- Pricing:
  - Model: Recurring
  - Price: $39.99
  - Billing period: Monthly
- Click **Save product**
- Copy the **Price ID** (starts with `price_`)
- Add to `.env`: `STRIPE_PRO_PRICE_ID=price_your_id_here`

### 4. Set Up Webhooks
1. Go to **Developers > Webhooks**
2. Click **+ Add endpoint**
3. Enter your endpoint URL: `https://your-domain.com/webhook/stripe`
4. Select events to listen for:
   - `checkout.session.completed`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
   - `invoice.payment_succeeded`
   - `invoice.payment_failed`
5. Click **Add endpoint**
6. Copy the **Signing secret** (starts with `whsec_`)
7. Add to `.env`: `STRIPE_WEBHOOK_SECRET=whsec_your_secret_here`

### 5. Enable Customer Portal
1. Go to **Settings > Billing > Customer portal**
2. Enable the customer portal
3. Configure allowed features:
   - ✅ Update payment method
   - ✅ View invoices
   - ✅ Cancel subscription
   - ✅ Update subscription (optional)
4. Save settings

## Testing the Integration

### Test Mode
Stripe starts in test mode by default. Use test credit cards:
- **Successful payment**: `4242 4242 4242 4242`
- **Declined payment**: `4000 0000 0000 0002`
- Use any future expiry date and any 3-digit CVC

### Test the Flow
1. Log in to your Super-Bot account
2. Navigate to **Subscription** in the sidebar
3. Click **View All Plans** or **Upgrade Plan**
4. Select a plan (Standard or Pro)
5. You'll be redirected to Stripe Checkout
6. Enter test card details
7. Complete checkout
8. You'll be redirected back to Super-Bot
9. Your subscription should be updated

### Verify Webhooks
1. Make a test purchase
2. Check Stripe Dashboard > Developers > Webhooks
3. Click on your webhook endpoint
4. View the webhook delivery attempts
5. All events should show as "Succeeded"

## Going Live

### 1. Switch to Live Mode
1. Complete Stripe account verification
2. Switch from Test mode to Live mode in Stripe Dashboard
3. Get your **live** API keys
4. Create **live** products and prices
5. Get **live** webhook secret
6. Update `.env` with live credentials

### 2. Update Environment
```bash
# Replace test keys with live keys
STRIPE_SECRET_KEY=sk_live_your_live_key_here
STRIPE_PUBLISHABLE_KEY=pk_live_your_live_key_here
STRIPE_WEBHOOK_SECRET=whsec_your_live_secret_here
STRIPE_STANDARD_PRICE_ID=price_your_live_standard_id
STRIPE_PRO_PRICE_ID=price_your_live_pro_id
```

### 3. Update Webhook URL
1. In Stripe Dashboard, update webhook endpoint to production URL
2. Test webhook delivery with a live transaction

## Features Implementation

### Subscription Enforcement
The system automatically enforces subscription limits:

- **Keywords**: Validated when settings are updated
- **Refresh Interval**: Minimum interval enforced per tier
- **Platform Access**: Only allowed platforms can be started
- **Analytics**: Requires Standard or Pro tier
- **Selling**: Requires Pro tier

### Database Structure
New tables added:
- `subscriptions`: Stores user subscription information
- `subscription_history`: Logs subscription events

### API Endpoints

#### User-Facing
- `GET /subscription` - View current subscription
- `GET /subscription/plans` - View all available plans
- `GET /subscription/checkout/<tier>` - Create checkout session
- `GET /subscription/success` - Checkout success page
- `GET /subscription/portal` - Redirect to Stripe customer portal

#### Webhooks
- `POST /webhook/stripe` - Handle Stripe webhook events

#### Admin
- Admin panel includes subscription statistics
- View all users' subscription status
- See subscription revenue metrics

## Subscription Context

All templates have access to these variables:
- `user_subscription` - Current user's subscription data
- `user_tier` - Current tier name ('free', 'standard', 'pro')
- `user_features` - Dictionary of available features
- `can_use_analytics` - Boolean for analytics access
- `can_use_selling` - Boolean for selling feature access
- `max_keywords` - Maximum allowed keywords
- `min_refresh_interval` - Minimum refresh interval in minutes
- `allowed_platforms` - List of allowed platform names

## Decorators and Middleware

### Feature Protection
```python
@require_feature('analytics')
def analytics():
    # Only accessible to users with analytics feature
    pass

@require_subscription_tier('standard')
def advanced_feature():
    # Only Standard and Pro users can access
    pass

@check_keyword_limit()
@check_refresh_interval()
def update_settings():
    # Validates settings against subscription limits
    pass
```

## Troubleshooting

### Webhooks Not Working
1. Check webhook URL is correct and accessible
2. Verify webhook secret in `.env`
3. Check Stripe Dashboard for failed deliveries
4. Ensure your server can receive POST requests at `/webhook/stripe`

### Checkout Not Redirecting
1. Verify price IDs in `.env`
2. Check Stripe logs for errors
3. Ensure success/cancel URLs are correct

### Subscription Not Updating
1. Check webhook delivery in Stripe Dashboard
2. Verify webhook handler is processing events
3. Check application logs for errors
4. Confirm database permissions

## Security Considerations

1. **Always use HTTPS in production**
2. Keep API keys secure - never commit to version control
3. Verify webhook signatures (already implemented)
4. Use environment variables for all sensitive data
5. Regularly rotate API keys
6. Monitor Stripe Dashboard for suspicious activity

## Support

For Stripe-specific issues:
- [Stripe Documentation](https://stripe.com/docs)
- [Stripe Support](https://support.stripe.com)

For Super-Bot issues:
- Check application logs
- Review database for consistency
- Test webhook delivery
- Verify environment variables

## Revenue Tracking

Monitor your subscription revenue:
1. Stripe Dashboard > Home (shows revenue charts)
2. Reports tab for detailed analytics
3. Admin panel shows subscription statistics
4. Database queries for custom reports

---

**Important**: Test thoroughly in test mode before going live!

