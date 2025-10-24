# Security Implementation Guide

## Overview

This document describes the comprehensive security measures implemented to protect the Botifex application from malicious attacks, including the file access attempts shown in your logs.

## Security Features Implemented

### 1. Enhanced Request Filtering Middleware

**File**: `security_middleware.py`

The security middleware automatically blocks malicious requests by:

- **Comprehensive Suspicious File Patterns**: Blocks access to sensitive files including:
  - Environment files (`.env`, `.env.local`, `.env.production`, etc.)
  - Configuration files (`.ini`, `.conf`, `.config`, `.yml`, `.yaml`)
  - Database files (`.sql`, `.db`, `.database`)
  - Backup files (`.bak`, `.backup`, `.old`, `.tmp`)
  - Version control files (`.git`, `.svn`, `.hg`)
  - Script files (`.sh`, `.bat`, `.cmd`, `.ps1`)
  - PHP/ASP files (`.php`, `.asp`, `.jsp`)
  - Security files (`.htaccess`, `.htpasswd`)
  - AWS credentials (`.aws/credentials`)
  - Development files (`composer.json`, `package.json`, `Dockerfile`)

- **Enhanced Malicious User Agent Detection**: Detects and blocks requests from:
  - Security scanners: `sqlmap`, `nikto`, `nmap`, `masscan`
  - Testing tools: `zap`, `burp`, `scanner`, `bot`, `crawler`
  - HTTP clients: `python-requests`, `curl`, `wget`, `httpie`
  - Programming languages: `go-http-client`, `java`, `perl`, `ruby`, `php`

- **Multi-Level Rate Limiting**: Implements aggressive IP-based rate limiting:
  - Maximum 20 requests per minute per IP (reduced from 30)
  - Maximum 5 requests per second per IP
  - Maximum 10 requests per 10 seconds (rapid-fire protection)
  - Automatic blocking after 3 suspicious requests (reduced from 5)
  - 120-minute block duration (increased from 60)
  - Immediate blocking for high-risk file access patterns

### 2. Honeypot Routes

**File**: `honeypot_routes.py`

Advanced honeypot system that attracts and immediately blocks automated scanners:

- **Environment File Honeypots**: Disguised routes for `.env` files
- **Configuration Honeypots**: Routes for `wp-config.php`, `config.js`, etc.
- **PHP Info Honeypots**: Routes for `phpinfo.php`, `info.php`, etc.
- **Admin Interface Honeypots**: Routes for `/admin/`, `/wp-admin/`, etc.
- **Version Control Honeypots**: Routes for `/.git/`, `/.svn/`, etc.
- **Development File Honeypots**: Routes for `composer.json`, `Dockerfile`, etc.
- **AWS Credential Honeypots**: Routes for AWS configuration files
- **Framework-Specific Honeypots**: Routes for Laravel, Node.js, React apps
- **Decoy Routes**: Legitimate-looking routes like `/robots.txt`, `/sitemap.xml`

### 3. Enhanced Rate Limiting

**File**: `rate_limiter.py`

Improved rate limiting with security integration:

- **Reduced Rate Limits**: More aggressive limits for all endpoints
  - API endpoints: 30 requests/minute (reduced from 60)
  - Scraper operations: 5 requests/minute (reduced from 10)
  - Settings updates: 15 requests/minute (reduced from 30)
  - Login attempts: 3 requests/minute (reduced from 5)
  - Registration: 2 requests/minute (reduced from 3)

- **Security Integration**: Rate limiter now checks:
  - Security middleware blocked IPs
  - Honeypot-triggered IPs
  - Suspicious IP reputation
  - Applies stricter limits for suspicious IPs (1 request/minute)

- **Enhanced Headers**: Added security information to responses:
  - `X-RateLimit-Remaining`: Remaining requests
  - `X-Security-Level`: Security level indicator
  - `X-Content-Security`: Security status

### 4. Security Headers

**Implementation**: Added comprehensive security headers to all responses:

```http
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 1; mode=block
Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; ...
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: geolocation=(), microphone=(), camera=(), ...
```

### 3. Security Event Logging

**Database Table**: `security_events`

Logs all security events including:
- IP addresses of blocked requests
- Requested paths
- User agents
- Block reasons
- Timestamps

### 4. Admin Security Dashboard

**Route**: `/admin/security`

Features:
- Real-time security statistics
- Blocked IPs monitoring
- Suspicious activity tracking
- Security event history
- IP-based event filtering

## Attack Patterns Blocked

Based on your logs, the following attack patterns are now automatically blocked:

### 1. Environment File Access (High Priority)
- `/.env`, `/.env.local`, `/.env.production`, `/.env.staging`
- `/.env.backup`, `/.env.old`, `/.env.sample`, `/.env.example`
- `/.env.production.local`, `/.env.stage`, `/.env.prod`

### 2. Configuration File Access
- `/application.yml`, `/composer.json`, `/docker-compose.yml`
- `/web.config`, `/config.js`, `/settings.php`
- `/config.json`, `/config.yml`, `/config.yaml`
- `/database.php`, `/db.php`

### 3. PHP Information Disclosure
- `/phpinfo.php`, `/info.php`, `/test.php`
- `/server-info.php`, `/server_info.php`
- `/_phpinfo.php`, `/_profiler/phpinfo`
- `/dashboard/phpinfo.php`, `/admin/server_info.php`
- `/secured/phpinfo.php`

### 4. WordPress and CMS Access
- `/wp-config.php`, `/wp-config.php.bak`, `/wp-config`
- `/wp-admin/`, `/admin/`, `/phpmyadmin/`, `/adminer/`

