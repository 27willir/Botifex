# Complete rebase and deploy script
Write-Host "🚀 Completing deployment..." -ForegroundColor Green

# Set non-interactive editor
$env:GIT_EDITOR = "cmd /c exit 0"
git config core.editor "cmd /c exit 0"

# Try to complete rebase
Write-Host "`n📝 Attempting to complete rebase..." -ForegroundColor Yellow
git rebase --continue

# If rebase is complete, check status
Write-Host "`n✅ Checking status..." -ForegroundColor Yellow
git status

# Push to deploy
Write-Host "`n🚀 Pushing to deploy..." -ForegroundColor Green
git push origin main

Write-Host "`n✅ Deployment complete!" -ForegroundColor Green

