# ⚡ Quick Command Reference - Deployment

Copy-paste commands for quick deployment.

---

## 📦 Prepare Code for Deployment

```bash
# Initialize git (if needed)
git init

# Add all files
git add .

# Commit
git commit -m "Ready for deployment"

# Create GitHub repo first at github.com, then:
git remote add origin https://github.com/YOUR-USERNAME/super-bot.git
git branch -M main
git push -u origin main
```

---

## 🔑 Generate Secret Key

```bash
# Generate secure SECRET_KEY
python -c "import secrets; print(secrets.token_hex(32))"
```

Copy the output and use it as your `SECRET_KEY` environment variable.

---

## 🏗️ Initialize Database (After Deployment)

```bash
# Initialize database tables
python scripts/init_db.py

# Create admin user
python scripts/create_admin.py admin admin@example.com YourSecurePassword123!
```

---

## 🌐 Render Deployment Commands

```bash
# Not needed! Deploy via web interface at render.com
# Just push to GitHub and connect repository

# After deployment, access Render Shell and run:
python scripts/init_db.py
python scripts/create_admin.py admin admin@example.com Password123!
```

---

## 🚂 Railway Deployment Commands

```bash
# Install Railway CLI (optional)
npm i -g @railway/cli

# Login
railway login

# Link project
railway link

# View logs
railway logs

# Run commands
railway run python scripts/init_db.py
railway run python scripts/create_admin.py admin admin@example.com Password123!
```

---

## 🎨 Heroku Deployment Commands

```bash
# Install Heroku CLI first
# Download from: https://devcenter.heroku.com/articles/heroku-cli

# Login
heroku login

# Create app
heroku create your-superbot-app

# Set buildpack
heroku buildpacks:set heroku/python

# Set environment variables
heroku config:set SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
heroku config:set FLASK_ENV=production
heroku config:set FLASK_DEBUG=False
heroku config:set SESSION_COOKIE_SECURE=True
heroku config:set SESSION_COOKIE_HTTPONLY=True

# Deploy
git push heroku main

# Initialize database
heroku run python scripts/init_db.py
heroku run python scripts/create_admin.py admin admin@example.com Password123!

# View logs
heroku logs --tail

# Open app
heroku open

# Scale web dynos
heroku ps:scale web=1
```

---

## 🐳 DigitalOcean Droplet Setup

```bash
# Connect to your droplet
ssh root@your-droplet-ip

# Update system
apt update && apt upgrade -y

# Install dependencies
apt install python3 python3-pip python3-venv nginx supervisor git -y

# Install Chrome for Selenium
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
apt install ./google-chrome-stable_current_amd64.deb -y

# Clone repository
cd /var/www
git clone https://github.com/YOUR-USERNAME/super-bot.git
cd super-bot

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install requirements
pip install -r requirements.txt

# Create .env file
nano .env
# Paste your environment variables

# Initialize database
python scripts/init_db.py
python scripts/create_admin.py admin admin@example.com Password123!

# Test application
gunicorn --worker-class eventlet -w 4 --bind 127.0.0.1:8000 app:app
```

### Configure Supervisor

```bash
# Create supervisor config
nano /etc/supervisor/conf.d/superbot.conf
```

Paste:
```ini
[program:superbot]
directory=/var/www/super-bot
command=/var/www/super-bot/venv/bin/gunicorn --worker-class eventlet -w 4 --bind 127.0.0.1:8000 app:app
user=www-data
autostart=true
autorestart=true
stderr_logfile=/var/log/superbot.err.log
stdout_logfile=/var/log/superbot.out.log
```

```bash
# Reload supervisor
supervisorctl reread
supervisorctl update
supervisorctl start superbot
supervisorctl status
```

### Configure Nginx

```bash
# Create nginx config
nano /etc/nginx/sites-available/superbot
```

Paste:
```nginx
server {
    listen 80;
    server_name your-domain.com www.your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
    
    location /static {
        alias /var/www/super-bot/static;
        expires 30d;
    }
}
```

```bash
# Enable site
ln -s /etc/nginx/sites-available/superbot /etc/nginx/sites-enabled/
nginx -t
systemctl restart nginx

# Install SSL
apt install certbot python3-certbot-nginx -y
certbot --nginx -d your-domain.com -d www.your-domain.com

# Auto-renew SSL
certbot renew --dry-run
```

---

## 🔄 Update Deployed Application

### Render/Railway (Auto-Deploy)
```bash
# Just push to GitHub
git add .
git commit -m "Update application"
git push origin main

# Render/Railway will auto-deploy
```

### Heroku
```bash
git add .
git commit -m "Update application"
git push heroku main
```

### DigitalOcean
```bash
# On your droplet
cd /var/www/super-bot
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
supervisorctl restart superbot
```

---

## 📊 View Logs

### Render
```bash
# Via web interface: Dashboard → Logs tab
# Or use Render CLI
```

### Railway
```bash
railway logs
```

### Heroku
```bash
heroku logs --tail
heroku logs --tail --source app
```

### DigitalOcean
```bash
# Application logs
tail -f /var/log/superbot.out.log
tail -f /var/log/superbot.err.log

# Nginx logs
tail -f /var/log/nginx/access.log
tail -f /var/log/nginx/error.log

# Supervisor logs
supervisorctl tail -f superbot
```