### 5. Version Control Access
- `/.git/`, `/.svn/`, `/.hg/`
- `/.git/config`, `/.git/HEAD`
- `/.vscode/`, `/.idea/`

### 6. Development Framework Access
- `/xampp/`, `/lara/phpinfo.php`, `/laravel/info.php`
- `/laravel/.env`, `/laravel/core/.env`
- `/node_modules/`, `/node/.env_example`
- `/scripts/nodemailer.js`

### 7. AWS and Cloud Credentials
- `/aws-secret.yaml`, `/.aws/credentials`, `/.aws/config`

### 8. Application-Specific Paths
- `/app/`, `/new/`, `/dev/`, `/prod/`, `/staging/`
- `/development/`, `/backend/`, `/frontend/`
- `/website/`, `/site/`, `/public/`, `/main/`
- `/core/`, `/local/`, `/apps/`, `/application/`
- `/web/`, `/crm/`, `/kyc/`, `/mail/`, `/mailer/`
- `/nginx/`, `/docker/`, `/api/shared/`

### 9. Static Asset Access (React/Vue apps)
- `/static/js/main.*.js`, `/static/js/2.*.chunk.js`
- `/static/js/*.chunk.js`

### 10. Service and Database Files
- `/service/email_service.py`
- `/server/config/database.js`
- `/api/shared/config/config.env`
- `/api/shared/config.env`

## Implementation Details

### Security Middleware Integration

The security middleware is integrated into the Flask application as the first `@app.before_request` handler:

```python
@app.before_request
def before_request():
    return security_before_request()
```

### Database Schema

The `security_events` table stores security events:

```sql
CREATE TABLE security_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ip_address TEXT NOT NULL,
    path TEXT NOT NULL,
    user_agent TEXT,
    reason TEXT NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### Rate Limiting Algorithm

1. **Request Tracking**: Each IP's requests are tracked in a sliding window
2. **Threshold Detection**: IPs exceeding 30 requests/minute are blocked
3. **Suspicious Activity**: IPs with 5+ suspicious file access attempts are blocked
4. **Automatic Cleanup**: Old tracking data is cleaned up every 5 minutes

## Monitoring and Alerting

### Real-time Monitoring

The admin dashboard provides:
- Live security statistics
- Currently blocked IPs
- Recent security events
- Suspicious IP tracking

### Security Event Types

1. **Suspicious File Access**: Attempts to access sensitive files
2. **Rate Limit Exceeded**: Too many requests from single IP
3. **Malicious User Agent**: Known attack tools
4. **IP Blocked**: Automatic blocking due to suspicious activity

## Configuration

### Environment Variables

The security middleware can be configured via environment variables:

```bash
# Rate limiting
MAX_REQUESTS_PER_MINUTE=30
MAX_SUSPICIOUS_REQUESTS=5
BLOCK_DURATION_MINUTES=60

# Security headers
SESSION_COOKIE_SECURE=True
SESSION_COOKIE_HTTPONLY=True
SESSION_COOKIE_SAMESITE=Lax
```

### Customization

To add new suspicious patterns, modify the `suspicious_patterns` list in `security_middleware.py`:

```python
self.suspicious_patterns = [
    r'\.(env|bak|backup|old|tmp|temp)$',
    # Add your custom patterns here
    r'\.(your-custom-pattern)$',
]
```

## Testing the Security Implementation

### 1. Test Malicious File Access

Try accessing these URLs (they should return 403 Forbidden):
- `/application.yml`
- `/composer.json`
- `/docker-compose.yml`
- `/db.php`
- `/.env.bak`

### 2. Test Rate Limiting

Make multiple rapid requests to trigger rate limiting.

### 3. Monitor Security Dashboard

Visit `/admin/security` to see:
- Blocked IPs
- Security events
- Real-time s](../../../Downloads/Botifex-main.zip)
## Maintenance

### Regular Tasks

1. **Review Security Events**: Check `/admin/security` regularly
2. **Clean Old Data**: Security events older than 30 days can be archived
3. **Update Patterns**: Add new attack patterns as they emerge
4. **Monitor Logs**: Watch for new attack vectors

### Database Maintenance

```sql
-- Clean up old security events (older than 30 days)
DELETE FROM security_events 
WHERE timestamp < datetime('now', '-30 days');
```

## Security Best Practices

1. **Regular Updates**: Keep security patterns updated
2. **Monitor Alerts**: Check security dashboard daily
3. **Log Analysis**: Review security events weekly
4. **Pattern Updates**: Add new attack patterns as discovered
5. **IP Whitelisting**: Whitelist legitimate IPs if needed

## Troubleshooting

### Common Issues

1. **False Positives**: Legitimate users blocked
   - Solution: Whitelist their IPs or adjust patterns

2. **High False Positive Rate**: Too many legitimate requests blocked
   - Solution: Adjust rate limiting thresholds

3. **Missing Attacks**: New attack patterns not blocked
   - Solution: Add new patterns to `suspicious_patterns`

### Debugging

Enable debug logging to see security decisions:

```python
import logging
logging.getLogger('security_middleware').setLevel(logging.DEBUG)
```

## Conclusion

This security implementation provides comprehensive protection against the types of attacks shown in your logs. The system automatically blocks malicious file access attempts, implements rate limiting, and provides detailed monitoring capabilities.

The security middleware is designed to be:
- **Automatic**: No manual intervention required
- **Comprehensive**: Covers multiple attack vectors
- **Configurable**: Easy to adjust for your needs
- **Monitorable**: Full visibility into security events
- **Maintainable**: Easy to update and extend
