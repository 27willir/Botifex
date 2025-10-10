# 🔗 Connect Your Stripe Account - Quick Setup Guide

## Overview
Your Super-Bot has a subscription system with 3 tiers:
- **Free**: 2 keywords, 10 min refresh, Craigslist only
- **Standard**: $9.99/month - 10 keywords, 5 min refresh, all platforms
- **Pro**: $39.99/month - Unlimited keywords, 1 min refresh, all features

## 🚀 Quick Setup (15 minutes)

### Step 1: Create/Login to Stripe (2 min)
1. Go to **https://stripe.com** and sign up (or login)
2. Verify your email
3. You'll start in **Test Mode** (perfect for testing!)

### Step 2: Get Your API Keys (1 min)
1. In Stripe Dashboard, click **Developers** → **API keys**
2. You'll see two keys:
   - **Publishable key** (starts with `pk_test_...`)
   - **Secret key** (starts with `sk_test_...`) - click "Reveal test key"
3. Keep this page open - you'll need these in Step 5

### Step 3: Create Your Products (5 min)

#### Create Standard Plan:
1. Click **Products** in the sidebar
2. Click **+ Add product**
3. Fill in:
   - **Name**: `Super-Bot Standard Plan`
   - **Description**: `10 keywords, 5 min refresh, all platforms, analytics`
   - **Pricing model**: `Standard pricing`
4. Under "Price information":
   - **Price**: `9.99`
   - **Currency**: `USD`
   - **Billing period**: `Monthly` (select Recurring)
5. Click **Save product**
6. **IMPORTANT**: Copy the **Price ID** (looks like `price_1AbC2dEfGhIjKlMn`)
   - You'll find it on the product page under the price

#### Create Pro Plan:
1. Click **Products** again → **+ Add product**
2. Fill in:
   - **Name**: `Super-Bot Pro Plan`
   - **Description**: `Unlimited keywords, 60 sec refresh, all features`
   - **Price**: `39.99` USD
   - **Billing period**: `Monthly` (Recurring)
3. Click **Save product**
4. **Copy the Price ID** for this plan too

### Step 4: Set Up Webhook (4 min)

Webhooks allow Stripe to notify your app when payments happen.

1. Click **Developers** → **Webhooks** → **Add endpoint**
2. For **Endpoint URL**, enter:
   - For local testing: `http://localhost:5000/webhook/stripe`
   - For production: `https://your-domain.com/webhook/stripe`
3. Click **Select events** and choose these 5 events:
   - ✅ `checkout.session.completed`
   - ✅ `customer.subscription.updated`
   - ✅ `customer.subscription.deleted`
   - ✅ `invoice.payment_succeeded`
   - ✅ `invoice.payment_failed`
4. Click **Add endpoint**
5. **Copy the Signing secret** (starts with `whsec_...`)

