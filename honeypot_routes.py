"""
Honeypot routes to detect and block automated scanners
These routes are designed to attract malicious bots and immediately block them
"""
from flask import request, jsonify, abort
from security_middleware import security_middleware
from utils import logger
import time
import random

class HoneypotManager:
    """Manages honeypot routes to detect and block automated scanners"""
    
    def __init__(self):
        self.honeypot_ips = set()
        self.honeypot_attempts = {}
        
    def log_honeypot_access(self, ip, path, user_agent):
        """Log honeypot access and block IP"""
        self.honeypot_attempts[ip] = self.honeypot_attempts.get(ip, 0) + 1
        self.honeypot_ips.add(ip)
        
        # Immediately block the IP
        security_middleware.blocked_ips.add(ip)
        
        logger.warning(f"HONEYPOT TRIGGERED: IP {ip} accessed honeypot route {path} (attempt #{self.honeypot_attempts[ip]})")
        logger.warning(f"User-Agent: {user_agent}")
        
        # Log to security events
        security_middleware.log_security_event(
            ip=ip,
            path=path,
            user_agent=user_agent,
            reason="Honeypot triggered - automated scanner detected"
        )
    
    def is_honeypot_triggered(self, ip):
        """Check if IP has triggered honeypot"""
        return ip in self.honeypot_ips

# Global honeypot manager
honeypot_manager = HoneypotManager()

