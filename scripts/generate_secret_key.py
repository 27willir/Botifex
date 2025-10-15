#!/usr/bin/env python3
"""
Generate a secure SECRET_KEY for Flask application
Usage: python scripts/generate_secret_key.py
"""
import secrets

def generate_secret_key():
    """Generate a cryptographically secure random secret key"""
    return secrets.token_hex(32)

if __name__ == "__main__":
    print("=" * 80)
    print("SECURE SECRET_KEY GENERATOR")
    print("=" * 80)
    print()
    print("Generated SECRET_KEY:")
    print("-" * 80)
    secret_key = generate_secret_key()
    print(secret_key)
    print("-" * 80)
    print()
    print("IMPORTANT:")
    print("1. Copy this key and add it to your Render environment variables")
    print("2. Set it as: SECRET_KEY=" + secret_key)
    print("3. NEVER commit this key to your Git repository")
    print("4. Keep this key secret and secure")
    print()
    print("=" * 80)