> **Note for Local Testing**: Webhooks won't work on localhost unless you use:
> - [Stripe CLI](https://stripe.com/docs/stripe-cli) (recommended)
> - [ngrok](https://ngrok.com) to expose localhost to the internet

### Step 5: Update Your .env File (3 min)

Open the `.env` file in your project root and update these lines:

```bash
# Find these lines and replace with YOUR actual values:

STRIPE_SECRET_KEY=sk_test_YOUR_SECRET_KEY_HERE
STRIPE_PUBLISHABLE_KEY=pk_test_YOUR_PUBLISHABLE_KEY_HERE
STRIPE_WEBHOOK_SECRET=whsec_YOUR_WEBHOOK_SECRET_HERE
STRIPE_STANDARD_PRICE_ID=price_YOUR_STANDARD_PRICE_ID
STRIPE_PRO_PRICE_ID=price_YOUR_PRO_PRICE_ID
```

**Example** (don't use these, use your own!):
```bash
STRIPE_SECRET_KEY=sk_test_51AbC123dEfGh456...
STRIPE_PUBLISHABLE_KEY=pk_test_51AbC123dEfGh456...
STRIPE_WEBHOOK_SECRET=whsec_abc123def456...
STRIPE_STANDARD_PRICE_ID=price_1JklMnOpQrStUv
STRIPE_PRO_PRICE_ID=price_1WxYzAbCdEfGhI
```

**⚠️ Important**: Never commit your `.env` file to git! It's already in `.gitignore`.

## ✅ Test Your Integration

### Start Your App:
```bash
python app.py
```

### Test the Flow:
1. Open http://localhost:5000
2. Login to your account
3. Click **Subscription** in the sidebar
4. Click **View All Plans**
5. Click **Upgrade Now** on Standard plan
6. You should be redirected to Stripe Checkout

### Use Test Card:
Stripe provides test cards that work in test mode:
- **Card Number**: `4242 4242 4242 4242`
- **Expiry**: Any future date (e.g., `12/28`)
- **CVC**: Any 3 digits (e.g., `123`)
- **ZIP**: Any 5 digits (e.g., `12345`)

### Complete Payment:
1. Fill in the test card details
2. Enter your email
3. Click **Subscribe**
4. You should be redirected back to Super-Bot
5. Your subscription should now show **Standard**!

### Verify:
- Go to **Settings** - you should now be able to add up to 10 keywords
- Go to **Analytics** - it should work now!
- Check Stripe Dashboard → **Payments** to see your test payment

## 🔍 Troubleshooting

### Issue: "Stripe not configured" error
- **Solution**: Make sure all 5 Stripe variables are in your `.env` file
- Restart the app after updating `.env`

### Issue: Checkout button doesn't work
- **Solution**: Open browser console (F12) and check for errors
- Verify your Price IDs are correct in `.env`
- Make sure you're using test keys with test price IDs

### Issue: Payment succeeds but subscription doesn't update
- **Solution**: This means webhooks aren't working
- For local testing, use Stripe CLI:
  ```bash
  stripe login
  stripe listen --forward-to localhost:5000/webhook/stripe
  ```
- Update `STRIPE_WEBHOOK_SECRET` with the webhook secret from Stripe CLI

### Issue: Where are the logs?
- Check `logs/superbot.log` for errors
- Check Stripe Dashboard → Developers → Webhooks for webhook delivery status

## 🌐 Going Live (When Ready)

When you're ready to accept real payments:

1. **Complete Stripe verification**
   - Stripe Dashboard → Complete your business profile
   - Submit required documents

2. **Switch to Live Mode**
   - Toggle from "Test mode" to "Live mode" in Stripe Dashboard

3. **Get Live Keys**
   - Get new API keys (they'll start with `sk_live_` and `pk_live_`)
   - Create new products with live prices
   - Set up new webhook with live webhook secret

4. **Update .env**
   - Replace all test keys with live keys
   - Update webhook URL to your production domain

5. **Deploy to Production**
   - Make sure your server uses HTTPS (required for Stripe)
   - Update webhook URL in Stripe to production URL

## 📚 Additional Resources

- **Full Setup Guide**: `docs/SUBSCRIPTION_SETUP.md`
- **Quick Start**: `docs/features/SUBSCRIPTION_QUICKSTART.md`
- **Stripe Docs**: https://stripe.com/docs
- **Test Cards**: https://stripe.com/docs/testing

## 💡 Pro Tips

1. **Always test in Test Mode first** - it's free and works exactly like live mode
2. **Use Stripe CLI for local webhook testing** - much easier than ngrok
3. **Check webhook logs** in Stripe Dashboard if something isn't working
4. **Monitor the logs/superbot.log** file for app errors
5. **Keep your keys secure** - never share them or commit to git

## 🎉 You're Ready!

Your Stripe account is now connected! Users can:
- ✅ Subscribe to Standard ($9.99/month)
- ✅ Subscribe to Pro ($39.99/month)
- ✅ Manage subscriptions via Stripe portal
- ✅ Get automatically upgraded/downgraded based on payments

---

**Need Help?** Check the detailed docs in `docs/SUBSCRIPTION_SETUP.md` or open an issue.