def create_honeypot_routes(app):
    """Create honeypot routes that attract malicious bots"""
    
    @app.route('/.env')
    @app.route('/.env.local')
    @app.route('/.env.production')
    @app.route('/.env.staging')
    @app.route('/.env.development')
    @app.route('/.env.backup')
    @app.route('/.env.old')
    @app.route('/.env.sample')
    @app.route('/.env.example')
    def honeypot_env():
        """Honeypot for .env file access attempts"""
        ip = request.remote_addr
        honeypot_manager.log_honeypot_access(ip, request.path, request.headers.get('User-Agent', ''))
        return jsonify({'error': 'Access Denied'}), 403
    
    @app.route('/wp-config.php')
    @app.route('/wp-config.php.bak')
    @app.route('/wp-config')
    def honeypot_wp_config():
        """Honeypot for WordPress config access"""
        ip = request.remote_addr
        honeypot_manager.log_honeypot_access(ip, request.path, request.headers.get('User-Agent', ''))
        return jsonify({'error': 'Access Denied'}), 403
    
    @app.route('/phpinfo.php')
    @app.route('/info.php')
    @app.route('/test.php')
    @app.route('/server-info.php')
    @app.route('/server_info.php')
    @app.route('/_phpinfo.php')
    @app.route('/_profiler/phpinfo')
    @app.route('/_profiler/phpinfo/phpinfo.php')
    @app.route('/dashboard/phpinfo.php')
    @app.route('/admin/server_info.php')
    @app.route('/secured/phpinfo.php')
    def honeypot_phpinfo():
        """Honeypot for PHP info access attempts"""
        ip = request.remote_addr
        honeypot_manager.log_honeypot_access(ip, request.path, request.headers.get('User-Agent', ''))
        return jsonify({'error': 'Access Denied'}), 403
    
    @app.route('/config.js')
    @app.route('/config.json')
    @app.route('/config.yml')
    @app.route('/config.yaml')
    @app.route('/settings.php')
    @app.route('/database.php')
    @app.route('/db.php')
    def honeypot_config():
        """Honeypot for configuration file access"""
        ip = request.remote_addr
        honeypot_manager.log_honeypot_access(ip, request.path, request.headers.get('User-Agent', ''))
        return jsonify({'error': 'Access Denied'}), 403
    
    @app.route('/admin/')
    @app.route('/wp-admin/')
    @app.route('/phpmyadmin/')
    @app.route('/adminer/')
    @app.route('/admin.php')
    def honeypot_admin():
        """Honeypot for admin interface access"""
        ip = request.remote_addr
        honeypot_manager.log_honeypot_access(ip, request.path, request.headers.get('User-Agent', ''))
        return jsonify({'error': 'Access Denied'}), 403
    
    @app.route('/.git/')
    @app.route('/.svn/')
    @app.route('/.hg/')
    @app.route('/.git/config')
    @app.route('/.git/HEAD')
    def honeypot_vcs():
        """Honeypot for version control access"""
        ip = request.remote_addr
        honeypot_manager.log_honeypot_access(ip, request.path, request.headers.get('User-Agent', ''))
        return jsonify({'error': 'Access Denied'}), 403
    
    @app.route('/composer.json')
    @app.route('/package.json')
    @app.route('/requirements.txt')
    @app.route('/docker-compose.yml')
    @app.route('/Dockerfile')
    @app.route('/web.config')
    @app.route('/.htaccess')
    def honeypot_dev_files():
        """Honeypot for development file access"""
        ip = request.remote_addr
        honeypot_manager.log_honeypot_access(ip, request.path, request.headers.get('User-Agent', ''))
        return jsonify({'error': 'Access Denied'}), 403
    
    @app.route('/aws-secret.yaml')
    @app.route('/.aws/credentials')
    @app.route('/.aws/config')
    def honeypot_aws():
        """Honeypot for AWS credential access"""
        ip = request.remote_addr
        honeypot_manager.log_honeypot_access(ip, request.path, request.headers.get('User-Agent', ''))
        return jsonify({'error': 'Access Denied'}), 403
    
    @app.route('/xampp/')
    @app.route('/xampp/phpinfo.php')
    @app.route('/lara/phpinfo.php')
    @app.route('/lara/info.php')
    @app.route('/laravel/info.php')
    @app.route('/laravel/.env')
    def honeypot_php_frameworks():
        """Honeypot for PHP framework access"""
        ip = request.remote_addr
        honeypot_manager.log_honeypot_access(ip, request.path, request.headers.get('User-Agent', ''))
        return jsonify({'error': 'Access Denied'}), 403
    
    @app.route('/node_modules/')
    @app.route('/node/.env_example')
    @app.route('/scripts/nodemailer.js')
    def honeypot_node():
        """Honeypot for Node.js file access"""
        ip = request.remote_addr
        honeypot_manager.log_honeypot_access(ip, request.path, request.headers.get('User-Agent', ''))
        return jsonify({'error': 'Access Denied'}), 403
    
    @app.route('/static/js/main.<random>.js')
    @app.route('/static/js/2.<random>.chunk.js')
    def honeypot_static_js():
        """Honeypot for static JS file access (common in React apps)"""
        ip = request.remote_addr
        honeypot_manager.log_honeypot_access(ip, request.path, request.headers.get('User-Agent', ''))
        return jsonify({'error': 'Access Denied'}), 403
    
    @app.route('/api/shared/config/config.env')
    @app.route('/api/shared/config.env')
    @app.route('/api/shared/.env')
    @app.route('/api/config.env')
    def honeypot_api_config():
        """Honeypot for API configuration access"""
        ip = request.remote_addr
        honeypot_manager.log_honeypot_access(ip, request.path, request.headers.get('User-Agent', ''))
        return jsonify({'error': 'Access Denied'}), 403
    
    @app.route('/service/email_service.py')
    @app.route('/server/config/database.js')
    def honeypot_service_files():
        """Honeypot for service file access"""
        ip = request.remote_addr
        honeypot_manager.log_honeypot_access(ip, request.path, request.headers.get('User-Agent', ''))
        return jsonify({'error': 'Access Denied'}), 403
    
    # Decoy routes that look legitimate but are actually honeypots
    @app.route('/robots.txt')
    def honeypot_robots():
        """Honeypot disguised as robots.txt"""
        ip = request.remote_addr
        # Only trigger if it's clearly a bot (no referer, suspicious user agent)
        user_agent = request.headers.get('User-Agent', '').lower()
        if any(bot in user_agent for bot in ['bot', 'crawler', 'spider', 'scanner']):
            honeypot_manager.log_honeypot_access(ip, request.path, request.headers.get('User-Agent', ''))
            return jsonify({'error': 'Access Denied'}), 403
        # Return normal robots.txt for legitimate requests
        return "User-agent: *\nDisallow: /admin/\nDisallow: /api/\n", 200, {'Content-Type': 'text/plain'}
    
    @app.route('/sitemap.xml')
    def honeypot_sitemap():
        """Honeypot disguised as sitemap.xml"""
        ip = request.remote_addr
        # Only trigger for suspicious requests
        if request.headers.get('User-Agent', '').lower() in ['', 'scanner', 'bot']:
            honeypot_manager.log_honeypot_access(ip, request.path, request.headers.get('User-Agent', ''))
            return jsonify({'error': 'Access Denied'}), 403
        # Return normal sitemap for legitimate requests
        return "<?xml version='1.0' encoding='UTF-8'?>\n<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>\n</urlset>", 200, {'Content-Type': 'application/xml'}

def get_honeypot_stats():
    """Get honeypot statistics"""
    return {
        'triggered_ips': len(honeypot_manager.honeypot_ips),
        'total_attempts': sum(honeypot_manager.honeypot_attempts.values()),
        'honeypot_attempts': dict(honeypot_manager.honeypot_attempts),
        'blocked_ips': list(honeypot_manager.honeypot_ips)
    }
