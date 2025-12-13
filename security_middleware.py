"""
Security Middleware for blocking malicious requests and protecting against common attacks
"""
import re
import time
import threading
from datetime import datetime, timedelta
from flask import request, jsonify, abort
from collections import defaultdict, deque
from queue import Queue
from utils import logger, get_client_ip
import db_enhanced

# Track request start time
_REQUEST_START_TIME = {}

# Async logging queue to prevent blocking
_security_log_queue = Queue(maxsize=1000)
_security_logger_thread = None
_security_logger_running = False

def _security_logger_worker():
    """Background thread that processes security log events from queue"""
    global _security_logger_running
    logger.info("Security logger worker started")
    
    while _security_logger_running:
        try:
            # Wait for events with timeout to allow clean shutdown
            event_data = _security_log_queue.get(timeout=1)
            
            # Try to log to database with limited retries
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    db_enhanced.log_security_event(
                        ip=event_data['ip'],
                        path=event_data['path'],
                        user_agent=event_data['user_agent'],
                        reason=event_data['reason'],
                        timestamp=event_data['timestamp']
                    )
                    break  # Success
                except Exception as e:
                    if attempt < max_retries - 1:
                        time.sleep(0.1 * (2 ** attempt))  # Exponential backoff
                    else:
                        # Failed all retries, log to file
                        logger.warning(
                            f"Failed to log security event after {max_retries} attempts: "
                            f"IP={event_data['ip']}, Path={event_data['path']}, Reason={event_data['reason']}"
                        )
            
            _security_log_queue.task_done()
            
        except Exception as e:
            # Queue timeout or other error, continue loop
            if str(e) != "":  # Only log non-timeout errors
                pass
    
    logger.info("Security logger worker stopped")

def start_security_logger():
    """Start the background security logger thread"""
    global _security_logger_thread, _security_logger_running
    
    if _security_logger_running:
        return  # Already running
    
    _security_logger_running = True
    _security_logger_thread = threading.Thread(target=_security_logger_worker, daemon=True)
    _security_logger_thread.start()
    logger.info("Security logger background thread started")

def stop_security_logger():
    """Stop the background security logger thread"""
    global _security_logger_running
    
    if not _security_logger_running:
        return
    
    _security_logger_running = False
    if _security_logger_thread:
        _security_logger_thread.join(timeout=5)
    logger.info("Security logger background thread stopped")

# Quick pattern matching for known malicious requests - compiled for performance
MALICIOUS_PATTERNS = [
    re.compile(r'/lander/', re.IGNORECASE),
    re.compile(r'index\.php', re.IGNORECASE),
    re.compile(r'\.php', re.IGNORECASE),
    re.compile(r'wp-', re.IGNORECASE),
    re.compile(r'administrator', re.IGNORECASE),
    re.compile(r'admin\.php', re.IGNORECASE),
    re.compile(r'\.sql', re.IGNORECASE),
    re.compile(r'\.env', re.IGNORECASE),
]

