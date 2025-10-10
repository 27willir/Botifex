#!/usr/bin/env python3
"""
Helper script to set up your .env file for Stripe integration
Run this after you have your Stripe credentials ready
"""

import os
import sys

def create_env_file():
    """Create .env file with prompts for Stripe credentials"""
    
    print("=" * 60)
    print("🚀 Super-Bot Stripe Setup Helper")
    print("=" * 60)
    print()
    print("This will help you create your .env file with Stripe credentials.")
    print("If you don't have them yet, see STRIPE_SETUP_GUIDE.md")
    print()
    
    # Check if .env already exists
    if os.path.exists('.env'):
        response = input("⚠️  .env file already exists. Overwrite? (yes/no): ")
        if response.lower() not in ['yes', 'y']:
            print("Cancelled. Edit .env manually or delete it first.")
            return
    
    # Copy from template
    template_path = 'docs/env_example.txt'
    if not os.path.exists(template_path):
        print(f"❌ Error: {template_path} not found!")
        return
    
    print("\n" + "=" * 60)
    print("📝 Enter Your Stripe Credentials")
    print("=" * 60)
    print("Leave blank to skip (you can fill in later)")
    print()
    
    # Get Stripe credentials
    stripe_secret = input("STRIPE_SECRET_KEY (sk_test_...): ").strip()
    stripe_public = input("STRIPE_PUBLISHABLE_KEY (pk_test_...): ").strip()
    stripe_webhook = input("STRIPE_WEBHOOK_SECRET (whsec_...): ").strip()
    stripe_standard_price = input("STRIPE_STANDARD_PRICE_ID (price_...): ").strip()
    stripe_pro_price = input("STRIPE_PRO_PRICE_ID (price_...): ").strip()
    
    # Read template
    with open(template_path, 'r') as f:
        content = f.read()
    
    # Replace values if provided
    if stripe_secret:
        content = content.replace('sk_test_your-stripe-secret-key-here', stripe_secret)
    if stripe_public:
        content = content.replace('pk_test_your-stripe-publishable-key-here', stripe_public)
    if stripe_webhook:
        content = content.replace('whsec_your-webhook-secret-here', stripe_webhook)
    if stripe_standard_price:
        content = content.replace('price_your-standard-price-id', stripe_standard_price)
    if stripe_pro_price:
        content = content.replace('price_your-pro-price-id', stripe_pro_price)
    
    # Write .env file
    with open('.env', 'w') as f:
        f.write(content)
    
    print()
    print("=" * 60)
    print("✅ Success! .env file created")
    print("=" * 60)
    print()
    print("Next steps:")
    print("1. Review .env file and update any other settings")
    print("2. Make sure all 5 Stripe values are filled in")
    print("3. Run: python app.py")
    print("4. Test subscription at http://localhost:5000")
    print()
    print("📖 Full guide: STRIPE_SETUP_GUIDE.md")
    print()

if __name__ == '__main__':
    try:
        create_env_file()
    except KeyboardInterrupt:
        print("\n\nCancelled by user.")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)

