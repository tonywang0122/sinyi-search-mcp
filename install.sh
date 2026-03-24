#!/usr/bin/env bash
# house-search-mcp 一鍵安裝腳本（Claude Desktop + Codex CLI）
# 用法: curl -LsSf https://raw.githubusercontent.com/tonywang0122/house-search-mcp/main/install.sh | bash
set -e

PACKAGE="house-search-mcp"
SERVER_NAME="買屋快搜"
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'
INSTALLED=""

echo ""
echo "🏠 ${PACKAGE} 安裝程式"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── Step 1: 檢查 / 安裝 uv ──────────────────────────────────

echo -e "${YELLOW}[Step 1]${NC} 檢查 uv..."

if command -v uv &>/dev/null; then
    echo -e "  ${GREEN}✓${NC} uv 已安裝 ($(uv --version))"
else
    echo -e "  ${YELLOW}→${NC} 安裝 uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    if command -v uv &>/dev/null; then
        echo -e "  ${GREEN}✓${NC} uv 安裝成功"
    else
        echo -e "  ${RED}✗${NC} uv 安裝失敗，請手動安裝: https://docs.astral.sh/uv/"
        exit 1
    fi
fi

UVX_PATH=$(command -v uvx)
echo -e "  ${GREEN}✓${NC} uvx 路徑: $UVX_PATH"

# ── Step 2: Claude Desktop ───────────────────────────────────

echo ""
echo -e "${YELLOW}[Step 2]${NC} 設定 Claude Desktop..."

if [[ "$OSTYPE" == "darwin"* ]]; then
    CLAUDE_DIR="$HOME/Library/Application Support/Claude"
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    CLAUDE_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/claude"
else
    CLAUDE_DIR=""
fi

if [ -n "$CLAUDE_DIR" ]; then
    CLAUDE_FILE="$CLAUDE_DIR/claude_desktop_config.json"
    mkdir -p "$CLAUDE_DIR"

    if [ -f "$CLAUDE_FILE" ]; then
        python3 -c "
import json
with open('$CLAUDE_FILE', 'r') as f:
    config = json.load(f)
config.setdefault('mcpServers', {})['$SERVER_NAME'] = {
    'command': '$UVX_PATH',
    'args': ['$PACKAGE']
}
with open('$CLAUDE_FILE', 'w') as f:
    json.dump(config, f, indent=2)
"
        echo -e "  ${GREEN}✓${NC} Claude Desktop 設定已更新"
    else
        cat > "$CLAUDE_FILE" << EOF
{
  "mcpServers": {
    "$SERVER_NAME": {
      "command": "$UVX_PATH",
      "args": ["$PACKAGE"]
    }
  }
}
EOF
        echo -e "  ${GREEN}✓${NC} Claude Desktop 設定已建立"
    fi
    echo -e "  ${GREEN}✓${NC} 路徑: $CLAUDE_FILE"
    INSTALLED="${INSTALLED}Claude Desktop, "
else
    echo -e "  ${YELLOW}⊘${NC} 跳過（不支援的 OS: $OSTYPE）"
fi

# ── Step 3: Codex CLI ────────────────────────────────────────

echo ""
echo -e "${YELLOW}[Step 3]${NC} 設定 Codex CLI..."

if command -v codex &>/dev/null; then
    echo -e "  ${GREEN}✓${NC} Codex CLI 已安裝"
    # 用 codex mcp add 指令（如果已存在會報錯，先移除再加）
    codex mcp remove "$SERVER_NAME" 2>/dev/null || true
    codex mcp add "$SERVER_NAME" -- "$UVX_PATH" "$PACKAGE" 2>&1 && {
        echo -e "  ${GREEN}✓${NC} Codex CLI MCP 已設定"
        INSTALLED="${INSTALLED}Codex CLI, "
    } || {
        # fallback: 直接寫 config.toml
        CODEX_CONFIG="$HOME/.codex/config.toml"
        if [ -f "$CODEX_CONFIG" ]; then
            # 檢查是否已有此 server
            if ! grep -q "mcp_servers.${SERVER_NAME}" "$CODEX_CONFIG" 2>/dev/null; then
                cat >> "$CODEX_CONFIG" << EOF

[mcp_servers."$SERVER_NAME"]
command = "$UVX_PATH"
args = ["$PACKAGE"]
EOF
                echo -e "  ${GREEN}✓${NC} Codex config.toml 已更新"
                INSTALLED="${INSTALLED}Codex CLI, "
            else
                echo -e "  ${GREEN}✓${NC} Codex config.toml 已包含此 server"
                INSTALLED="${INSTALLED}Codex CLI, "
            fi
        fi
    }
else
    echo -e "  ${YELLOW}⊘${NC} 跳過（未偵測到 Codex CLI）"
fi

# ── Step 4: ChatGPT Desktop（提示） ──────────────────────────

echo ""
echo -e "${YELLOW}[Step 4]${NC} ChatGPT Desktop..."
echo -e "  ${YELLOW}⊘${NC} ChatGPT Desktop 目前僅支援 remote HTTP MCP，不支援 local stdio"
echo -e "  ${YELLOW}⊘${NC} 待 OpenAI 開放 local MCP 後將自動支援"

# ── 完成 ─────────────────────────────────────────────────────

# 去掉尾部逗號空格
INSTALLED=$(echo "$INSTALLED" | sed 's/, $//')

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${GREEN}✓ 安裝完成！${NC}"
if [ -n "$INSTALLED" ]; then
    echo -e "  已設定: ${GREEN}${INSTALLED}${NC}"
fi
echo ""
echo "📋 下一步："
echo "  1. 重啟 Claude Desktop / Codex CLI"
echo "  2. 開始對話：「幫我找板橋三房 預算一千八」"
echo ""
echo "🔧 如果遇到問題："
if [ -n "$CLAUDE_DIR" ]; then
    echo "  Claude log: tail -20 ~/Library/Logs/Claude/mcp*.log"
    echo "  Claude 設定: $CLAUDE_FILE"
fi
if command -v codex &>/dev/null; then
    echo "  Codex: codex mcp list"
fi
echo ""
