import multiprocessing
import os

# Server socket
bind = f"0.0.0.0:{os.getenv('PORT', '5000')}"
backlog = 2048

# Worker processes
workers = int(os.getenv('WEB_CONCURRENCY', multiprocessing.cpu_count() * 2 + 1))
# Use gevent for SocketIO support (compatible with Python 3.13)
# Fallback to sync if gevent not available
worker_class = os.getenv('GUNICORN_WORKER_CLASS', 'gevent')  # gevent, sync, or eventlet
worker_connections = 1000

# Timeout settings - optimized for production stability
timeout = 60  # Increased timeout to handle database operations
graceful_timeout = 30  # Allow workers time to finish current requests
keepalive = 10  # Increased for better connection reuse

# Worker lifecycle - restart workers periodically to prevent memory leaks
max_requests = 1000  # Restart worker after handling this many requests
max_requests_jitter = 100  # Add randomness to prevent all workers restarting at once

# Worker memory management
preload_app = False  # Don't preload to reduce memory per worker
limit_request_fields = 100  # Limit number of request headers and fields
limit_request_field_size = 8190  # Limit size of individual request fields

# Logging
accesslog = '-'
errorlog = '-'
loglevel = os.getenv('LOG_LEVEL', 'info')
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'

# Process naming
proc_name = 'superbot'

# Server mechanics
daemon = False
pidfile = None
umask = 0
user = None
group = None
tmp_upload_dir = None

# SSL (if needed)
# keyfile = None
# certfile = None

