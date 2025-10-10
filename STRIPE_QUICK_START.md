# 🚀 Connect Stripe - 2 Minute Quick Start

## What You Need
5 values from Stripe to paste into your `.env` file:
1. **Secret Key** (`sk_test_...`)
2. **Publishable Key** (`pk_test_...`)
3. **Webhook Secret** (`whsec_...`)
4. **Standard Plan Price ID** (`price_...`)
5. **Pro Plan Price ID** (`price_...`)

## Option 1: Automated Setup (Easiest)

```bash
python setup_env.py
```

Follow the prompts and paste your Stripe credentials when asked.

## Option 2: Manual Setup

### Step 1: Create .env file
```bash
# Copy the template
copy docs\env_example.txt .env
```

### Step 2: Get Stripe Values

Go to https://dashboard.stripe.com and get:

1. **API Keys** (Developers → API keys)
   - Copy Secret Key and Publishable Key

2. **Create Products** (Products → Add Product)
   - **Standard**: Name it, set price to $9.99/month recurring
     - Copy the Price ID
   - **Pro**: Name it, set price to $39.99/month recurring
     - Copy the Price ID

3. **Webhook** (Developers → Webhooks → Add Endpoint)
   - URL: `http://localhost:5000/webhook/stripe`
   - Events: Select these 5:
     - `checkout.session.completed`
     - `customer.subscription.updated`
     - `customer.subscription.deleted`
     - `invoice.payment_succeeded`
     - `invoice.payment_failed`
   - Copy the Signing Secret

### Step 3: Edit .env file

Open `.env` in a text editor and find these lines (around line 67-75):

```bash
STRIPE_SECRET_KEY=sk_test_your-stripe-secret-key-here
STRIPE_PUBLISHABLE_KEY=pk_test_your-stripe-publishable-key-here
STRIPE_WEBHOOK_SECRET=whsec_your-webhook-secret-here
STRIPE_STANDARD_PRICE_ID=price_your-standard-price-id
STRIPE_PRO_PRICE_ID=price_your-pro-price-id
```

Replace the placeholder values with your actual Stripe values.

### Step 4: Start App

```bash
python app.py
```

### Step 5: Test

1. Go to http://localhost:5000
2. Login
3. Click **Subscription** → **View All Plans**
4. Click **Upgrade Now**
5. Use test card: `4242 4242 4242 4242`
6. Any future expiry, any CVC
7. Complete checkout
8. Your subscription should update to Standard!

## ✅ Verification Checklist

- [ ] `.env` file exists in project root
- [ ] All 5 STRIPE_* variables are filled in
- [ ] Values start with correct prefixes:
  - [ ] `sk_test_` for secret key
  - [ ] `pk_test_` for publishable key  
  - [ ] `whsec_` for webhook secret
  - [ ] `price_` for both price IDs
- [ ] App starts without "Stripe not configured" errors
- [ ] Can access subscription page
- [ ] Checkout redirects to Stripe
- [ ] Payment with test card works
- [ ] Subscription updates after payment

## 🆘 Common Issues

### "Stripe not configured" error
- Check all 5 variables are in `.env`
- Restart the app after editing `.env`

### Checkout button doesn't work
- Check browser console (F12) for errors
- Verify Price IDs match what's in Stripe Dashboard
- Make sure using test keys with test prices

### Payment works but subscription doesn't update
- Webhooks issue - check Stripe Dashboard → Webhooks
- For local testing, use Stripe CLI:
  ```bash
  stripe listen --forward-to localhost:5000/webhook/stripe
  ```

## 📚 More Help

- **Detailed Setup**: `STRIPE_SETUP_GUIDE.md` (15 min with screenshots)
- **Full Docs**: `docs/SUBSCRIPTION_SETUP.md`
- **Quick Start**: `docs/features/SUBSCRIPTION_QUICKSTART.md`

## 🎉 That's It!

You're done! Your app now has:
- ✅ Free tier (always available)
- ✅ Standard tier ($9.99/month)
- ✅ Pro tier ($39.99/month)
- ✅ Automatic subscription enforcement
- ✅ Stripe payment processing
- ✅ Customer portal for managing subscriptions

Start making money! 💰

