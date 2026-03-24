# sinyi-search-mcp 一鍵安裝腳本 (Windows)
# 用法: irm https://raw.githubusercontent.com/tonywang0122/sinyi-search-mcp/main/install.ps1 | iex

$ErrorActionPreference = "Stop"

$PACKAGE = "sinyi-search-mcp"
$SERVER_NAME = "買屋快搜 (by 信義房屋)"

Write-Host ""
Write-Host "===============================" -ForegroundColor Cyan
Write-Host "  sinyi-search-mcp installer"  -ForegroundColor Cyan
Write-Host "===============================" -ForegroundColor Cyan
Write-Host ""

# ── Step 1: 檢查 / 安裝 uv ──────────────────────────────────

Write-Host "[Step 1/5] 檢查 uv..." -ForegroundColor White

try {
    $uvCmd = Get-Command uv -ErrorAction Stop
    $uvVersion = & uv --version 2>&1
    Write-Host "  [OK] uv 已安裝: $uvVersion" -ForegroundColor Green
    Write-Host "  [OK] uv 路徑: $($uvCmd.Source)" -ForegroundColor Green
} catch {
    Write-Host "  [INFO] uv 未安裝，開始安裝..." -ForegroundColor Yellow
    try {
        irm https://astral.sh/uv/install.ps1 | iex
        Write-Host "  [OK] uv 安裝指令已執行" -ForegroundColor Green
    } catch {
        Write-Host "  [FAIL] uv 安裝失敗: $_" -ForegroundColor Red
        Write-Host "  請手動安裝: https://docs.astral.sh/uv/" -ForegroundColor Red
        Read-Host "按 Enter 結束"
        exit 1
    }
    # 刷新 PATH
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "User") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    Write-Host "  [INFO] PATH 已刷新" -ForegroundColor Yellow
    try {
        $uvCmd = Get-Command uv -ErrorAction Stop
        Write-Host "  [OK] uv 安裝成功: $($uvCmd.Source)" -ForegroundColor Green
    } catch {
        Write-Host "  [FAIL] uv 安裝後仍找不到，請重開終端機再試" -ForegroundColor Red
        Read-Host "按 Enter 結束"
        exit 1
    }
}

# ── Step 2: 取得 uvx 路徑 ────────────────────────────────────

Write-Host ""
Write-Host "[Step 2/5] 取得 uvx 路徑..." -ForegroundColor White

$uvxPath = $null
try {
    $uvxCmd = Get-Command uvx -ErrorAction Stop
    $uvxPath = $uvxCmd.Source
    Write-Host "  [OK] uvx 找到: $uvxPath" -ForegroundColor Green
} catch {
    Write-Host "  [INFO] uvx 不在 PATH，嘗試從 uv 同目錄找..." -ForegroundColor Yellow
    try {
        $uvDir = Split-Path (Get-Command uv -ErrorAction Stop).Source
        $candidate = Join-Path $uvDir "uvx.exe"
        Write-Host "  [INFO] 嘗試路徑: $candidate" -ForegroundColor Yellow
        if (Test-Path $candidate) {
            $uvxPath = $candidate
            Write-Host "  [OK] uvx 找到: $uvxPath" -ForegroundColor Green
        } else {
            Write-Host "  [INFO] $candidate 不存在" -ForegroundColor Yellow
            # 再試 uv 本身（新版 uv 整合了 uvx 功能）
            $uvxPath = (Get-Command uv).Source
            Write-Host "  [INFO] 改用 uv 路徑: $uvxPath (將用 uv tool run 替代)" -ForegroundColor Yellow
        }
    } catch {
        Write-Host "  [FAIL] 找不到 uvx 也找不到 uv: $_" -ForegroundColor Red
        Read-Host "按 Enter 結束"
        exit 1
    }
}

# ── Step 3: 找到 Claude Desktop 設定檔 ───────────────────────

Write-Host ""
Write-Host "[Step 3/5] 找到 Claude Desktop 設定檔..." -ForegroundColor White

$configDir = Join-Path $env:APPDATA "Claude"
$configFile = Join-Path $configDir "claude_desktop_config.json"

Write-Host "  [INFO] APPDATA: $env:APPDATA" -ForegroundColor Yellow
Write-Host "  [INFO] 設定檔目錄: $configDir" -ForegroundColor Yellow
Write-Host "  [INFO] 設定檔路徑: $configFile" -ForegroundColor Yellow

if (-not (Test-Path $configDir)) {
    New-Item -ItemType Directory -Path $configDir -Force | Out-Null
    Write-Host "  [OK] 目錄已建立" -ForegroundColor Green
} else {
    Write-Host "  [OK] 目錄已存在" -ForegroundColor Green
}

if (Test-Path $configFile) {
    $existingContent = Get-Content $configFile -Raw -ErrorAction SilentlyContinue
    Write-Host "  [INFO] 現有設定檔內容:" -ForegroundColor Yellow
    Write-Host $existingContent -ForegroundColor DarkGray
} else {
    Write-Host "  [INFO] 設定檔不存在，將建立新檔" -ForegroundColor Yellow
}

