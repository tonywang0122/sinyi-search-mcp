# house-search-mcp 一鍵安裝腳本 (Windows) — Claude Desktop + Codex CLI
# 用法: irm https://raw.githubusercontent.com/tonywang0122/house-search-mcp/main/install.ps1 | iex

$ErrorActionPreference = "Stop"

$PACKAGE = "house-search-mcp"
$SERVER_NAME = "買屋快搜"
$installed = @()

Write-Host ""
Write-Host "===============================" -ForegroundColor Cyan
Write-Host "  house-search-mcp installer"  -ForegroundColor Cyan
Write-Host "===============================" -ForegroundColor Cyan
Write-Host ""

# ── Step 1: 檢查 / 安裝 uv ──────────────────────────────────

Write-Host "[Step 1/4] 檢查 uv..." -ForegroundColor White

try {
    $uvCmd = Get-Command uv -ErrorAction Stop
    $uvVersion = & uv --version 2>&1
    Write-Host "  [OK] uv 已安裝: $uvVersion" -ForegroundColor Green
} catch {
    Write-Host "  [INFO] uv 未安裝，開始安裝..." -ForegroundColor Yellow
    try {
        irm https://astral.sh/uv/install.ps1 | iex
    } catch {
        Write-Host "  [FAIL] uv 安裝失敗: $_" -ForegroundColor Red
        Read-Host "按 Enter 結束"
        exit 1
    }
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "User") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    try {
        Get-Command uv -ErrorAction Stop | Out-Null
        Write-Host "  [OK] uv 安裝成功" -ForegroundColor Green
    } catch {
        Write-Host "  [FAIL] uv 安裝後找不到，請重開終端機再試" -ForegroundColor Red
        Read-Host "按 Enter 結束"
        exit 1
    }
}

# 取得 uvx 路徑
$uvxPath = $null
try { $uvxPath = (Get-Command uvx -ErrorAction Stop).Source } catch {}
if (-not $uvxPath) {
    $uvDir = Split-Path (Get-Command uv).Source
    $candidate = Join-Path $uvDir "uvx.exe"
    if (Test-Path $candidate) { $uvxPath = $candidate }
    else { $uvxPath = (Get-Command uv).Source }
}
Write-Host "  [OK] uvx: $uvxPath" -ForegroundColor Green

# MCP server command/args
if ($uvxPath -match "uvx") {
    $serverCommand = $uvxPath
    $serverArgs = @($PACKAGE)
} else {
    $serverCommand = $uvxPath
    $serverArgs = @("tool", "run", $PACKAGE)
}

# ── Step 2: Claude Desktop ───────────────────────────────────

Write-Host ""
Write-Host "[Step 2/4] 設定 Claude Desktop..." -ForegroundColor White

# 偵測 Store 版 vs 一般安裝版
$storeConfig = Get-Item "$env:LOCALAPPDATA\Packages\Claude_*\LocalCache\Roaming\Claude" -ErrorAction SilentlyContinue
if ($storeConfig) {
    $configDir = $storeConfig.FullName
    Write-Host "  [INFO] 偵測到 Microsoft Store 版" -ForegroundColor Yellow
} else {
    $configDir = Join-Path $env:APPDATA "Claude"
    Write-Host "  [INFO] 偵測到一般安裝版" -ForegroundColor Yellow
}
$configFile = Join-Path $configDir "claude_desktop_config.json"

if (-not (Test-Path $configDir)) {
    New-Item -ItemType Directory -Path $configDir -Force | Out-Null
}