---

## 🗄️ Database Management

### Backup Database
```bash
# On server/shell
python scripts/backup_database.py

# Or manually
cp superbot.db backups/superbot_$(date +%Y%m%d_%H%M%S).db
```

### Restore Database
```bash
# Stop application first
cp backups/your-backup-file.db superbot.db
# Restart application
```

### Reset Database
```bash
# WARNING: This deletes all data!
rm superbot.db
python scripts/init_db.py
python scripts/create_admin.py admin admin@example.com Password123!
```

---

## 🔐 Environment Variables

### View Current Variables

**Render:** Dashboard → Environment tab

**Railway:**
```bash
railway variables
```

**Heroku:**
```bash
heroku config
```

### Set Variable

**Render:** Dashboard → Environment → Add Variable

**Railway:**
```bash
railway variables set KEY=value
```

**Heroku:**
```bash
heroku config:set KEY=value
```

### Remove Variable

**Railway:**
```bash
railway variables delete KEY
```

**Heroku:**
```bash
heroku config:unset KEY
```

---

## 🧪 Testing Commands

### Test Locally
```bash
# Run development server
python app.py

# Or with gunicorn
gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:5000 app:app
```

### Test Production URL
```bash
# Test homepage
curl https://your-app.onrender.com

# Test API
curl https://your-app.onrender.com/api/status

# Test with verbose output
curl -v https://your-app.onrender.com
```

---

## 🎛️ Scale Application

### Heroku
```bash
# Scale web dynos
heroku ps:scale web=2

# View current scale
heroku ps
```

### Render
```bash
# Via dashboard: Instance Type → Select larger size
```

### DigitalOcean
```bash
# Increase worker count in supervisor config
nano /etc/supervisor/conf.d/superbot.conf
# Change: -w 4 to -w 8 (or more)
supervisorctl restart superbot
```

---

## 🔍 Debug Commands

### Check if app is running
```bash
# Heroku
heroku ps

# DigitalOcean
supervisorctl status
ps aux | grep gunicorn
```

### Interactive shell
```bash
# Heroku
heroku run bash

# Railway
railway run bash

# DigitalOcean
ssh root@your-droplet-ip
```

### Python shell
```bash
# On server/shell
python
>>> from app import app
>>> from db_enhanced import *
>>> # Test database queries
```

---

## 🎨 Custom Domain

### Render
1. Dashboard → Settings → Custom Domains
2. Add domain: `yourdomain.com`
3. Update DNS:
   - Type: CNAME
   - Name: www
   - Value: your-app.onrender.com

### Heroku
```bash
heroku domains:add www.yourdomain.com
heroku domains:add yourdomain.com

# Get DNS target
heroku domains

# Update DNS with provided target
```

---

## 📦 Install Additional Dependencies

### Add to requirements.txt
```bash
echo "new-package==1.0.0" >> requirements.txt
```

### Install and deploy
```bash
# Commit and push
git add requirements.txt
git commit -m "Add new dependency"
git push origin main

# Or on DigitalOcean
pip install -r requirements.txt
supervisorctl restart superbot
```

---

## 🔒 SSL/HTTPS

### Render/Railway/Heroku
```bash
# Automatic! HTTPS enabled by default
# No commands needed
```

### DigitalOcean
```bash
# Install certbot (if not already)
apt install certbot python3-certbot-nginx -y

# Get certificate
certbot --nginx -d yourdomain.com -d www.yourdomain.com

# Renew (automatic with cron)
certbot renew --dry-run
```

---

## 🧹 Maintenance Commands

### Clear cache
```bash
# Via admin dashboard: /admin/cache → Clear Cache

# Or via Python
python -c "from cache_manager import cache_clear; cache_clear()"
```

### Clean old logs
```bash
# DigitalOcean
find /var/log -name "*.log" -mtime +30 -delete
```

### Optimize database
```bash
python -c "import sqlite3; conn = sqlite3.connect('superbot.db'); conn.execute('VACUUM'); conn.close()"
```

---

## 🆘 Emergency Commands

### Restart application
**Render/Railway:** Dashboard → Manual Deploy or Restart

**Heroku:**
```bash
heroku restart
```

**DigitalOcean:**
```bash
supervisorctl restart superbot
```

### Stop application
**Heroku:**
```bash
heroku ps:scale web=0
```

**DigitalOcean:**
```bash
supervisorctl stop superbot
```

### Start application
**Heroku:**
```bash
heroku ps:scale web=1
```

**DigitalOcean:**
```bash
supervisorctl start superbot
```

---

## 📝 Notes

- Replace `YOUR-USERNAME` with your GitHub username
- Replace `your-app-name` with your actual app name
- Replace `your-droplet-ip` with your server IP
- Replace `yourdomain.com` with your actual domain
- Always test commands in development first
- Keep backups before major changes

---

**Quick Reference Complete!** 

For detailed explanations, see:
- [QUICK_DEPLOY.md](QUICK_DEPLOY.md)
- [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)
- [README_DEPLOYMENT.md](README_DEPLOYMENT.md)

