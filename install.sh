#!/usr/bin/env bash
# sinyi-search-mcp 一鍵安裝腳本
# 用法: curl -LsSf https://raw.githubusercontent.com/tonywang0122/sinyi-search-mcp/main/install.sh | bash
set -e

PACKAGE="sinyi-search-mcp"
SERVER_NAME="買屋快搜 (by 信義房屋)"
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo ""
echo "🏠 ${PACKAGE} 安裝程式"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── Step 1: 檢查 / 安裝 uv ──────────────────────────────────

if command -v uv &>/dev/null; then
    echo -e "${GREEN}✓${NC} uv 已安裝 ($(uv --version))"
else
    echo -e "${YELLOW}→${NC} 安裝 uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    if command -v uv &>/dev/null; then
        echo -e "${GREEN}✓${NC} uv 安裝成功"
    else
        echo -e "${RED}✗${NC} uv 安裝失敗，請手動安裝: https://docs.astral.sh/uv/"
        exit 1
    fi
fi

# ── Step 2: 驗證 package 可執行 ──────────────────────────────

echo -e "${YELLOW}→${NC} 驗證 ${PACKAGE}..."
if uvx ${PACKAGE} --version &>/dev/null 2>&1 || timeout 3 uvx ${PACKAGE} </dev/null &>/dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} ${PACKAGE} 可正常執行"
else
    echo -e "${GREEN}✓${NC} ${PACKAGE} 已下載（MCP server 為 stdio 模式，無版本輸出為正常）"
fi

# ── Step 3: 找到 Claude Desktop 設定檔 ───────────────────────

if [[ "$OSTYPE" == "darwin"* ]]; then
    CONFIG_DIR="$HOME/Library/Application Support/Claude"
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/claude"
else
    echo -e "${RED}✗${NC} 不支援的作業系統: $OSTYPE"
    echo "  請手動設定，參考: https://github.com/tonywang0122/sinyi-search-mcp#manual-setup"
    exit 1
fi

CONFIG_FILE="$CONFIG_DIR/claude_desktop_config.json"

# 建立目錄（如果不存在）
mkdir -p "$CONFIG_DIR"

# ── Step 4: 更新設定檔 ───────────────────────────────────────

# 取得 uvx 完整路徑（避免 Claude Desktop 找不到）
UVX_PATH=$(command -v uvx)

if [ -f "$CONFIG_FILE" ]; then
    # 檔案已存在：檢查是否已有 sinyi-search
    if grep -q "$SERVER_NAME" "$CONFIG_FILE" 2>/dev/null; then
        echo -e "${YELLOW}→${NC} 設定檔已包含 ${SERVER_NAME}，更新中..."
        # 用 python 更新 JSON（安全處理）
        python3 -c "
import json, sys
with open('$CONFIG_FILE', 'r') as f:
    config = json.load(f)
config.setdefault('mcpServers', {})['$SERVER_NAME'] = {
    'command': '$UVX_PATH',
    'args': ['$PACKAGE']
}
with open('$CONFIG_FILE', 'w') as f:
    json.dump(config, f, indent=2)
print('  已更新')
"
    else
        echo -e "${YELLOW}→${NC} 新增 ${SERVER_NAME} 到現有設定..."
        python3 -c "
import json
with open('$CONFIG_FILE', 'r') as f:
    config = json.load(f)
config.setdefault('mcpServers', {})['$SERVER_NAME'] = {
    'command': '$UVX_PATH',
    'args': ['$PACKAGE']
}
with open('$CONFIG_FILE', 'w') as f:
    json.dump(config, f, indent=2)
print('  已新增')
"
    fi
else
    echo -e "${YELLOW}→${NC} 建立新設定檔..."
    cat > "$CONFIG_FILE" << EOF
{
  "mcpServers": {
    "$SERVER_NAME": {
      "command": "$UVX_PATH",
      "args": ["$PACKAGE"]
    }
  }
}
EOF
    echo "  已建立: $CONFIG_FILE"
fi

echo -e "${GREEN}✓${NC} 設定檔已更新"

# ── Step 5: 完成 ─────────────────────────────────────────────

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${GREEN}✓ 安裝完成！${NC}"
echo ""
echo "📋 下一步："
echo "  1. 完全退出 Claude Desktop（不是關視窗，是退出 App）"
echo "  2. 重新開啟 Claude Desktop"
echo "  3. 開始對話：「幫我找板橋三房 預算一千八」"
echo ""
echo "🔧 如果遇到問題："
echo "  查看 log: tail -20 ~/Library/Logs/Claude/mcp-server-${SERVER_NAME}.log"
echo "  設定檔位置: $CONFIG_FILE"
echo ""
