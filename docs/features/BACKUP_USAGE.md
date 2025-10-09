# Database Backup System - User Guide
## Super-Bot Application

---

## 🎯 Overview

The automated backup system protects your data with:
- ✅ Automatic daily backups
- ✅ Gzip compression (saves ~70% space)
- ✅ 7-day retention policy
- ✅ Easy restore capability
- ✅ Safety backups before restore

---

## 📦 Manual Backup

### Create a Backup:
```bash
python scripts/backup_database.py
```

**Output:**
```
📦 Creating backup: superbot_backup_20251009_153045.db.gz
✅ Backup created successfully!
   Original size: 15.34 MB
   Compressed size: 4.21 MB
   Compression: 72.6%
   Location: backups/superbot_backup_20251009_153045.db.gz
```

---

## 📋 List Backups

### View All Available Backups:
```bash
python scripts/backup_database.py list
```

**Output:**
```
📋 Available backups (5):
--------------------------------------------------------------------------------
   superbot_backup_20251009_153045.db.gz
      Date: 2025-10-09 15:30:45 (2h ago) | Size: 4.21 MB
   superbot_backup_20251009_020000.db.gz
      Date: 2025-10-09 02:00:00 (13h ago) | Size: 4.18 MB
   superbot_backup_20251008_020000.db.gz
      Date: 2025-10-08 02:00:00 (1d ago) | Size: 4.15 MB
```

---

## ♻️ Restore a Backup

### Restore from a Specific Backup:
```bash
python scripts/backup_database.py restore superbot_backup_20251009_153045.db.gz
```

**What Happens:**
1. Creates a safety backup of current database
2. Restores the selected backup
3. Keeps safety backup in case you need to revert

**Output:**
```
📦 Created safety backup: superbot.db.before_restore
♻️  Restoring backup: superbot_backup_20251009_153045.db.gz
✅ Database restored successfully from superbot_backup_20251009_153045.db.gz
   Safety backup saved as: superbot.db.before_restore
```

**⚠️ Important:** Stop your application before restoring!

---

## 🧹 Cleanup Old Backups

### Remove Old Backups Manually:
```bash
python scripts/backup_database.py cleanup
```

**What Gets Removed:**
- Backups older than 7 days
- Excess backups (keeps max 30)

---

## 🤖 Automated Daily Backups

### Option 1: Run as Background Service

**Linux/Mac:**
```bash
# Start the scheduler
python scripts/schedule_backups.py &

# To stop, find the process
ps aux | grep schedule_backups
kill <PID>
```

**Windows:**
```powershell
# Start in background
Start-Process python -ArgumentList "scripts/schedule_backups.py" -WindowStyle Hidden
```

---

### Option 2: Use Cron (Linux/Mac)

**Edit crontab:**
```bash
crontab -e
```

**Add this line (runs at 2 AM daily):**
```bash
0 2 * * * cd /path/to/super-bot && python scripts/backup_database.py >> backups/backup.log 2>&1
```

---

### Option 3: Use Task Scheduler (Windows)

1. Open **Task Scheduler**
2. Create Basic Task
3. Name: "Super-Bot Daily Backup"
4. Trigger: Daily at 2:00 AM
5. Action: Start a Program
6. Program: `python`
7. Arguments: `scripts/backup_database.py`
8. Start in: `C:\path\to\super-bot`

---

## 📊 Backup Configuration

Edit `scripts/backup_database.py` to customize:

```python
# Configuration
DB_FILE = "superbot.db"          # Database file name
BACKUP_DIR = Path("backups")     # Backup directory
KEEP_DAYS = 7                    # Keep backups for 7 days
MAX_BACKUPS = 30                 # Maximum number of backups
```

---

## 🔍 Troubleshooting

### Problem: "Database file not found"
**Solution:** Make sure you're in the super-bot directory
```bash
cd /path/to/super-bot
python scripts/backup_database.py
```

---

### Problem: "Permission denied"
**Solution:** Check file permissions
```bash
chmod +x scripts/backup_database.py
chmod 755 backups/
```

---

### Problem: Backup fails during restore
**Solution:** The safety backup is automatically created before restore
```bash
# If restore fails, manually restore the safety backup
cp superbot.db.before_restore superbot.db
```

---

## 💾 Storage Requirements

### Typical Sizes:
- **Small database** (< 1000 listings): 1-5 MB compressed
- **Medium database** (1000-10000 listings): 5-20 MB compressed
- **Large database** (10000+ listings): 20-100 MB compressed

### With default settings (30 backups max, 7 days retention):
- **Maximum storage:** ~3 GB for large databases
- **Typical storage:** ~150-600 MB

---

## 🔐 Security Notes

1. **Backup Location:** Backups are stored in `backups/` directory
2. **Encryption:** Backups are NOT encrypted by default
3. **Off-site Backup:** Consider copying to cloud storage
4. **Access Control:** Ensure proper file permissions

### Optional: Encrypt Backups
```bash
# Encrypt a backup
gpg --symmetric backups/superbot_backup_20251009_153045.db.gz

# Decrypt a backup
gpg --decrypt backups/superbot_backup_20251009_153045.db.gz.gpg > restore.db.gz
```

---

## ☁️ Cloud Backup Integration

### AWS S3 Example:
```bash
# Install AWS CLI
pip install awscli

# Sync backups to S3 after each backup
aws s3 sync backups/ s3://your-bucket/superbot-backups/
```

### Google Drive Example:
```bash
# Install rclone
# Configure with: rclone config

# Sync backups to Google Drive
rclone sync backups/ gdrive:superbot-backups/
```

---

## 📈 Monitoring Backup Health

### Check Last Backup:
```bash
ls -lth backups/ | head -n 2
```

### Verify Backup Integrity:
```bash
# Test that backup can be decompressed
gunzip -t backups/superbot_backup_20251009_153045.db.gz
echo "Backup integrity: OK"
```

### Monitor Disk Space:
```bash
# Check available space
df -h .

# Check backups directory size
du -sh backups/
```

---

## 🎓 Best Practices

1. **Test Restores Regularly:** 
   - Test restore process monthly
   - Verify data integrity after restore

2. **Monitor Backup Success:**
   - Check backup logs daily
   - Set up alerts for failed backups

3. **Off-site Backups:**
   - Copy backups to cloud storage
   - Keep at least one off-site backup

4. **Before Major Changes:**
   - Always create a manual backup
   - Test on a copy first

5. **Disaster Recovery Plan:**
   - Document restore procedure
   - Train team members
   - Keep backup credentials secure

---

## 📞 Quick Reference

| Command | Description |
|---------|-------------|
| `python scripts/backup_database.py` | Create backup now |
| `python scripts/backup_database.py list` | List all backups |
| `python scripts/backup_database.py restore <file>` | Restore a backup |
| `python scripts/backup_database.py cleanup` | Remove old backups |
| `python scripts/schedule_backups.py` | Run automated backups |

---

## ✅ Backup Checklist

- [ ] Automated daily backups configured
- [ ] Tested manual backup creation
- [ ] Tested restore process
- [ ] Verified backup compression working
- [ ] Checked backup directory has enough space
- [ ] Set up off-site backup (optional)
- [ ] Documented restore procedure
- [ ] Team members trained on restore

---

**Your data is now protected! 🛡️**

