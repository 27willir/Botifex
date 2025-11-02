#!/usr/bin/env python3
"""
Script to complete remaining scraper migrations.
This script will update Mercari, Poshmark, and Facebook scrapers.
"""

import re
import sys

def migrate_scraper(file_path, site_name, base_url, keep_selenium=False):
    """Migrate a scraper to use common utilities."""
    
    print(f"Migrating {site_name}...")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find and remove duplicate helper functions
    functions_to_remove = [
        r'def get_random_user_agent\(\):.*?(?=\ndef\s|\n# =|$)',
        r'def get_realistic_headers\(\):.*?(?=\ndef\s|\n# =|$)',
        r'def initialize_session\(\):.*?(?=\ndef\s|\n# =|$)',
        r'def human_delay\(.*?\):.*?(?=\ndef\s|\n# =|$)',
        r'def normalize_url\(.*?\):.*?(?=\ndef\s|\n# =|$)',
        r'def is_new_listing\(link\):.*?(?=\ndef\s|\n# =|$)',
        r'def save_seen_listings\(.*?\):.*?(?=\ndef\s|\n# =|$)',
        r'def load_seen_listings\(.*?\):.*?(?=\ndef\s|\n# =|$)',
        r'def validate_listing\(.*?\):.*?(?=\ndef\s|\n# =|$)',
        r'def load_settings\(\):.*?(?=\ndef\s|\n# =|$)',
    ]
    
    for pattern in functions_to_remove:
        content = re.sub(pattern, '', content, flags=re.DOTALL)
    
    # Update send_discord_message to include image validation
    old_send = r'''def send_discord_message\(title, link, price=None, image_url=None\):
    """Save listing to database and send notification."""
    try:
        # Validate data before saving
        is_valid, error = validate_listing\(title, link, price\)
        if not is_valid:
            logger.warning\(f"⚠️ Skipping invalid listing: {error}"\)
            return
        
        # Save to database
        save_listing\(title, price, link, image_url, "''' + site_name + '''"\)'''
    
    new_send = f'''def send_discord_message(title, link, price=None, image_url=None):
    """Save listing to database and send notification."""
    try:
        # Validate data before saving
        is_valid, error = validate_listing(title, link, price)
        if not is_valid:
            logger.warning(f"⚠️ Skipping invalid listing: {{error}}")
            return
        
        # Validate image URL if provided
        if image_url and not validate_image_url(image_url):
            logger.debug(f"Invalid/placeholder image URL, setting to None: {{image_url}}")
            image_url = None
        
        # Save to database
        save_listing(title, price, link, image_url, SITE_NAME)'''
    
    content = re.sub(old_send, new_send, content)
    
    # Update recursion guard calls
    content = re.sub(
        r'if getattr\(_recursion_guard, \'in_scraper\', False\):',
        f'if check_recursion_guard(SITE_NAME):',
        content
    )
    content = re.sub(
        r'_recursion_guard\.in_scraper = True',
        f'set_recursion_guard(SITE_NAME, True)',
        content
    )
    content = re.sub(
        r'_recursion_guard\.in_scraper = False',
        f'set_recursion_guard(SITE_NAME, False)',
        content
    )
    
    # Update is_new_listing calls
    content = re.sub(
        r'is_new_listing\(link\)',
        f'is_new_listing(link, seen_listings, SITE_NAME)',
        content
    )
    
    # Update seen_listings lock usage
    content = re.sub(
        r'with _seen_listings_lock:',
        f'lock = get_seen_listings_lock(SITE_NAME)\n        with lock:',
        content
    )
    
    # Update save/load_seen_listings calls
    content = re.sub(
        r'save_seen_listings\(\)',
        f'save_seen_listings(seen_listings, SITE_NAME)',
        content
    )
    content = re.sub(
        r'load_seen_listings\(\)',
        f'seen_listings = load_seen_listings(SITE_NAME)',
        content
    )
    
    # Write back
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"✅ {site_name} migration complete")

if __name__ == '__main__':
    print("Starting scraper migrations...")
    print("=" * 50)
    
    # Note: This script handles the mechanical parts
    # Manual review still recommended for complex cases
    
    print("\nNote: This script provides automated help but manual review")
    print("of the check_X() and run_X_scraper() functions is recommended.")
    print("\nSee IMPLEMENTATION_SUMMARY.md for the complete pattern.")

