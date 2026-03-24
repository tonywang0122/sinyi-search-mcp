# 買屋快搜

房屋物件搜尋 MCP Server — 讓 AI 幫你找房子。

支援 Claude Desktop / Codex CLI，以及所有相容 MCP 的 AI 工具。

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

安裝腳本自動偵測並設定：
- **Claude Desktop**（macOS / Windows 一般版 / Store 版）
- **Codex CLI**（macOS / Windows 一般版 / Store 版）

安裝完成後，重啟應用即可使用。

## 升級

```bash
uvx --refresh house-search-mcp
```

然後重啟 Claude Desktop / Codex CLI。

## 功能

- **house_search** — 搜尋物件列表（城市、行政區、房數、價格、坪數、屋齡等篩選）
- **house_get_detail** — 查詢單一物件完整明細（座向、建築結構、生活圈步行距離、管理費等）

## 使用方式

在 AI 對話中直接說：

- 「幫我找板橋三房 預算一千八」
- 「台中西屯有什麼降價的三房大樓嗎」
- 「查一下這間物件的明細：1083GN」

## 手動安裝

如果一鍵安裝失敗，可以手動設定：

1. 安裝 [uv](https://docs.astral.sh/uv/)

2. **Claude Desktop** — 編輯設定檔：
   - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - Windows: `%APPDATA%\Claude\claude_desktop_config.json`（Store 版路徑不同，安裝腳本會自動偵測）
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

3. **Codex CLI** — 執行指令：
   ```bash
   codex mcp add house-search -- uvx house-search-mcp
   ```

4. 重啟應用
