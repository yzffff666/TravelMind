# 将本地 TravelMind 推送到 https://github.com/yzffff666/TravelMind
# 用法：在 PowerShell 中执行
#   cd 本仓库根目录（与 llm_backend、README.md 同级）
#   .\scripts\push-to-github.ps1
#
# 前置：已安装 Git for Windows，且已登录 GitHub（HTTPS 凭据或 SSH）。

$ErrorActionPreference = "Stop"
$RemoteUrl = "https://github.com/yzffff666/TravelMind.git"

$git = Get-Command git -ErrorAction SilentlyContinue
if (-not $git) {
    Write-Host "未找到 git。请先安装: https://git-scm.com/download/win" -ForegroundColor Red
    exit 1
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot
Write-Host "仓库根目录: $RepoRoot" -ForegroundColor Cyan

if (-not (Test-Path (Join-Path $RepoRoot ".git"))) {
    git init
    Write-Host "已执行 git init" -ForegroundColor Green
}

$remotes = git remote 2>$null
if ($remotes -notcontains "origin") {
    git remote add origin $RemoteUrl
    Write-Host "已添加 remote origin" -ForegroundColor Green
} else {
    git remote set-url origin $RemoteUrl
    Write-Host "已更新 remote origin 为官方仓库" -ForegroundColor Green
}

git add -A
$status = git status --porcelain
if ($status) {
    git commit -m "chore: sync local workspace"
} else {
    Write-Host "工作区无新变更；若尚未有任何提交，将创建空提交以便推送。" -ForegroundColor Yellow
    git rev-parse HEAD 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        git commit --allow-empty -m "chore: initial sync"
    }
}

git branch -M main 2>$null

# 若远端已有提交，先拉取合并（避免非快进被拒绝）
git fetch origin 2>&1 | Out-Host
if ($LASTEXITCODE -eq 0) {
    git rev-parse "origin/main" 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "检测到远端 main，尝试与本地合并（允许无关历史）..." -ForegroundColor Cyan
        git pull origin main --allow-unrelated-histories --no-edit 2>&1 | Out-Host
        if ($LASTEXITCODE -ne 0) {
            Write-Host "自动合并失败，请在仓库目录手动执行 git status，解决冲突后再 push。" -ForegroundColor Red
            exit 1
        }
    }
} else {
    Write-Host "git fetch 失败（可能无网络或尚未配置凭据），将直接尝试 push ..." -ForegroundColor Yellow
}

Write-Host "正在推送到 origin main ..." -ForegroundColor Cyan
git push -u origin main
if ($LASTEXITCODE -eq 0) {
    Write-Host "推送成功: $RemoteUrl" -ForegroundColor Green
} else {
    Write-Host "推送失败。请检查：1) GitHub 登录/PAT 2) 对该仓库的写权限 3) 网络" -ForegroundColor Red
    exit 1
}