def _is_quick_reject_path(path):
    """Quick check for paths that should be rejected immediately - no DB access."""
    if not path:
        return True
    
    # Check against known malicious patterns (compiled regex for performance)
    for pattern in MALICIOUS_PATTERNS:
        if pattern.search(path):
            return True
    
    return False

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
            
            # Admin and management interfaces (excluding legitimate /admin routes)
            r'/(wp-admin|phpmyadmin|adminer)/',
            r'/(wp-config|server_info|server-info)$',
            r'/administrator/',  # Moved from MALICIOUS_PATTERNS for more precise matching
            
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
        
        # Rate limiting thresholds - tightened for better security
        self.max_requests_per_minute = 60  # More reasonable for normal users
        self.max_suspicious_requests = 3   # Reduced from 5 - block faster
        self.block_duration_minutes = 60   # Increased from 30 - longer blocks
        
        # Additional security thresholds
        self.max_requests_per_second = 10  # Allow higher burst for normal usage
        self.suspicious_ip_block_threshold = 2  # Reduced from 3 - block after 2 suspicious requests
        self.rapid_fire_threshold = 15  # Reduced from 20 - be more sensitive to DDoS
        
        # Track failed requests for fail2ban-like behavior
        self.failed_requests = defaultdict(lambda: deque())  # Changed to deque to track timestamps
        self.failed_request_threshold = 20  # Block after 20 failed requests in window (more forgiving)
        self.failed_request_window = 300  # 5 minute window for tracking failed requests
        
        # Track 404s separately for faster blocking of scanners
        self.not_found_requests = defaultdict(lambda: deque())
        self.not_found_threshold = 20  # Block after 20 404s in window (scanners hit way more)
        self.not_found_window = 60  # 1 minute window - scanners hit this fast
        
        # Admin rate limiting thresholds (higher but still present for security)
        self.admin_max_requests_per_minute = 300  # 5x normal user limit
        self.admin_max_requests_per_second = 50   # 5x normal user limit
        self.admin_rapid_fire_threshold = 100     # Much higher for admin operations
        
        # Track admin activity for security auditing
        self.admin_activity = defaultdict(lambda: deque())
        
    def is_suspicious_request(self, path):
        """Check if the request path matches suspicious patterns"""
        for pattern in self.compiled_patterns:
            if pattern.search(path):
                return True
        return False
    
    def is_malicious_user_agent(self, user_agent):
        """Check for suspicious user agents"""
        if not user_agent:
            return False  # Don't block if no user agent
            
        # Block known bot and scanner patterns
        malicious_agents = [
            'sqlmap', 'nikto', 'nmap', 'masscan', 'zap', 'burp',
            'acunetix', 'nessus', 'openvas', 'metasploit',
            'xsser', 'backtrack', 'kaeli',
            # Known scanner bots
            'ahrefsbot', 'semrushbot', 'dotbot', 'mj12bot',
            'blexbot', 'screaming frog', 'sitebulb', 'nerdybot'
        ]
        
        user_agent_lower = user_agent.lower()
        
        # Detect fake/outdated Chrome versions (common in bot attacks)
        # Chrome 94 is from 2021 - suspicious if still in use in 2025
        fake_browser_patterns = [
            r'chrome/9[0-4]\.',  # Chrome 90-94 (very outdated)
            r'chrome/8[0-9]\.',  # Chrome 80-89 (ancient)
            r'chrome/7[0-9]\.',  # Chrome 70-79 (ancient)
        ]
        
        for pattern in fake_browser_patterns:
            if re.search(pattern, user_agent_lower):
                # Check if this is likely a bot by looking at the full pattern
                # Real browsers from 2025 should be Chrome 120+
                logger.warning(f"Detected suspicious outdated browser version: {user_agent}")
                return True
        
        # Don't block legitimate modern browsers or tools that might be used legitimately
        allowed_patterns = [
            'googlebot', 'bingbot', 'slurp', 'duckduckbot',
            'baiduspider', 'yandexbot', 'facebookexternalhit',
            'go-http-client',  # Some legitimate Go clients
            'python-requests',  # May be used for API calls
            'postman',  # API testing tools
            'botifex'  # Your own bot
        ]
        
        # Check if it's a legitimate bot/tool
        if any(pattern in user_agent_lower for pattern in allowed_patterns):
            return False
        
        # Only block if it's clearly malicious
        return any(agent in user_agent_lower for agent in malicious_agents)
    
    def is_suspicious_ip_range(self, ip):
        """Check if IP is from a known suspicious range"""
        if not ip:
            return False
        
        # Known hosting/VPS ranges commonly used by bots
        # These are not home/business IPs
        suspicious_ranges = [
            '45.90.',      # DataCamp Limited - often used for scanning
            '89.104.',     # M247 Europe - frequently used for bots
            '176.53.',     # M247 Europe - frequently used for bots  
            '154.220.',    # Prager IT - known for bot traffic
            '156.248.',    # Unknown - scanner activity
            '198.64.198.', # Specific scanner IP range
        ]
        
        for range_prefix in suspicious_ranges:
            if ip.startswith(range_prefix):
                return True
        
        return False
    
    def track_ip_activity(self, ip, is_admin=False):
        """Track IP activity for rate limiting with multiple thresholds"""
        now = time.time()
        minute_ago = now - 60
        second_ago = now - 1
        ten_seconds_ago = now - 10
        
        # Use admin-specific tracking if admin user
        if is_admin:
            # Track admin activity separately for auditing
            while self.admin_activity[ip] and self.admin_activity[ip][0] < minute_ago:
                self.admin_activity[ip].popleft()
            self.admin_activity[ip].append(now)
            
            # Apply admin-specific (higher) rate limits
            recent_requests = [req for req in self.admin_activity[ip] if req > ten_seconds_ago]
            if len(recent_requests) > self.admin_rapid_fire_threshold:
                logger.warning(f"Admin IP {ip} exceeded rapid-fire threshold: {len(recent_requests)} in 10 seconds")
                return False
            
            second_requests = [req for req in self.admin_activity[ip] if req > second_ago]
            if len(second_requests) > self.admin_max_requests_per_second:
                logger.warning(f"Admin IP {ip} exceeded per-second limit: {len(second_requests)}")
                return False
            
            if len(self.admin_activity[ip]) > self.admin_max_requests_per_minute:
                logger.warning(f"Admin IP {ip} exceeded per-minute limit: {len(self.admin_activity[ip])}")
                return False
            
            return True
        
        # Standard user rate limiting
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
    
    def record_failed_request(self, ip, status_code=None):
        """Record a failed request (404, 403, etc.) for fail2ban-like behavior"""
        now = time.time()
        
        # Track general failed requests
        self.failed_requests[ip].append(now)
        
        # Track 404s separately for faster blocking
        if status_code == 404:
            self.not_found_requests[ip].append(now)
            
            # Clean old 404 entries
            cutoff = now - self.not_found_window
            while self.not_found_requests[ip] and self.not_found_requests[ip][0] < cutoff:
                self.not_found_requests[ip].popleft()
            
            # Check 404 threshold (faster blocking for scanners)
            if len(self.not_found_requests[ip]) >= self.not_found_threshold:
                self.blocked_ips.add(ip)
                logger.warning(f"IP {ip} blocked after {len(self.not_found_requests[ip])} 404s in {self.not_found_window}s")
                return True
        
        # Clean old failed request entries
        cutoff = now - self.failed_request_window
        while self.failed_requests[ip] and self.failed_requests[ip][0] < cutoff:
            self.failed_requests[ip].popleft()
        
        # Block IP if too many failed requests overall
        if len(self.failed_requests[ip]) >= self.failed_request_threshold:
            self.blocked_ips.add(ip)
            logger.warning(f"IP {ip} blocked after {len(self.failed_requests[ip])} failed requests in {self.failed_request_window}s")
            return True
        
        return False
    
    def should_block_request(self, request, is_admin=False):
        """Determine if request should be blocked"""
        ip = get_client_ip(request) or request.remote_addr
        path = request.path
        user_agent = request.headers.get('User-Agent', '')
        
        # Admin users: apply relaxed security but still monitor
        if is_admin:
            # Log admin activity for audit trail
            logger.info(f"Admin access: {ip} -> {path}")
            
            # Allow admins to access admin paths immediately (bypass all checks for admin panel)
            if path.startswith('/admin'):
                logger.debug(f"Admin user accessing admin panel: {path}")
                return False, None
            
            # Still check rate limits for non-admin paths (but with higher thresholds)
            if not self.track_ip_activity(ip, is_admin=True):
                logger.warning(f"Admin IP {ip} exceeded rate limits")
                return True, "Admin rate limit exceeded"
            
            # For non-admin paths, still apply security checks
            # (in case admin account is compromised and being used to attack)
        
        # Check if IP is blocked (applies to both admin and regular users on non-admin paths)
        if self.is_ip_blocked(ip):
            if is_admin:
                logger.critical(f"Admin account on blocked IP {ip} attempted access to {path}")
            return True, "IP blocked for suspicious activity"
        
        # Check if IP is from a suspicious range (known bot networks)
        if self.is_suspicious_ip_range(ip):
            # Don't block immediately, but track more aggressively
            self.suspicious_ips[ip] += 1
            if self.suspicious_ips[ip] >= 5:  # Allow 5 requests from suspicious ranges
                self.blocked_ips.add(ip)
                logger.warning(f"IP {ip} from suspicious range blocked after {self.suspicious_ips[ip]} requests")
                return True, "IP from suspicious network range"
        
        # Check for suspicious file access patterns
        if self.is_suspicious_request(path):
            self.suspicious_ips[ip] += 1
            if is_admin:
                logger.warning(f"Admin account from {ip} attempted suspicious file access: {path}")
            else:
                logger.warning(f"Suspicious file access attempt from {ip}: {path}")
            
            # Block IP immediately for certain high-risk patterns
            high_risk_patterns = [
                r'\.env', r'phpinfo', r'server-info', r'wp-config',
                r'_profiler', r'config\.js', r'aws-secret',
                r'index\.php', r'lander.*\.php', r'database\.php'
            ]
            
            is_high_risk = any(re.search(pattern, path, re.IGNORECASE) for pattern in high_risk_patterns)
            
            # Block immediately for high-risk patterns or after threshold
            if is_high_risk or self.suspicious_ips[ip] >= self.suspicious_ip_block_threshold:
                self.blocked_ips.add(ip)
                if is_admin:
                    logger.critical(f"Admin IP {ip} blocked for suspicious file access: {path}")
                else:
                    logger.warning(f"IP {ip} blocked for suspicious file access: {path} (high_risk={is_high_risk}, count={self.suspicious_ips[ip]})")
                return True, "IP blocked for suspicious file access attempts"
            
            return True, "Suspicious file access blocked"
        
        # Check for malicious user agents (skip for admin on legitimate paths)
        if not is_admin and self.is_malicious_user_agent(user_agent):
            logger.warning(f"Malicious user agent from {ip}: {user_agent}")
            self.blocked_ips.add(ip)
            return True, "Malicious user agent detected"
        
        # Track IP activity with appropriate thresholds
        if not self.track_ip_activity(ip, is_admin=is_admin):
            return True, "Rate limit exceeded"
        
        return False, None
    
    def log_security_event(self, ip, path, user_agent, reason):
        """Log security events to database asynchronously to prevent blocking"""
        try:
            # Add to queue for async processing (non-blocking)
            event_data = {
                'ip': ip,
                'path': path,
                'user_agent': user_agent,
                'reason': reason,
                'timestamp': datetime.now()
            }
            
            # Try to add to queue without blocking
            try:
                _security_log_queue.put_nowait(event_data)
            except Exception:
                # Queue is full, log to file instead
                logger.warning(f"Security log queue full. Event: IP={ip}, Path={path}, Reason={reason}")
        except Exception as e:
            # Don't let logging errors block the request
            logger.error(f"Error queuing security event: {e}")
    
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
        
        # Clean up failed requests tracking
        failed_cutoff = now - self.failed_request_window
        for ip in list(self.failed_requests.keys()):
            while self.failed_requests[ip] and self.failed_requests[ip][0] < failed_cutoff:
                self.failed_requests[ip].popleft()
            
            if not self.failed_requests[ip]:
                del self.failed_requests[ip]
        
        # Clean up 404 tracking
        not_found_cutoff = now - self.not_found_window
        for ip in list(self.not_found_requests.keys()):
            while self.not_found_requests[ip] and self.not_found_requests[ip][0] < not_found_cutoff:
                self.not_found_requests[ip].popleft()
            
            if not self.not_found_requests[ip]:
                del self.not_found_requests[ip]
        
        # Remove old blocked IPs (let them try again after block duration)
        self.blocked_ips.clear()
        self.suspicious_ips.clear()

