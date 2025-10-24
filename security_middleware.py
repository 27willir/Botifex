"""
Security Middleware for blocking malicious requests and protecting against common attacks
"""
import re
import time
from datetime import datetime, timedelta
from flask import request, jsonify, abort
from collections import defaultdict, deque
from utils import logger
import db_enhanced

class SecurityMiddleware:
    """Advanced security middleware to block malicious requests"""
    
    def __init__(self):
        # Suspicious file patterns that attackers commonly try to access
        self.suspicious_patterns = [
            # Environment and config files
            r'\.(env|bak|backup|old|tmp|temp)$',
            r'\.(env\.local|\.env\.production|\.env\.staging|\.env\.development)$',
            r'\.(env\.backup|\.env\.old|\.env\.sample|\.env\.example)$',
            
            # Version control and development files
            r'\.(git|svn|hg)$',
            r'/(\.git|\.svn|\.hg)/',
            r'/(\.vscode|\.idea)/',
            
            # Database and data files
            r'\.(sql|db|database)$',
            r'\.(log|logs)$',
            
            # Configuration files
            r'\.(ini|conf|config)$',
            r'/(config|database|backup|conf)/',
            r'/(composer\.json|package\.json|requirements\.txt)$',
            r'/(docker-compose\.yml|Dockerfile)$',
            r'/(web\.config|\.htaccess)$',
            r'/(settings\.php|config\.js)$',
            
            # Server-side scripts
            r'\.(php|asp|jsp)$',
            r'/(phpinfo|info\.php|test\.php|server-info)$',
            r'/(_profiler|_phpinfo|phpinfo\.php)$',
            
            # Data and config files
            r'\.(xml|yml|yaml|json)$',
            r'/(aws-secret\.yaml|config\.env)$',
            
            # Scripts and executables
            r'\.(sh|bat|cmd|ps1)$',
            
            # Security and certificates
            r'\.(key|pem|crt|cert)$',
            r'\.(htaccess|htpasswd)$',
            r'/(\.aws/credentials)$',
            
            # Admin and management interfaces
            r'/(admin|wp-admin|phpmyadmin|adminer)/',
            r'/(wp-config|server_info|server-info)$',
            
            # Common attack targets
            r'/(xampp|laravel|laravel/core|laravel/info\.php)$',
            r'/(lara/phpinfo|lara/info\.php)$',
            r'/(dashboard/phpinfo|admin/server_info)$',
            r'/(secured/phpinfo|server-info\.php)$',
            
            # Node.js and development files
            r'/(node_modules|node/\.env_example)$',
            r'/(scripts/nodemailer\.js)$',
            
            # Application-specific paths
            r'/(app|new|dev|prod|staging|development|backend|frontend)/',
            r'/(website|site|public|main|core|local|apps|application|web)/',
            r'/(crm|kyc|mail|mailer|nginx|docker)/',
            r'/(api/shared|api/config|api/shared/config)/',
            r'/(service/email_service\.py)$',
            
            # Static files that shouldn't be accessible
            r'/(static/js/main\.|static/js/2\.|static/js/.*\.chunk\.js)$',
            
            # Backup and old files
            r'/(env\.backup|env\.old|env\.sample|env\.prod)$',
            r'/(\.env\.production\.local|\.env\.stage)$'
        ]
        
        # Compile patterns for better performance
        self.compiled_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in self.suspicious_patterns]
        
        # IP tracking for rate limiting and blocking
        self.ip_requests = defaultdict(lambda: deque())
        self.blocked_ips = set()
        self.suspicious_ips = defaultdict(int)
        
        # Rate limiting thresholds - more aggressive for security
        self.max_requests_per_minute = 20  # Reduced from 30
        self.max_suspicious_requests = 3   # Reduced from 5
        self.block_duration_minutes = 120  # Increased from 60
        
        # Additional security thresholds
        self.max_requests_per_second = 5   # New: limit per second
        self.suspicious_ip_block_threshold = 2  # Block after 2 suspicious requests
        self.rapid_fire_threshold = 10  # Block if 10+ requests in 10 seconds
        
    def is_suspicious_request(self, path):
        """Check if the request path matches suspicious patterns"""
        for pattern in self.compiled_patterns:
            if pattern.search(path):
                return True
        return False
    
    def is_malicious_user_agent(self, user_agent):
        """Check for suspicious user agents"""
        if not user_agent:
            return True
            
        suspicious_agents = [
            'sqlmap', 'nikto', 'nmap', 'masscan', 'zap', 'burp',
            'scanner', 'bot', 'crawler', 'spider', 'harvester',
            'python-requests', 'curl', 'wget', 'httpie', 'postman',
            'go-http-client', 'java', 'perl', 'ruby', 'php'
        ]
        
        user_agent_lower = user_agent.lower()
        return any(agent in user_agent_lower for agent in suspicious_agents)
    
    def track_ip_activity(self, ip):
        """Track IP activity for rate limiting with multiple thresholds"""
        now = time.time()
        minute_ago = now - 60
        second_ago = now - 1
        ten_seconds_ago = now - 10
        
        # Clean old requests
        while self.ip_requests[ip] and self.ip_requests[ip][0] < minute_ago:
            self.ip_requests[ip].popleft()
        
        # Add current request
        self.ip_requests[ip].append(now)
        
        # Check rapid-fire requests (10+ in 10 seconds)
        recent_requests = [req for req in self.ip_requests[ip] if req > ten_seconds_ago]
        if len(recent_requests) > self.rapid_fire_threshold:
            self.blocked_ips.add(ip)
            logger.warning(f"IP {ip} blocked for rapid-fire requests: {len(recent_requests)} in 10 seconds")
            return False
        
        # Check per-second rate limit
        second_requests = [req for req in self.ip_requests[ip] if req > second_ago]
        if len(second_requests) > self.max_requests_per_second:
            self.blocked_ips.add(ip)
            logger.warning(f"IP {ip} blocked for excessive per-second requests: {len(second_requests)}")
            return False
        
        # Check per-minute rate limit
        if len(self.ip_requests[ip]) > self.max_requests_per_minute:
            self.blocked_ips.add(ip)
            logger.warning(f"IP {ip} blocked for excessive requests: {len(self.ip_requests[ip])} in last minute")
            return False
        
        return True
    
    def is_ip_blocked(self, ip):
        """Check if IP is currently blocked"""
        return ip in self.blocked_ips
    
    def should_block_request(self, request):
        """Determine if request should be blocked"""
        ip = request.remote_addr
        path = request.path
        user_agent = request.headers.get('User-Agent', '')
        
        # Check if IP is blocked
        if self.is_ip_blocked(ip):
            return True, "IP blocked for suspicious activity"
        
        # Check for suspicious file access patterns
        if self.is_suspicious_request(path):
            self.suspicious_ips[ip] += 1
            logger.warning(f"Suspicious file access attempt from {ip}: {path}")
            
            # Block IP immediately for certain high-risk patterns
            high_risk_patterns = [
                r'\.env', r'phpinfo', r'server-info', r'wp-config',
                r'_profiler', r'admin', r'config\.js', r'aws-secret'
            ]
            
            is_high_risk = any(re.search(pattern, path, re.IGNORECASE) for pattern in high_risk_patterns)
            
            # Block immediately for high-risk patterns or after threshold
            if is_high_risk or self.suspicious_ips[ip] >= self.suspicious_ip_block_threshold:
                self.blocked_ips.add(ip)
                logger.warning(f"IP {ip} blocked for suspicious file access: {path} (high_risk={is_high_risk}, count={self.suspicious_ips[ip]})")
                return True, "IP blocked for suspicious file access attempts"
            
            return True, "Suspicious file access blocked"
        
        # Check for malicious user agents
        if self.is_malicious_user_agent(user_agent):
            logger.warning(f"Malicious user agent from {ip}: {user_agent}")
            return True, "Malicious user agent detected"
        
        # Track IP activity
        if not self.track_ip_activity(ip):
            return True, "Rate limit exceeded"
        
        return False, None
    
    def log_security_event(self, ip, path, user_agent, reason):
        """Log security events to database with retry logic"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                db_enhanced.log_security_event(
                    ip=ip,
                    path=path,
                    user_agent=user_agent,
                    reason=reason,
                    timestamp=datetime.now()
                )
                return  # Success, exit retry loop
            except Exception as e:
                if "database is locked" in str(e).lower() and attempt < max_retries - 1:
                    # Wait briefly before retry
                    import time
                    time.sleep(0.1 * (attempt + 1))  # Exponential backoff
                    continue
                else:
                    logger.error(f"Failed to log security event after {attempt + 1} attempts: {e}")
                    # Log to file as fallback
                    logger.warning(f"Security event (fallback): IP={ip}, Path={path}, Reason={reason}")
                    break
    
    def cleanup_old_data(self):
        """Clean up old tracking data"""
        now = time.time()
        cutoff = now - (self.block_duration_minutes * 60)
        
        # Remove old IP requests
        for ip in list(self.ip_requests.keys()):
            while self.ip_requests[ip] and self.ip_requests[ip][0] < cutoff:
                self.ip_requests[ip].popleft()
            
            if not self.ip_requests[ip]:
                del self.ip_requests[ip]
        
        # Remove old blocked IPs
        self.blocked_ips.clear()
        self.suspicious_ips.clear()

# Global security middleware instance
security_middleware = SecurityMiddleware()

def security_before_request():
    """Flask before_request handler for security"""
    # Clean up old data periodically
    if hasattr(security_middleware, '_last_cleanup'):
        if time.time() - security_middleware._last_cleanup > 300:  # 5 minutes
            security_middleware.cleanup_old_data()
            security_middleware._last_cleanup = time.time()
    else:
        security_middleware._last_cleanup = time.time()
    
    # Check if request should be blocked
    should_block, reason = security_middleware.should_block_request(request)
    
    if should_block:
        # Log the security event
        security_middleware.log_security_event(
            ip=request.remote_addr,
            path=request.path,
            user_agent=request.headers.get('User-Agent', ''),
            reason=reason
        )
        
        # Return 403 Forbidden
        return jsonify({
            'error': 'Access Denied',
            'message': 'Request blocked by security policy',
            'code': 403
        }), 403

def add_security_headers(response):
    """Add comprehensive security headers"""
    # Prevent MIME type sniffing
    response.headers['X-Content-Type-Options'] = 'nosniff'
    
    # Prevent clickjacking
    response.headers['X-Frame-Options'] = 'DENY'
    
    # XSS protection
    response.headers['X-XSS-Protection'] = '1; mode=block'
    
    # Content Security Policy
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "font-src 'self' data:; "
        "connect-src 'self' wss: ws:; "
        "frame-ancestors 'none';"
    )
    
    # Referrer Policy
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    
    # Permissions Policy
    response.headers['Permissions-Policy'] = (
        "geolocation=(), "
        "microphone=(), "
        "camera=(), "
        "payment=(), "
        "usb=(), "
        "magnetometer=(), "
        "gyroscope=(), "
        "speaker=()"
    )
    
    # Remove server information
    if 'Server' in response.headers:
        del response.headers['Server']
    
    return response

def get_security_stats():
    """Get current security statistics"""
    return {
        'blocked_ips': len(security_middleware.blocked_ips),
        'suspicious_ips': len(security_middleware.suspicious_ips),
        'tracked_ips': len(security_middleware.ip_requests),
        'blocked_ips_list': list(security_middleware.blocked_ips),
        'suspicious_ips_list': dict(security_middleware.suspicious_ips)
    }
