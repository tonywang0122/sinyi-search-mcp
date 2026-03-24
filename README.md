# 買屋快搜

房屋物件搜尋 MCP Server — 讓 Claude 幫你找房子。

## 一鍵安裝

**macOS / Linux：**
```bash
curl -LsSf https://raw.githubusercontent.com/tonywang0122/house-search-mcp/main/install.sh | bash
```

**Windows (PowerShell)：**
```powershell
irm https://raw.githubusercontent.com/tonywang0122/house-search-mcp/main/install.ps1 | iex
```

> 如果遇到 ExecutionPolicy 錯誤：
> ```powershell
> # 方法 A：只對這次生效（推薦）
> powershell -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/tonywang0122/house-search-mcp/main/install.ps1 | iex"
>
> # 方法 B：永久放行（需管理員權限）
> Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
> # 然後重跑安裝指令
> ```

自動偵測並設定：Claude Desktop（含 Store 版）+ Codex CLI。
安裝完成後，重啟應用即可使用。

## 功能

- **house_search** — 搜尋物件列表（城市、行政區、房數、價格、坪數、屋齡等篩選）
- **house_get_detail** — 查詢單一物件完整明細（座向、建築結構、生活圈步行距離、管理費等）

## 使用方式

直接在 Claude 對話中說：

- 「幫我找板橋三房 預算一千八」
- 「台中西屯有什麼降價的三房大樓嗎」
- 「查一下這間物件的明細：1083GN」

## 手動安裝

如果一鍵安裝失敗，可以手動設定：

1. 安裝 [uv](https://docs.astral.sh/uv/)
2. 編輯 Claude Desktop 設定檔：
   - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - Windows: `%APPDATA%\Claude\claude_desktop_config.json`
3. 加入：
```json
{
  "mcpServers": {
    "買屋快搜": {
      "command": "uvx",
      "args": ["house-search-mcp"]
    }
  }
}
```
4. 重啟 Claude Desktop
