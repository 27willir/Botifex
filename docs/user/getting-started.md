# Getting Started with Super-Bot

Welcome! This guide will help you start finding great deals on your favorite items.

## 🎯 What is Super-Bot?

Super-Bot automatically searches multiple marketplaces for items you want to buy, saving you time and helping you find the best deals.

### Supported Marketplaces
- 🟦 **Facebook Marketplace** - Local deals
- 📋 **Craigslist** - Classified ads
- 🏔️ **KSL Classifieds** - Utah marketplace
- 🛒 **eBay** - Online auctions

---

## 🚀 Quick Start (3 Steps)

### Step 1: Create Account

1. Visit the Super-Bot website
2. Click **"Register"**
3. Enter username, email, and password
4. Accept Terms of Service
5. Click **"Create Account"**

### Step 2: Configure Search

1. Go to **Settings** page
2. Set your preferences:
   - **Keywords**: Items you're looking for (e.g., "iPhone 12, MacBook Pro")
   - **Price Range**: Min and max price
   - **Location**: Your city/region
   - **Refresh Interval**: How often to check (in minutes)

Example:
```
Keywords: Firebird, Camaro, Corvette
Min Price: $5,000
Max Price: $30,000
Location: Boise, ID
Radius: 50 miles
Refresh Interval: 60 minutes
```

### Step 3: Start Scraping

1. Go to **Home** page
2. Click **"Start"** next to any marketplace
3. Watch listings appear automatically!

**That's it!** Super-Bot is now finding deals for you. 🎉

---

## 💡 How It Works

1. **You set preferences** - Tell Super-Bot what you want
2. **Bot searches constantly** - Checks marketplaces every few minutes
3. **New listings appear** - See fresh deals as they're posted
4. **You save time** - No more manual searching!

---

## 📱 Using the Dashboard

### Home Page

Your main command center:
- **Scraper Status**: See which platforms are running
- **Recent Listings**: View latest finds
- **Quick Controls**: Start/stop scrapers
- **Quick Settings**: Adjust search on the fly

### Settings Page

Fine-tune your search:
- **Search Keywords**: What to look for
- **Price Filters**: Budget range
- **Location**: Where to search
- **Notifications**: How to get alerts
- **Refresh Speed**: How often to check

### Favorites

Save listings you like:
1. Click ⭐ on any listing
2. Access from **Favorites** menu
3. Add notes to remember details
4. Export your favorites list

### Analytics (Pro)

See market insights:
- **Price Trends**: How prices change over time
- **Best Times to Buy**: When deals appear
- **Keyword Performance**: What finds the most results
- **Source Comparison**: Which platform has best deals

---

## 🎓 Tips for Success

### Choose Good Keywords

**Good:**
- Specific models: "iPhone 13 Pro", "Toyota Camry 2020"
- Brand names: "Nike", "Sony"
- Unique terms: "Vintage typewriter"

**Avoid:**
- Too generic: "phone", "car"
- Too narrow: "blue iPhone 13 Pro 128GB unlocked mint condition"

### Set Realistic Prices

- Research typical prices first
- Set range 20% above/below average
- Adjust based on results

### Use Multiple Keywords

Free tier: 2 keywords  
Standard: 10 keywords  
Pro: Unlimited keywords

**Example:**
```
Keywords: iPhone 13, iPhone 13 Pro, iPhone 13 Pro Max
```

### Check Regularly

- New listings appear in real-time
- Act fast on good deals
- Set up notifications for alerts

---

## 🔔 Notifications

Get notified about new listings:

### Email Notifications (Standard/Pro)

1. Go to **Settings** → **Notifications**
2. Enable **Email Notifications**
3. Verify your email address
4. Get emails for each new listing

### SMS Notifications (Optional)

1. Add phone number in Settings
2. Enable **SMS Notifications**
3. Requires Twilio configuration

---

## ⭐ Subscription Tiers

### Free Tier

Perfect for casual users:
- ✅ 2 keywords
- ✅ 10-minute refresh
- ✅ Craigslist & eBay
- ✅ Basic listing view

### Standard - $9.99/month

For serious deal hunters:
- ✅ 10 keywords
- ✅ 5-minute refresh
- ✅ All 4 platforms
- ✅ Limited analytics
- ✅ Email notifications
- ✅ Saved searches
- ✅ Price alerts

