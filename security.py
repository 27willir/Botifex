"""
Security utilities for the Super Bot application
"""
import os
import re
import secrets
from datetime import timedelta
from flask import session
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables
load_dotenv()

class SecurityConfig:
    """Security configuration and utilities"""
    
    # Password requirements
    MIN_PASSWORD_LENGTH = int(os.getenv('MIN_PASSWORD_LENGTH', '8'))
    REQUIRE_SPECIAL_CHARS = os.getenv('REQUIRE_SPECIAL_CHARS', 'True').lower() == 'true'
    REQUIRE_NUMBERS = os.getenv('REQUIRE_NUMBERS', 'True').lower() == 'true'
    REQUIRE_UPPERCASE = os.getenv('REQUIRE_UPPERCASE', 'True').lower() == 'true'
    
    # Session configuration
    PERMANENT_SESSION_LIFETIME = timedelta(seconds=int(os.getenv('PERMANENT_SESSION_LIFETIME', '3600')))
    
    @staticmethod
    def generate_secret_key():
        """Generate a secure secret key"""
        return secrets.token_urlsafe(32)
    
    @staticmethod
    def get_secret_key():
        """Get secret key from environment or generate and persist a new one"""
        secret_key = os.getenv('SECRET_KEY')
        if not secret_key or secret_key == 'your-super-secret-key-here-change-this-in-production':
            # Generate a new secret key if not set or using default
            secret_key = SecurityConfig.generate_secret_key()
            
            # Try to persist the key to .env file
            env_file = Path('.env')
            try:
                if env_file.exists():
                    # Read existing .env content
                    env_content = env_file.read_text()
                    # Replace or append SECRET_KEY
                    if 'SECRET_KEY=' in env_content:
                        # Replace existing SECRET_KEY
                        import re
                        env_content = re.sub(
                            r'SECRET_KEY=.*',
                            f'SECRET_KEY={secret_key}',
                            env_content
                        )
                    else:
                        # Append new SECRET_KEY
                        if not env_content.endswith('\n'):
                            env_content += '\n'
                        env_content += f'SECRET_KEY={secret_key}\n'
                    env_file.write_text(env_content)
                    print(f"✅ Generated and saved new SECRET_KEY to .env file")
                else:
                    # Create new .env file with the secret key
                    env_file.write_text(f'SECRET_KEY={secret_key}\n')
                    print(f"✅ Created .env file with new SECRET_KEY")
            except Exception as e:
                print(f"WARNING: Generated new secret key but couldn't save to .env file: {e}")
                print(f"Please manually add this to your .env file:")
                print(f"SECRET_KEY={secret_key}")
        return secret_key
    
    @staticmethod
    def validate_password(password):
        """
        Validate password strength
        Returns: (is_valid, error_message)
        """
        if len(password) < SecurityConfig.MIN_PASSWORD_LENGTH:
            return False, f"Password must be at least {SecurityConfig.MIN_PASSWORD_LENGTH} characters long"
        
        if SecurityConfig.REQUIRE_UPPERCASE and not re.search(r'[A-Z]', password):
            return False, "Password must contain at least one uppercase letter"
        
        if SecurityConfig.REQUIRE_NUMBERS and not re.search(r'\d', password):
            return False, "Password must contain at least one number"
        
        if SecurityConfig.REQUIRE_SPECIAL_CHARS and not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            return False, "Password must contain at least one special character"
        
        return True, None
    
    @staticmethod
    def hash_password(password):
        """Hash a password securely"""
        return generate_password_hash(password, method='pbkdf2:sha256', salt_length=16)
    
    @staticmethod
    def verify_password(password_hash, password):
        """Verify a password against its hash"""
        return check_password_hash(password_hash, password)
    
    @staticmethod
    def sanitize_input(text):
        """Sanitize user input to prevent XSS"""
        if not text:
            return ""
        # Remove potentially dangerous characters
        text = re.sub(r'[<>"\']', '', text)
        return text.strip()
    
    @staticmethod
    def validate_username(username):
        """Validate username format"""
        if not username:
            return False, "Username is required"
        
        if len(username) < 3:
            return False, "Username must be at least 3 characters long"
        
        if len(username) > 20:
            return False, "Username must be less than 20 characters long"
        
        if not re.match(r'^[a-zA-Z0-9_-]+$', username):
            return False, "Username can only contain letters, numbers, underscores, and hyphens"
        
        return True, None
    
    @staticmethod
    def validate_email(email):
        """Validate email format"""
        if not email:
            return False, "Email is required"
        
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, email):
            return False, "Invalid email format"
        
        return True, None
    
    @staticmethod
    def setup_session_security(app):
        """Configure Flask session security"""
        # Session cookie security
        app.config['SESSION_COOKIE_SECURE'] = os.getenv('SESSION_COOKIE_SECURE', 'False').lower() == 'true'
        app.config['SESSION_COOKIE_HTTPONLY'] = os.getenv('SESSION_COOKIE_HTTPONLY', 'True').lower() == 'true'
        app.config['SESSION_COOKIE_SAMESITE'] = os.getenv('SESSION_COOKIE_SAMESITE', 'Lax')
        app.config['PERMANENT_SESSION_LIFETIME'] = SecurityConfig.PERMANENT_SESSION_LIFETIME
        
        # Additional security headers
        @app.after_request
        def add_security_headers(response):
            response.headers['X-Content-Type-Options'] = 'nosniff'
            response.headers['X-Frame-Options'] = 'DENY'
            response.headers['X-XSS-Protection'] = '1; mode=block'
            return response
