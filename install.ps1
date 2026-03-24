# sinyi-search-mcp 一鍵安裝腳本 (Windows)
# 用法: powershell -c "irm https://raw.githubusercontent.com/tonywang0122/sinyi-search-mcp/main/install.ps1 | iex"

$PACKAGE = "sinyi-search-mcp"
$SERVER_NAME = "買屋快搜 (by 信義房屋)"

Write-Host ""
Write-Host "🏠 $PACKAGE 安裝程式" -ForegroundColor Cyan
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor DarkGray
Write-Host ""

# ── Step 1: 檢查 / 安裝 uv ──────────────────────────────────

$uvPath = Get-Command uv -ErrorAction SilentlyContinue
if ($uvPath) {
    $uvVersion = & uv --version 2>&1
    Write-Host "✓ uv 已安裝 ($uvVersion)" -ForegroundColor Green
} else {
    Write-Host "→ 安裝 uv..." -ForegroundColor Yellow
    irm https://astral.sh/uv/install.ps1 | iex
    # 刷新 PATH
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "User") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $uvPath = Get-Command uv -ErrorAction SilentlyContinue
    if ($uvPath) {
        Write-Host "✓ uv 安裝成功" -ForegroundColor Green
    } else {
        Write-Host "✗ uv 安裝失敗，請手動安裝: https://docs.astral.sh/uv/" -ForegroundColor Red
        exit 1
    }
}

# ── Step 2: 取得 uvx 完整路徑 ────────────────────────────────

$uvxPath = (Get-Command uvx -ErrorAction SilentlyContinue).Source
if (-not $uvxPath) {
    # uvx 可能跟 uv 同目錄
    $uvDir = Split-Path (Get-Command uv).Source
    $uvxPath = Join-Path $uvDir "uvx.exe"
    if (-not (Test-Path $uvxPath)) {
        $uvxPath = "uvx"
    }
}
Write-Host "✓ uvx 路徑: $uvxPath" -ForegroundColor Green

# ── Step 3: 找到 Claude Desktop 設定檔 ───────────────────────

$configDir = Join-Path $env:APPDATA "Claude"
$configFile = Join-Path $configDir "claude_desktop_config.json"

if (-not (Test-Path $configDir)) {
    New-Item -ItemType Directory -Path $configDir -Force | Out-Null
    Write-Host "→ 建立目錄: $configDir" -ForegroundColor Yellow
}

# ── Step 4: 更新設定檔 ───────────────────────────────────────

$newServer = @{
    command = $uvxPath
    args = @($PACKAGE)
}

if (Test-Path $configFile) {
    $config = Get-Content $configFile -Raw | ConvertFrom-Json

    # 確保 mcpServers 存在
    if (-not $config.mcpServers) {
        $config | Add-Member -NotePropertyName "mcpServers" -NotePropertyValue ([PSCustomObject]@{})
    }

    # 新增或更新 server
    if ($config.mcpServers.PSObject.Properties[$SERVER_NAME]) {
        $config.mcpServers.$SERVER_NAME = [PSCustomObject]$newServer
        Write-Host "→ 已更新 $SERVER_NAME" -ForegroundColor Yellow
    } else {
        $config.mcpServers | Add-Member -NotePropertyName $SERVER_NAME -NotePropertyValue ([PSCustomObject]$newServer)
        Write-Host "→ 已新增 $SERVER_NAME" -ForegroundColor Yellow
    }

    $config | ConvertTo-Json -Depth 10 | Set-Content $configFile -Encoding UTF8
} else {
    $config = @{
        mcpServers = @{
            $SERVER_NAME = $newServer
        }
    }
    $config | ConvertTo-Json -Depth 10 | Set-Content $configFile -Encoding UTF8
    Write-Host "→ 已建立: $configFile" -ForegroundColor Yellow
}

Write-Host "✓ 設定檔已更新" -ForegroundColor Green

# ── Step 5: 完成 ─────────────────────────────────────────────

Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor DarkGray
Write-Host "✓ 安裝完成！" -ForegroundColor Green
Write-Host ""
Write-Host "📋 下一步："
Write-Host "  1. 完全退出 Claude Desktop（系統匣也要關）"
Write-Host "  2. 重新開啟 Claude Desktop"
Write-Host '  3. 開始對話：「幫我找板橋三房 預算一千八」'
Write-Host ""
Write-Host "🔧 如果遇到問題："
Write-Host "  設定檔位置: $configFile"
Write-Host ""