# Global security middleware instance
security_middleware = SecurityMiddleware()

# Start the async security logger
start_security_logger()

def security_before_request():
    """Flask before_request handler for security"""
    # CRITICAL: Check if we're inside a Stripe operation to prevent recursion
    # Import here to avoid circular dependencies
    try:
        from subscriptions import _stripe_operation_lock
        if getattr(_stripe_operation_lock, 'in_stripe_call', False):
            # Skip all security checks during Stripe operations to prevent recursion
            return None
    except Exception:
        # If we can't check, proceed normally
        pass
    
    # CRITICAL: Check if we're inside a scraper operation to prevent recursion
    try:
        from scrapers.craigslist import _recursion_guard as cl_guard
        from scrapers.ebay import _recursion_guard as ebay_guard
        from scrapers.facebook import _recursion_guard as fb_guard
        from scrapers.ksl import _recursion_guard as ksl_guard
        from scrapers.mercari import _recursion_guard as mercari_guard
        from scrapers.poshmark import _recursion_guard as poshmark_guard
        
        if (getattr(cl_guard, 'in_scraper', False) or 
            getattr(ebay_guard, 'in_scraper', False) or
            getattr(fb_guard, 'in_scraper', False) or
            getattr(ksl_guard, 'in_scraper', False) or
            getattr(mercari_guard, 'in_scraper', False) or
            getattr(poshmark_guard, 'in_scraper', False)):
            # Skip all security checks during scraper operations to prevent recursion
            return None
    except Exception:
        # If we can't check, proceed normally
        pass
    
    # Early rejection for obviously malicious paths - no DB access
    if _is_quick_reject_path(request.path):
        # Log and block immediately without database access
        logger.warning(f"Quick reject: malicious path from {get_client_ip(request) or request.remote_addr}: {request.path}")
        return jsonify({'error': 'Access Denied', 'message': 'Request blocked by security policy', 'code': 403}), 403
    
    # Skip security check for static files
    if request.path.startswith('/static/'):
        return None
    
    # Check if user is an authenticated admin EARLY
    is_admin = False
    try:
        from flask_login import current_user
        if current_user and current_user.is_authenticated:
            if hasattr(current_user, 'role') and current_user.role == 'admin':
                is_admin = True
                logger.debug(f"Admin user detected: {current_user.id}")
    except Exception as e:
        # If there's an error checking user status, continue with security checks as regular user
        logger.debug(f"Error checking admin status in security middleware: {e}")
    
    # Allow admins to access admin panel without any security checks
    if is_admin and request.path.startswith('/admin'):
        logger.debug(f"Admin {current_user.id} accessing admin panel: {request.path}")
        return None
    
    # Skip security check for basic public routes that users need to access
    allowed_paths = [
        '/',
        '/login',
        '/register',
        '/register/',
        '/landing',
        '/favicon.ico',
        '/robots.txt',
        '/health',
        '/api/health'
    ]
    
    if request.path in allowed_paths:
        return None
    
    # Clean up old data periodically - more frequent cleanup
    if hasattr(security_middleware, '_last_cleanup'):
        if time.time() - security_middleware._last_cleanup > 60:  # Every 1 minute instead of 5
            security_middleware.cleanup_old_data()
            security_middleware._last_cleanup = time.time()
    else:
        security_middleware._last_cleanup = time.time()
    
    # Check if request should be blocked (with admin flag for relaxed limits)
    should_block, reason = security_middleware.should_block_request(request, is_admin=is_admin)
    
    if should_block:
        # Log the security event (including admin attempts for audit)
        security_middleware.log_security_event(
            ip=get_client_ip(request) or request.remote_addr,
            path=request.path,
            user_agent=request.headers.get('User-Agent', ''),
            reason=f"{'[ADMIN] ' if is_admin else ''}{reason}"
        )
        
        # Return 403 Forbidden
        return jsonify({
            'error': 'Access Denied',
            'message': 'Request blocked by security policy',
            'code': 403
        }), 403

