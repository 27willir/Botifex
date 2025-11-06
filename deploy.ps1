# PowerShell script to complete rebase and deploy
Write-Host "🚀 Completing rebase and deploying..." -ForegroundColor Green

# Set git editor to avoid vim
$env:GIT_EDITOR = "notepad"

# Complete rebase
Write-Host "`n📝 Completing rebase..." -ForegroundColor Yellow
git rebase --continue

# Check status
Write-Host "`n✅ Checking git status..." -ForegroundColor Yellow
git status

# Show what will be deployed
Write-Host "`n📊 Files ready to deploy:" -ForegroundColor Cyan
git log --oneline -1
git diff --stat HEAD~1

Write-Host "`n✅ Ready to push! Run: git push origin main" -ForegroundColor Green

