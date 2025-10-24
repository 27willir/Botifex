# Database Locking Fixes

## Problem Analysis

Your application is experiencing "database is locked" errors due to:

1. **High concurrency**: Multiple processes/threads accessing SQLite simultaneously
2. **Connection pool issues**: 50 connections may be too many for SQLite
3. **Long-running transactions**: Some operations holding locks too long
4. **WAL mode conflicts**: Even with WAL mode, SQLite can experience locking

## Immediate Solutions

### 1. Quick Fix Script
Run the database lock fix script:
```bash
python scripts/fix_database_locks.py
```

### 2. Reset Database Connections
```bash
python scripts/database_maintenance.py
```

### 3. Manual Database Reset
If scripts don't work:
```bash
# Stop your application
# Remove WAL files
rm superbot.db-wal superbot.db-shm
# Restart application
```

## Long-term Optimizations

### 1. Reduce Connection Pool Size
Current: 50 connections
Recommended: 10-20 connections

Update `db_enhanced.py`:
```python
POOL_SIZE = 15  # Reduced from 50
CONNECTION_TIMEOUT = 30  # Reduced from 60
```

### 2. Optimize Database Settings
Add these PRAGMA settings:
```python
conn.execute("PRAGMA busy_timeout=1000")  # 1 second timeout
conn.execute("PRAGMA wal_autocheckpoint=1000")  # More frequent checkpoints
conn.execute("PRAGMA synchronous=NORMAL")  # Balance safety/performance
```

### 3. Implement Connection Timeouts
Add shorter timeouts to prevent long-running connections:
```python
conn.execute("PRAGMA busy_timeout=1000")  # 1 second
```

### 4. Add Database Health Monitoring
Use the monitoring script to track database health:
```bash
python scripts/database_maintenance.py
# Choose option 6 for continuous monitoring
```

## Configuration Changes

### Update db_enhanced.py
```python
# Connection pool configuration
POOL_SIZE = 15  # Reduced from 50
CONNECTION_TIMEOUT = 30  # Reduced from 60
MAX_RETRIES = 3  # Reduced from 5
BASE_DELAY = 0.05  # Faster retry delays
```

### Add Connection Health Checks
```python
def _create_connection(self):
    conn = sqlite3.connect(
        self.database,
        check_same_thread=False,
        timeout=5,  # Shorter timeout
        isolation_level=None
    )
    # Add health check
    conn.execute("SELECT 1").fetchone()
    return conn
```

## Monitoring and Prevention

### 1. Database Health Monitoring
- Monitor connection pool usage
- Track database lock frequency
- Alert on high lock rates

### 2. Connection Pool Optimization
- Reduce pool size to prevent over-connection
- Implement connection timeouts
- Add connection health checks

### 3. Query Optimization
- Use shorter transactions
- Implement query timeouts
- Add connection pooling limits

## Emergency Procedures

### If Database is Completely Locked:
1. Stop all application processes
2. Remove WAL files: `rm *.db-wal *.db-shm`
3. Restart application
4. Monitor for recurring issues

### If Locks Persist:
1. Check for multiple application instances
2. Verify no other processes are using the database
3. Consider switching to PostgreSQL for production

## Testing the Fixes

### 1. Load Testing
Test with multiple concurrent users:
```bash
# Use tools like Apache Bench or wrk
ab -n 1000 -c 10 http://localhost:5000/
```

### 2. Connection Monitoring
Monitor connection pool status:
```python
from db_enhanced import get_pool
pool = get_pool()
print(f"Available connections: {pool.pool.qsize()}")
```

### 3. Database Health Checks
Run regular health checks:
```bash
python scripts/database_maintenance.py
```

## Prevention Strategies

### 1. Connection Pool Limits
- Keep pool size reasonable (10-20 connections)
- Implement connection timeouts
- Monitor pool usage

### 2. Transaction Management
- Keep transactions short
- Use appropriate isolation levels
- Implement retry logic

### 3. Database Optimization
- Regular VACUUM operations
- Monitor WAL file size
- Optimize queries

## Production Recommendations

### For High-Traffic Applications:
1. **Consider PostgreSQL**: Better for high concurrency
2. **Implement Redis**: For session storage and caching
3. **Use connection pooling**: Like PgBouncer for PostgreSQL
4. **Add monitoring**: Database performance monitoring

### For SQLite Applications:
1. **Optimize settings**: Use recommended PRAGMA settings
2. **Limit connections**: Keep pool size small
3. **Monitor locks**: Track and alert on lock frequency
4. **Regular maintenance**: Clean up old data regularly