def security_after_request(response):
    """Flask after_request handler for security - tracks failed requests"""
    # Track failed requests (404s and other errors) to block scanning bots
    if response.status_code in [403, 404, 500]:
        try:
            ip = get_client_ip(request) or request.remote_addr
            
            # Check if this is an admin user - don't penalize admins for 404s
            is_admin = False
            try:
                from flask_login import current_user
                if current_user and current_user.is_authenticated:
                    if hasattr(current_user, 'role') and current_user.role == 'admin':
                        is_admin = True
            except Exception:
                pass
            
            # Only track failed requests for non-admin users or for admin on non-admin paths
            if not is_admin or (is_admin and not request.path.startswith('/admin')):
                # Record the failed request
                was_blocked = security_middleware.record_failed_request(ip, status_code=response.status_code)
                
                if was_blocked:
                    # Log the block event
                    security_middleware.log_security_event(
                        ip=ip,
                        path=request.path,
                        user_agent=request.headers.get('User-Agent', ''),
                        reason=f"Too many {response.status_code} responses - automated blocking"
                    )
        except Exception as e:
            # Don't let tracking errors break the response
            logger.error(f"Error tracking failed request: {e}")
    
    # Add security headers
    return add_security_headers(response)

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
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "img-src 'self' data: https:; "
        "font-src 'self' data: https://fonts.gstatic.com; "
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
        'failed_request_ips': len(security_middleware.failed_requests),
        'not_found_tracked_ips': len(security_middleware.not_found_requests),
        'admin_active_ips': len(security_middleware.admin_activity),
        'blocked_ips_list': list(security_middleware.blocked_ips),
        'suspicious_ips_list': dict(security_middleware.suspicious_ips),
        'admin_activity_ips': list(security_middleware.admin_activity.keys()),
        'top_404_ips': sorted(
            [(ip, len(requests)) for ip, requests in security_middleware.not_found_requests.items()],
            key=lambda x: x[1],
            reverse=True
        )[:10]  # Top 10 IPs by 404 count
    }