### Pro - $39.99/month

For power users:
- ✅ **Unlimited keywords**
- ✅ **60-second refresh**
- ✅ All 4 platforms
- ✅ **Full analytics dashboard**
- ✅ **Selling features**
- ✅ Email & SMS notifications
- ✅ Advanced filters
- ✅ Priority support
- ✅ Export data

[View Pricing Details](../deployment/stripe-setup.md)

---

## 🛠️ Common Tasks

### Change Your Search

1. Go to **Settings**
2. Update keywords or price range
3. Click **"Save Settings"**
4. Changes take effect immediately

### Stop/Start Scrapers

**Stop a scraper:**
- Click **"Stop"** button on home page
- Useful to pause during maintenance

**Start a scraper:**
- Click **"Start"** button
- Scraper resumes with current settings

### View Only Certain Platforms

Free users can only use Craigslist & eBay.  
Upgrade to access Facebook & KSL.

### Save Favorite Listings

1. Click ⭐ star icon on listing
2. Add notes if desired
3. View all favorites in **Favorites** page
4. Remove with ⭐ icon again

### Export Your Data

1. Go to **Profile** page
2. Click **"Export All Data"**
3. Download JSON file with all your data
4. Includes favorites, searches, alerts

---

## ❓ Frequently Asked Questions

### How often does it check?

Depends on your subscription:
- Free: Every 10 minutes
- Standard: Every 5 minutes
- Pro: Every 60 seconds

### Will I miss any listings?

Super-Bot checks consistently, but:
- Very short-lived listings might disappear
- Multiple searches happening simultaneously
- Bot checks as fast as your tier allows

### Can I search multiple locations?

Currently one location per account.  
Pro tip: Use broad location + large radius

### How many items will it find?

Depends on:
- How popular your keywords are
- Your price range
- Your location
- Time of day

Typical: 10-50 new listings per day

### Can I use it on my phone?

Yes! The website is mobile-friendly.  
Access from any browser on phone/tablet.

### Is my data private?

Yes! See [Privacy Policy] and [Security](../development/security.md).
- Your searches are private
- Data is encrypted
- No selling of personal info

---

## 🐛 Troubleshooting

### No Listings Appearing

**Check:**
- Scrapers are started (green status)
- Keywords are not too specific
- Price range is reasonable
- Location is correct

**Try:**
- Broader keywords
- Wider price range
- Wait 5-10 minutes for first results

### Scraper Won't Start

**Possible causes:**
- Internet connection issue
- Platform is down temporarily
- Reached platform access limit

**Solution:**
- Wait a few minutes and try again
- Check other platforms work
- Contact support if persists

### Too Many Results

**Refine your search:**
- More specific keywords
- Narrower price range
- Smaller radius
- Use exclude words (Pro feature)

### Not Enough Results

**Broaden your search:**
- More generic keywords
- Wider price range
- Larger radius
- Multiple similar keywords

---

## 🆘 Getting Help

### Documentation

- **Features Guide**: [features.md](features.md)
- **Subscription Info**: [subscriptions.md](subscriptions.md)
- **FAQ**: Common questions answered

### Support

- **Email**: support@example.com
- **Discord**: Community chat
- **GitHub**: Report bugs
- **Twitter**: @SuperBotApp

### Quick Links

- [Report a Bug](https://github.com/your-repo/issues)
- [Request a Feature](https://github.com/your-repo/issues)
- [View Changelog](https://github.com/your-repo/releases)

---

## 🎉 Success Stories

> "Found my dream car in 2 days! Super-Bot saved me weeks of searching."  
> — Sarah M., Pro User

> "Set it up in 5 minutes, found a $200 deal on a TV that same day."  
> — Mike R., Standard User

> "The analytics helped me understand the perfect time to buy. Saved $500!"  
> — Jennifer L., Pro User

---

## 🚀 Next Steps

Now that you're set up:

1. **Start searching** - Let the bot work for you
2. **Refine settings** - Adjust based on results
3. **Save favorites** - Track items you like
4. **Upgrade if needed** - Get more features
5. **Share with friends** - Help others find deals too!

---

**Happy deal hunting!** 🎯

Found something great? Share your success story with us!

