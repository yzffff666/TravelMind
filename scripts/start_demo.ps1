param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 3000,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$BackendDir = Join-Path $RepoRoot "llm_backend"
$FrontendDir = Join-Path $RepoRoot "frontend\DsAgentChat_web"
$Python = Join-Path $BackendDir ".venv312\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    $Python = Join-Path $BackendDir ".venv\Scripts\python.exe"
}
if (-not (Test-Path $Python)) {
    throw "Cannot find backend Python. Expected .venv312 or .venv under llm_backend."
}
if (-not (Test-Path (Join-Path $FrontendDir "node_modules"))) {
    throw "Cannot find frontend node_modules. Run npm install in frontend\DsAgentChat_web first."
}

$BackendCommand = "cd /d `"$BackendDir`"; `"$Python`" -m uvicorn main:app --host 127.0.0.1 --port $BackendPort"
$FrontendCommand = "cd /d `"$FrontendDir`"; npm.cmd run dev -- --host 127.0.0.1 --port $FrontendPort"

Write-Host "Starting TravelMind demo..." -ForegroundColor Cyan
Write-Host "Backend:  http://127.0.0.1:$BackendPort" -ForegroundColor Gray
Write-Host "Frontend: http://127.0.0.1:$FrontendPort" -ForegroundColor Gray

Start-Process powershell.exe -ArgumentList "-NoExit", "-Command", $BackendCommand
Start-Sleep -Seconds 3
Start-Process powershell.exe -ArgumentList "-NoExit", "-Command", $FrontendCommand

if (-not $NoBrowser) {
    Start-Sleep -Seconds 5
    Start-Process "http://127.0.0.1:$FrontendPort"
}

Write-Host ""
Write-Host "Demo prompts:" -ForegroundColor Cyan
Write-Host "1. 帮我规划 3 天成都亲子游，预算中等，节奏轻松"
Write-Host "2. 第 2 天安排是什么？"
Write-Host "3. 把第二天下午改成更轻松的室内活动"
Write-Host ""
Write-Host "If anything is slow, use docs\demo\导师演示小抄.md as the fallback script." -ForegroundColor Yellow
