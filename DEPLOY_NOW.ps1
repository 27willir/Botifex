# Quick Deploy Script - Run this after closing vim
# If vim is open, press Esc then :wq to close it first

Write-Host "🚀 Deploying all changes..." -ForegroundColor Green

# Set non-interactive editor
git config core.editor "cmd /c exit 0"
$env:GIT_EDITOR = "cmd /c exit 0"

# Complete rebase
Write-Host "`n📝 Completing rebase..." -ForegroundColor Yellow
git rebase --continue

# Check status
Write-Host "`n✅ Git status:" -ForegroundColor Cyan
git status

# Push to deploy
Write-Host "`n🚀 Pushing to origin/main..." -ForegroundColor Green
git push origin main

Write-Host "`n✅ Deployment initiated! Render will automatically deploy." -ForegroundColor Green
Write-Host "`n📊 Check your Render dashboard for deployment status." -ForegroundColor Yellow