try {
    $newServer = [PSCustomObject]@{ command = $serverCommand; args = $serverArgs }

    if (Test-Path $configFile) {
        $config = Get-Content $configFile -Raw | ConvertFrom-Json
        if (-not $config.mcpServers) {
            $config | Add-Member -NotePropertyName "mcpServers" -NotePropertyValue ([PSCustomObject]@{})
        }
        if ($config.mcpServers.PSObject.Properties[$SERVER_NAME]) {
            $config.mcpServers.$SERVER_NAME = $newServer
        } else {
            $config.mcpServers | Add-Member -NotePropertyName $SERVER_NAME -NotePropertyValue $newServer
        }
        $config | ConvertTo-Json -Depth 10 | Set-Content $configFile -Encoding UTF8
    } else {
        @{ mcpServers = @{ $SERVER_NAME = @{ command = $serverCommand; args = $serverArgs } } } |
            ConvertTo-Json -Depth 10 | Set-Content $configFile -Encoding UTF8
    }
    Write-Host "  [OK] Claude Desktop 設定完成: $configFile" -ForegroundColor Green
    $installed += "Claude Desktop"
} catch {
    Write-Host "  [FAIL] Claude Desktop 設定失敗: $($_.Exception.Message)" -ForegroundColor Red
}

# ── Step 3: Codex CLI ────────────────────────────────────────

Write-Host ""
Write-Host "[Step 3/4] 設定 Codex CLI..." -ForegroundColor White

$codexCmd = Get-Command codex -ErrorAction SilentlyContinue
if ($codexCmd) {
    Write-Host "  [OK] Codex CLI 已安裝: $($codexCmd.Source)" -ForegroundColor Green
    try {
        & codex mcp remove $SERVER_NAME 2>$null
        & codex mcp add $SERVER_NAME -- $uvxPath $PACKAGE 2>&1
        Write-Host "  [OK] Codex CLI MCP 設定完成" -ForegroundColor Green
        $installed += "Codex CLI"
    } catch {
        Write-Host "  [WARN] codex mcp add 失敗，嘗試寫 config.toml..." -ForegroundColor Yellow
        $codexConfig = Join-Path $env:USERPROFILE ".codex\config.toml"
        if (Test-Path $codexConfig) {
            $content = Get-Content $codexConfig -Raw
            if ($content -notmatch "mcp_servers.*$SERVER_NAME") {
                $tomlBlock = "`n[mcp_servers.`"$SERVER_NAME`"]`ncommand = `"$uvxPath`"`nargs = [`"$PACKAGE`"]`n"
                Add-Content $codexConfig $tomlBlock
                Write-Host "  [OK] Codex config.toml 已更新" -ForegroundColor Green
                $installed += "Codex CLI"
            } else {
                Write-Host "  [OK] Codex config.toml 已包含此 server" -ForegroundColor Green
                $installed += "Codex CLI"
            }
        } else {
            Write-Host "  [WARN] Codex config.toml 不存在，跳過" -ForegroundColor Yellow
        }
    }
} else {
    Write-Host "  [SKIP] 未偵測到 Codex CLI" -ForegroundColor DarkGray
}

# ── Step 4: ChatGPT Desktop ─────────────────────────────────

Write-Host ""
Write-Host "[Step 4/4] ChatGPT Desktop..." -ForegroundColor White
Write-Host "  [SKIP] ChatGPT Desktop 目前僅支援 remote HTTP MCP，不支援 local stdio" -ForegroundColor DarkGray

# ── 完成 ─────────────────────────────────────────────────────

Write-Host ""
Write-Host "===============================" -ForegroundColor Green
Write-Host "  安裝完成！" -ForegroundColor Green
Write-Host "===============================" -ForegroundColor Green
if ($installed.Count -gt 0) {
    Write-Host "  已設定: $($installed -join ', ')" -ForegroundColor Green
}
Write-Host ""
Write-Host "下一步："
Write-Host "  1. 重啟 Claude Desktop / Codex CLI"
Write-Host '  2. 開始對話：「幫我找板橋三房 預算一千八」'
Write-Host ""
Write-Host "設定檔:"
Write-Host "  Claude: $configFile"
if ($codexCmd) { Write-Host "  Codex:  codex mcp list" }
Write-Host ""
Read-Host "按 Enter 結束"
