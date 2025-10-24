# Security Implementation Guide

## Overview

This document describes the comprehensive security measures implemented to protect the Botifex application from malicious attacks, including the file access attempts shown in your logs.

## Security Features Implemented

### 1. Request Filtering Middleware

**File**: `security_middleware.py`

The security middleware automatically blocks malicious requests by:

- **Suspicious File Patterns**: Blocks access to sensitive files like:
  - Configuration files (`.env`, `.ini`, `.conf`, `.yml`, `.yaml`)
  - Database files (`.sql`, `.db`, `.database`)
  - Backup files (`.bak`, `.backup`, `.old`)
  - Version control files (`.git`, `.svn`, `.hg`)
  - Script files (`.sh`, `.bat`, `.cmd`, `.ps1`)
  - PHP/ASP files (`.php`, `.asp`, `.jsp`)
  - Security files (`.htaccess`, `.htpasswd`)

- **Malicious User Agents**: Detects and blocks requests from known attack tools:
  - `sqlmap`, `nikto`, `nmap`, `masscan`
  - `zap`, `burp`, `scanner`, `bot`, `crawler`

- **Rate Limiting**: Implements IP-based rate limiting:
  - Maximum 30 requests per minute per IP
  - Automatic blocking after 5 suspicious requests
  - 60-minute block duration

### 2. Security Headers

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

1. **Configuration File Access**:
   - `/application.yml`
   - `/composer.json`
   - `/docker-compose.yml`
   - `/web.config`
   - `/config.js`
   - `/settings.php`

2. **Database File Access**:
   - `/db.php`
   - `/database.php`

3. **Backup File Access**:
   - `/.env.bak`
   - `/.gitconfig`

4. **Directory Traversal Attempts**:
   - `/admin/`, `/wp-admin/`, `/phpmyadmin/`
   - `/.git/`, `/.svn/`, `/.hg/`

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
- Real-time statistics

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