# ── Step 4: 更新設定檔 ───────────────────────────────────────

Write-Host ""
Write-Host "[Step 4/5] 更新設定檔..." -ForegroundColor White

# 決定 command 和 args
if ($uvxPath -match "uvx") {
    $serverCommand = $uvxPath
    $serverArgs = @("--from", "git+https://github.com/tonywang0122/sinyi-search-mcp", $PACKAGE)
} else {
    # 用 uv tool run 替代 uvx
    $serverCommand = $uvxPath
    $serverArgs = @("tool", "run", $PACKAGE)
}

Write-Host "  [INFO] MCP command: $serverCommand" -ForegroundColor Yellow
Write-Host "  [INFO] MCP args: $($serverArgs -join ' ')" -ForegroundColor Yellow

try {
    if (Test-Path $configFile) {
        $raw = Get-Content $configFile -Raw
        Write-Host "  [INFO] 讀取現有設定檔成功 ($($raw.Length) bytes)" -ForegroundColor Yellow
        $config = $raw | ConvertFrom-Json
        Write-Host "  [OK] JSON 解析成功" -ForegroundColor Green

        # 確保 mcpServers 存在
        if (-not $config.mcpServers) {
            Write-Host "  [INFO] mcpServers 不存在，新增..." -ForegroundColor Yellow
            $config | Add-Member -NotePropertyName "mcpServers" -NotePropertyValue ([PSCustomObject]@{})
        }

        # 新增或更新 server
        $newServer = [PSCustomObject]@{
            command = $serverCommand
            args = $serverArgs
        }

        if ($config.mcpServers.PSObject.Properties[$SERVER_NAME]) {
            $config.mcpServers.$SERVER_NAME = $newServer
            Write-Host "  [OK] 已更新 '$SERVER_NAME'" -ForegroundColor Green
        } else {
            $config.mcpServers | Add-Member -NotePropertyName $SERVER_NAME -NotePropertyValue $newServer
            Write-Host "  [OK] 已新增 '$SERVER_NAME'" -ForegroundColor Green
        }

        $output = $config | ConvertTo-Json -Depth 10
        Write-Host "  [INFO] 輸出 JSON:" -ForegroundColor Yellow
        Write-Host $output -ForegroundColor DarkGray
        $output | Set-Content $configFile -Encoding UTF8
        Write-Host "  [OK] 設定檔已寫入" -ForegroundColor Green
    } else {
        Write-Host "  [INFO] 建立新設定檔..." -ForegroundColor Yellow
        $config = @{
            mcpServers = @{
                $SERVER_NAME = @{
                    command = $serverCommand
                    args = $serverArgs
                }
            }
        }
        $output = $config | ConvertTo-Json -Depth 10
        Write-Host "  [INFO] 輸出 JSON:" -ForegroundColor Yellow
        Write-Host $output -ForegroundColor DarkGray
        $output | Set-Content $configFile -Encoding UTF8
        Write-Host "  [OK] 新設定檔已建立" -ForegroundColor Green
    }
} catch {
    Write-Host "  [FAIL] 設定檔更新失敗: $_" -ForegroundColor Red
    Write-Host "  [FAIL] 錯誤詳情: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  [FAIL] 錯誤位置: $($_.InvocationInfo.PositionMessage)" -ForegroundColor Red
    Read-Host "按 Enter 結束"
    exit 1
}

# ── Step 5: 驗證 ─────────────────────────────────────────────

Write-Host ""
Write-Host "[Step 5/5] 驗證..." -ForegroundColor White

if (Test-Path $configFile) {
    $finalContent = Get-Content $configFile -Raw
    Write-Host "  [INFO] 最終設定檔內容:" -ForegroundColor Yellow
    Write-Host $finalContent -ForegroundColor DarkGray
    if ($finalContent -match $PACKAGE) {
        Write-Host "  [OK] 設定檔包含 $PACKAGE" -ForegroundColor Green
    } else {
        Write-Host "  [WARN] 設定檔似乎不包含 $PACKAGE" -ForegroundColor Red
    }
} else {
    Write-Host "  [FAIL] 設定檔不存在!" -ForegroundColor Red
}

# ── 完成 ─────────────────────────────────────────────────────

Write-Host ""
Write-Host "===============================" -ForegroundColor Green
Write-Host "  安裝完成！" -ForegroundColor Green
Write-Host "===============================" -ForegroundColor Green
Write-Host ""
Write-Host "下一步："
Write-Host "  1. 完全退出 Claude Desktop（系統匣圖示也要右鍵退出）"
Write-Host "  2. 重新開啟 Claude Desktop"
Write-Host "  3. 開始對話：幫我找板橋三房 預算一千八"
Write-Host ""
Write-Host "設定檔位置: $configFile"
Write-Host ""
Read-Host "按 Enter 結束"
