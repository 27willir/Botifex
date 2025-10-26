[1mdiff --git a/gunicorn_config.py b/gunicorn_config.py[m
[1mindex e99bf12..5f15510 100644[m
[1m--- a/gunicorn_config.py[m
[1m+++ b/gunicorn_config.py[m
[36m@@ -12,10 +12,10 @@[m [mworkers = int(os.getenv('WEB_CONCURRENCY', multiprocessing.cpu_count() * 2 + 1))[m
 worker_class = os.getenv('GUNICORN_WORKER_CLASS', 'gevent')  # gevent, sync, or eventlet[m
 worker_connections = 1000[m
 [m
[31m-# Timeout settings - increased to prevent legitimate request timeouts[m
[31m-timeout = 180  # Increased from 120 to handle resource-intensive operations[m
[31m-graceful_timeout = 45  # Allow workers time to finish current requests[m
[31m-keepalive = 10  # Increased from 5 for better connection reuse[m
[32m+[m[32m# Timeout settings - optimized for production stability[m
[32m+[m[32mtimeout = 30  # Reduced timeout to fail fast on malicious/blocked requests[m
[32m+[m[32mgraceful_timeout = 15  # Allow workers time to finish current requests[m
[32m+[m[32mkeepalive = 5  # Reduced for faster connection recycling[m
 [m
 # Worker lifecycle - restart workers periodically to prevent memory leaks[m
 max_requests = 1000  # Restart worker after handling this many requests[m
[1mdiff --git a/security_middleware.py b/security_middleware.py[m
[1mindex 39b8109..b6eafed 100644[m
[1m--- a/security_middleware.py[m
[1m+++ b/security_middleware.py[m
[36m@@ -9,6 +9,33 @@[m [mfrom collections import defaultdict, deque[m
 from utils import logger[m
 import db_enhanced[m
 [m
[32m+[m[32m# Track request start time[m
[32m+[m[32m_REQUEST_START_TIME = {}[m
[32m+[m
[32m+[m[32m# Quick pattern matching for known malicious requests - compiled for performance[m
[32m+[m[32mMALICIOUS_PATTERNS = [[m
[32m+[m[32m    re.compile(r'/lander/', re.IGNORECASE),[m
[32m+[m[32m    re.compile(r'index\.php', re.IGNORECASE),[m
[32m+[m[32m    re.compile(r'\.php', re.IGNORECASE),[m
[32m+[m[32m    re.compile(r'wp-', re.IGNORECASE),[m
[32m+[m[32m    re.compile(r'administrator', re.IGNORECASE),[m
[32m+[m[32m    re.compile(r'admin\.php', re.IGNORECASE),[m
[32m+[m[32m    re.compile(r'\.sql', re.IGNORECASE),[m
[32m+[m[32m    re.compile(r'\.env', re.IGNORECASE),[m
[32m+[m[32m][m
[32m+[m
[32m+[m[32mdef _is_quick_reject_path(path):[m
[32m+[m[32m    """Quick check for paths that should be rejected immediately - no DB access."""[m
[32m+[m[32m    if not path:[m
[32m+[m[32m        return True[m
[32m+[m[41m    [m
[32m+[m[32m    # Check against known malicious patterns (compiled regex for performance)[m
[32m+[m[32m    for pattern in MALICIOUS_PATTERNS:[m
[32m+[m[32m        if pattern.search(path):[m
[32m+[m[32m            return True[m
[32m+[m[41m    [m
[32m+[m[32m    return False[m
[32m+[m
 class SecurityMiddleware:[m
     """Advanced security middleware to block malicious requests"""[m
     [m
[36m@@ -304,6 +331,12 @@[m [msecurity_middleware = SecurityMiddleware()[m
 [m
 def security_before_request():[m
     """Flask before_request handler for security"""[m
[32m+[m[32m    # Early rejection for obviously malicious paths - no DB access[m
[32m+[m[32m    if _is_quick_reject_path(request.path):[m
[32m+[m[32m        # Log and block immediately without database access[m
[32m+[m[32m        logger.warning(f"Quick reject: malicious path from {request.remote_addr}: {request.path}")[m
[32m+[m[32m        return jsonify({'error': 'Access Denied', 'message': 'Request blocked by security policy', 'code': 403}), 403[m
[32m+[m[41m    [m
     # Skip security check for static files and allowed routes[m
     if request.path.startswith('/static/'):[m
         return None[m
