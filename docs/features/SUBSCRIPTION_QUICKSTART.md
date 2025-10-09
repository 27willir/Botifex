# Subscription System - Quick Start Guide

## 🚀 Get Up and Running in 15 Minutes

### Step 1: Install Dependencies (2 min)
```bash
# Make sure you're in your virtual environment
# Activate venv if not already active:
# Windows: venv\Scripts\activate
# Linux/Mac: source venv/bin/activate

pip install -r requirements.txt
```

### Step 2: Update Database (1 min)
```bash
python scripts/init_db.py
```

The database will automatically create the new subscription tables.

### Step 3: Create Stripe Account (5 min)
1. Go to [https://stripe.com](https://stripe.com)
2. Sign up for a free account
3. Verify your email

### Step 4: Configure Stripe (5 min)

#### Get API Keys
1. Log in to [Stripe Dashboard](https://dashboard.stripe.com)
2. Click **Developers** → **API keys**
3. Copy **Publishable key** (starts with `pk_test_`)
4. Copy **Secret key** (starts with `sk_test_`)

#### Create Products
1. Click **Products** → **Add Product**

**Standard Plan:**
- Name: `Super-Bot Standard`
- Price: `$9.99/month` (recurring monthly)
- Save and copy the **Price ID** (starts with `price_`)

**Pro Plan:**
- Name: `Super-Bot Pro`  
- Price: `$39.99/month` (recurring monthly)
- Save and copy the **Price ID** (starts with `price_`)

#### Set Up Webhook
1. Click **Developers** → **Webhooks**
2. Click **Add endpoint**
3. Endpoint URL: `` (for testing)
4. Select events:
   - `checkout.session.completed`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
   - `invoice.payment_succeeded`
   - `invoice.payment_failed`
5. Save and copy the **Signing secret** (starts with `whsec_`)

### Step 5: Update .env File (2 min)

Copy `env_example.txt` to `.env` if you haven't already:
```bash
copy env_example.txt .env  # Windows
# or
cp env_example.txt .env    # Linux/Mac
```

Add your Stripe credentials to `.env`:
```bash
# Add these at the bottom of your .env file
STRIPE_SECRET_KEY=sk_test_YOUR_SECRET_KEY_HERE
STRIPE_PUBLISHABLE_KEY=pk_test_YOUR_PUBLISHABLE_KEY_HERE
STRIPE_WEBHOOK_SECRET=whsec_YOUR_WEBHOOK_SECRET_HERE
STRIPE_STANDARD_PRICE_ID=price_YOUR_STANDARD_PRICE_ID
STRIPE_PRO_PRICE_ID=price_YOUR_PRO_PRICE_ID
```

### Step 6: Test It! (5 min)

#### Start the App
```bash
python app.py
```

#### Test Subscription Flow
1. Open browser to `http://localhost:5000`
2. Log in to your account
3. Click **Subscription** in the sidebar
4. Click **View All Plans**
5. Click **Upgrade Now** on Standard plan
6. You'll be redirected to Stripe Checkout

#### Use Test Credit Card
- Card number: `4242 4242 4242 4242`
- Expiry: Any future date (e.g., `12/25`)
- CVC: Any 3 digits (e.g., `123`)
- Name: Your name
- Email: Your email

#### Complete Checkout
1. Click **Subscribe**
2. You'll be redirected back to Super-Bot
3. Your subscription should now show as **Standard**
4. Try accessing Analytics - it should work now!

### Step 7: Verify Everything Works

#### Check Your Limits
As a Standard user, you should now have:
- ✅ 10 keywords allowed (try adding more in settings)
- ✅ 5 minute minimum refresh interval
- ✅ Access to all platforms (Facebook, Craigslist, KSL)
- ✅ Limited analytics access
- ❌ Selling feature (still locked - requires Pro)

#### Test Pro Upgrade
1. Go to Subscription → Upgrade to Pro
2. Complete checkout with test card
3. Now you should have:
   - ✅ Unlimited keywords
   - ✅ 60 second refresh interval
   - ✅ Full analytics
   - ✅ Selling feature unlocked

#### Check Webhooks
1. Go to [Stripe Dashboard](https://dashboard.stripe.com)
2. Click **Developers** → **Webhooks**
3. Click on your webhook endpoint
4. You should see successful deliveries for your test payments

### Step 8: Admin Dashboard

1. Make yourself an admin (if not already):
   ```bash
   python scripts/create_admin.py
   ```

2. Log in and go to Admin Panel
3. Click **Subscriptions** (new section)
4. You'll see:
   - Total subscriptions
   - MRR (Monthly Recurring Revenue)
   - Subscription breakdown by tier
   - List of all user subscriptions

## 🎉 You're Done!

Your subscription system is now fully operational!

## What's Next?

### Going Live (When Ready)
1. Complete Stripe account verification
2. Switch to live mode in Stripe Dashboard
3. Get live API keys (they start with `sk_live_` and `pk_live_`)
4. Create live products and prices
5. Update `.env` with live credentials
6. Deploy to production server
7. Update webhook URL to your production domain

### Marketing Your Tiers

**Free Plan** - Lead generator
- Gets users hooked on the platform
- Shows value of automated scraping
- Limited features create upgrade pressure

**Standard Plan** - Sweet spot
- Price point most users can afford
- Enough features for serious users
- Good margin for sustainable business

**Pro Plan** - Power users
- Premium features for heavy users
- Best margin per user
- Makes Standard look more affordable

## Troubleshooting

### Webhook Not Receiving Events
- Check webhook URL is accessible
- For local testing, use [ngrok](https://ngrok.com) or [Stripe CLI](https://stripe.com/docs/stripe-cli)
- Verify webhook secret in `.env`

### Checkout Button Not Working
- Check browser console for errors
- Verify price IDs in `.env` match Stripe
- Make sure you're using test keys with test price IDs

### Subscription Not Updating After Payment
- Check webhook delivery in Stripe Dashboard
- Look at app logs: `logs/superbot.log`
- Verify webhook handler is running

## Quick Reference

### Test Credit Cards
- **Success**: `4242 4242 4242 4242`
- **Decline**: `4000 0000 0000 0002`
- **Auth Required**: `4000 0025 0000 3155`

### Stripe Dashboard Links
- Keys: https://dashboard.stripe.com/apikeys
- Products: https://dashboard.stripe.com/products
- Webhooks: https://dashboard.stripe.com/webhooks
- Payments: https://dashboard.stripe.com/payments
- Customers: https://dashboard.stripe.com/customers

### Key Files
- `subscriptions.py` - Subscription logic
- `subscription_middleware.py` - Access control
- `app.py` - Routes (lines 610-843)
- `db_enhanced.py` - Database functions (lines 1274-1469)
- `templates/subscription_plans.html` - Plans page
- `docs/SUBSCRIPTION_SETUP.md` - Detailed setup guide

## Support

Need help? Check:
1. `SUBSCRIPTION_IMPLEMENTATION.md` - Full implementation details
2. `docs/SUBSCRIPTION_SETUP.md` - Detailed Stripe setup
3. Application logs - `logs/superbot.log`
4. Stripe docs - https://stripe.com/docs

---

**Happy Coding! 🚀** Your Super-Bot is now a money-making machine! 💰

