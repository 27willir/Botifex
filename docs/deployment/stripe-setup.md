# Stripe Payment Integration Setup

Complete guide to integrating Stripe payments with Super-Bot.

## 📋 Overview

Super-Bot uses Stripe for subscription management with three tiers:
- **Free**: $0 - Basic features
- **Standard**: $9.99/month - Enhanced features
- **Pro**: $39.99/month - All features

---

## 🚀 Quick Setup (10 Minutes)

### 1. Create Stripe Account

Visit [https://dashboard.stripe.com/register](https://dashboard.stripe.com/register)

### 2. Get API Keys

1. Go to [https://dashboard.stripe.com/apikeys](https://dashboard.stripe.com/apikeys)
2. Copy **Publishable key** → Save for later
3. Click "Reveal test key" (or "Reveal live key" for production)
4. Copy **Secret key** → Save for later

### 3. Create Products

1. Go to [https://dashboard.stripe.com/products](https://dashboard.stripe.com/products)
2. Click **"+ Add product"**

**Standard Plan:**
- Name: `Super-Bot Standard`
- Description: `Enhanced marketplace scraping with 10 keywords and all platforms`
- Price: `$9.99 USD`
- Billing: `Recurring - Monthly`
- Click **Save product**
- Copy the **Price ID** (starts with `price_`)

**Pro Plan:**
- Name: `Super-Bot Pro`
- Description: `Premium tier with unlimited keywords, analytics, and selling features`
- Price: `$39.99 USD`
- Billing: `Recurring - Monthly`
- Click **Save product**
- Copy the **Price ID** (starts with `price_`)

### 4. Setup Webhooks

1. Go to [https://dashboard.stripe.com/webhooks](https://dashboard.stripe.com/webhooks)
2. Click **"+ Add endpoint"**
3. Endpoint URL: `https://your domain.com/webhook/stripe`
4. Description: `Super-Bot Subscription Events`
5. Select events to listen to:
   - `checkout.session.completed`
   - `customer.subscription.created`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
   - `invoice.payment_succeeded`
   - `invoice.payment_failed`
6. Click **Add endpoint**
7. Copy the **Signing secret** (starts with `whsec_`)

### 5. Configure Environment

Add to your `.env` file:

```bash
# Stripe API Keys
STRIPE_SECRET_KEY=sk_test_...  # or sk_live_... for production
STRIPE_PUBLISHABLE_KEY=pk_test_...  # or pk_live_... for production

# Webhook Secret
STRIPE_WEBHOOK_SECRET=whsec_...

# Product Price IDs
STRIPE_STANDARD_PRICE_ID=price_...
STRIPE_PRO_PRICE_ID=price_...
```

### 6. Test the Integration

```bash
# Start your app
python app.py

# Visit subscription page
http://localhost:5000/subscription/plans

# Try test checkout (use Stripe test card)
Card: 4242 4242 4242 4242
Expiry: Any future date
CVC: Any 3 digits
```

**Done!** 🎉

---

## 🧪 Testing

### Test Mode vs Live Mode

**Test Mode** (Development):
- Uses test API keys (`sk_test_...`, `pk_test_...`)
- No real money involved
- Use test cards

**Live Mode** (Production):
- Uses live API keys (`sk_live_...`, `pk_live_...`)
- Real payment processing
- Use real credit cards

### Test Cards

```
Success: 4242 4242 4242 4242
Decline: 4000 0000 0000 0002
Insufficient funds: 4000 0000 0000 9995
Authentication required: 4000 0025 0000 3155
```

Expiry: Any future date  
CVC: Any 3 digits  
ZIP: Any 5 digits

### Testing Webhooks Locally

Install Stripe CLI:
```bash
# Mac
brew install stripe/stripe-cli/stripe

# Windows
scoop install stripe

# Linux
wget https://github.com/stripe/stripe-cli/releases/download/v1.13.0/stripe_1.13.0_linux_x86_64.tar.gz
tar -xvf stripe_1.13.0_linux_x86_64.tar.gz
```

Forward webhooks to local server:
```bash
# Login to Stripe
stripe login

# Forward webhooks
stripe listen --forward-to localhost:5000/webhook/stripe

# In another terminal, trigger test events
stripe trigger checkout.session.completed
stripe trigger customer.subscription.updated
```

---

## 🔧 Advanced Configuration

### Custom Pricing

Modify `subscriptions.py`:

```python
SUBSCRIPTION_TIERS = {
    'standard': {
        'price': 9.99,  # Change price
        'price_id': os.getenv('STRIPE_STANDARD_PRICE_ID'),
        'features': {
            'max_keywords': 10,  # Adjust limits
            'refresh_interval': 300,
            # ...
        }
    },
    'pro': {
        'price': 39.99,
        'price_id': os.getenv('STRIPE_PRO_PRICE_ID'),
        'features': {
            'max_keywords': -1,  # -1 = unlimited
            # ...
        }
    }
}
```

### Adding New Tier

1. Create product in Stripe
2. Add to `subscriptions.py`:

```python
'premium': {
    'name': 'Premium',
    'price': 19.99,
    'price_id': os.getenv('STRIPE_PREMIUM_PRICE_ID'),
    'features': {
        'max_keywords': 25,
        'refresh_interval': 120,
        # ...
    }
}
```

3. Add environment variable:
```bash
STRIPE_PREMIUM_PRICE_ID=price_...
```

4. Update templates to show new tier

### Customer Portal

Stripe Customer Portal is automatically configured. Users can:
- Update payment methods
- Cancel subscription
- Download invoices
- Update billing information

Access via: `/subscription/portal`

### Promo Codes & Coupons

Create in Stripe Dashboard:
1. Go to [https://dashboard.stripe.com/coupons](https://dashboard.stripe.com/coupons)
2. Click **"Create coupon"**
3. Configure:
   - Percent off or amount off
   - Duration (once, forever, repeating)
4. Copy coupon ID
5. Share with users to apply at checkout

---

## 🔐 Security

### Webhook Signature Verification

Super-Bot automatically verifies webhook signatures:

```python
# In app.py
event, error = StripeManager.verify_webhook_signature(payload, sig_header)
```

**Never skip signature verification in production!**

### API Key Security

- ✅ Store keys in environment variables
- ✅ Never commit keys to git
- ✅ Use `.env` file (in `.gitignore`)
- ✅ Rotate keys periodically
- ✅ Use test keys in development
- ❌ Never hardcode keys in code
- ❌ Never expose secret key to frontend

### PCI Compliance

Super-Bot is PCI compliant because:
- Stripe handles all card data
- No card information touches your server
- Uses Stripe Checkout (hosted payment page)
- No need for PCI certification

---

## 📊 Monitoring

### Stripe Dashboard

Monitor in real-time:
- [Payments](https://dashboard.stripe.com/payments)
- [Subscriptions](https://dashboard.stripe.com/subscriptions)
- [Customers](https://dashboard.stripe.com/customers)
- [Webhooks](https://dashboard.stripe.com/webhooks)

### Failed Payments

Handle in webhook:
```python
def _handle_payment_failed(invoice):
    customer_id = invoice.get('customer')
    # Send notification to user
    # Update subscription status
    # Implement retry logic
```

### Dunning (Retry Failed Payments)

Configure in Stripe Dashboard:
1. Settings → Billing
2. Configure Smart Retries
3. Enable email notifications

---

## 🐛 Troubleshooting

### Webhook Not Receiving Events

**Check endpoint:**
```bash
# Test webhook is reachable
curl -X POST https://yourdomain.com/webhook/stripe \
  -H "Content-Type: application/json" \
  -d '{"test": true}'
```

**Verify webhook secret:**
```bash
echo $STRIPE_WEBHOOK_SECRET
# Should start with whsec_
```

**Check Stripe logs:**
- Go to Webhooks → Your endpoint
- Click on failed delivery
- See error message

**Common issues:**
- SSL certificate invalid
- Endpoint returns non-200 status
- Signature verification fails
- Server timeout (>30s response)

### Checkout Not Working

**Check API keys:**
```bash
echo $STRIPE_SECRET_KEY
echo $STRIPE_PUBLISHABLE_KEY
# Should match (both test or both live)
```

**Check price IDs:**
```bash
echo $STRIPE_STANDARD_PRICE_ID
echo $STRIPE_PRO_PRICE_ID
# Should start with price_
```

**Test with Stripe CLI:**
```bash
stripe products list
stripe prices list
```

### Subscription Not Activating

**Check webhook is configured:**
- Webhook endpoint exists in dashboard
- Events include `checkout.session.completed`
- Endpoint is reachable from internet

**Check database:**
```python
# In Python console
from db_enhanced import get_user_subscription
subscription = get_user_subscription('username')
print(subscription)
```

**Check logs:**
```bash
tail -f logs/superbot.log | grep stripe
```

### Test Mode vs Live Mode Mismatch

**Symptoms:**
- Payments succeed but don't activate subscription
- "No such customer" errors
- "No such price" errors

**Solution:**
- Ensure all keys are same mode (all test or all live)
- Test keys: `sk_test_...`, `pk_test_...`
- Live keys: `sk_live_...`, `pk_live_...`

---

## 🚀 Going Live

### Pre-Launch Checklist

- [ ] Test full checkout flow
- [ ] Test successful payment
- [ ] Test failed payment
- [ ] Test webhook delivery
- [ ] Test subscription activation
- [ ] Test subscription cancellation
- [ ] Test customer portal
- [ ] Verify all features work for each tier
- [ ] Set up email receipts
- [ ] Configure billing statement descriptor

### Switch to Live Mode

1. **Activate Stripe account:**
   - Submit business information
   - Verify identity
   - Wait for approval

2. **Get live API keys:**
   - Switch to "Live mode" in dashboard
   - Copy live keys from API Keys page

3. **Create live products:**
   - Create same products as test mode
   - Copy live price IDs

4. **Create live webhook:**
   - Same configuration as test webhook
   - Use production URL
   - Copy live webhook secret

5. **Update environment:**
   ```bash
   STRIPE_SECRET_KEY=sk_live_...
   STRIPE_PUBLISHABLE_KEY=pk_live_...
   STRIPE_WEBHOOK_SECRET=whsec_...  # Live secret
   STRIPE_STANDARD_PRICE_ID=price_...  # Live price ID
   STRIPE_PRO_PRICE_ID=price_...  # Live price ID
   ```

6. **Test with real card:**
   - Make real purchase (can refund)
   - Verify subscription activates
   - Check webhook delivery
   - Verify all features work

### Post-Launch

- Monitor [Stripe Dashboard](https://dashboard.stripe.com)
- Set up alerts for failed payments
- Review transactions weekly
- Keep keys secure
- Monitor for fraud
- Respond to disputes promptly

---

## 📚 Additional Resources

- **Stripe Documentation**: https://stripe.com/docs
- **Stripe API Reference**: https://stripe.com/docs/api
- **Webhooks Guide**: https://stripe.com/docs/webhooks
- **Testing Guide**: https://stripe.com/docs/testing
- **Security Best Practices**: https://stripe.com/docs/security
- **Customer Portal**: https://stripe.com/docs/billing/subscriptions/customer-portal

---

## 🆘 Getting Help

- **Stripe Support**: https://support.stripe.com
- **Community**: https://stripe.com/community
- **Status Page**: https://status.stripe.com
- **Super-Bot Issues**: GitHub Issues

---

**Your payment system is now ready!** 💳

Users can now subscribe to paid tiers and access premium features.

