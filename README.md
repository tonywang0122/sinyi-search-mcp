# 買屋快搜

信義房屋物件搜尋工具，分為兩個套件：

| 套件 | 功能 | 安裝 |
|------|------|------|
| **house-search-mcp** | MCP Server，讓 AI 幫你找房子 | `uvx house-search-mcp` |
| **house-search-tools** | 批次爬取全台物件 + 產生市場分析 HTML 報表 | `pip install house-search-tools` |

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

開啟終端機（macOS: Terminal / Windows: PowerShell），貼上：

```bash
uv cache clean house-search-mcp
```

然後重啟 Claude Desktop / Codex CLI，會自動下載最新版。

## 功能

- **house_search** — 搜尋物件列表（城市、行政區、房數、價格、坪數、屋齡等篩選）
  - 回傳：總價、單價、原始開價、降價幅度、格局、加蓋格局、樓層、屋齡、建物/主建物/土地面積、車位、陽台/景觀/影片/3DVR 旗標、首圖/大圖 URL、標籤、關注人數、社區、座標、分享連結
  - 統計摘要：新上架數、新降價數、熱門數、熱門成交數、最佳價格數
- **house_get_detail** — 查詢單一物件完整明細
  - 完整價格（總價/單價/土地單價/開價/降幅）、詳細格局（房/廳/衛/開放式）、座向（房屋/大樓/窗戶/土地）、建築結構、面積明細、管理方式與月管理費、經紀人賣點描述、物件照片 URL 列表、格局圖、3D 格局圖、地圖圖片、VR 看屋連結、AI 導覽、影片、語音導覽、周邊生活圈步行距離、經紀人完整資訊、門市、經緯度座標

## 資料爬取 & 市場分析報表（house-search-tools）

### 安裝

```bash
pip install house-search-tools
# 或在本 repo 開發環境：
pip install ./tools
```

### 爬取全地理區物件

```bash
house-search-crawler                              # 互動選城市（含完整明細）
house-search-crawler --cities Taipei NewTaipei    # 指定城市
house-search-crawler --list-only                  # 只抓搜尋列表（快速）
house-search-crawler --enrich data/20260331.db    # 對已有 DB 補抓明細
```

預設會對每筆物件呼叫 detail API 取得完整欄位（單價、座向、結構、管理費、經紀人等）。
資料存入 `data/<yyyymmdd>.db`（SQLite，102 個欄位），涵蓋全台 22 個城市。

### 產生市場分析報表

```bash
house-search-report                               # 自動偵測最新 DB
house-search-report --db data/20260331.db         # 指定 DB
house-search-report --cities Taipei NewTaipei     # 只分析特定城市
```

產生自包含 HTML 報表（`report_<yyyymmdd>.html`），包含：
- **Executive Summary** — KPI 卡片（物件總數、平均單價、平均總價、管理費、新上架、新降價）
- **全台市場總覽** — 各城市物件數量、均價、均單價、管理費、降價比例
- **行政區產銷分析** — 每城市各行政區熱力表（單價/關注度）+ 價格分佈圖 + 管理費
- **委託售屋分析** — 物件類型環狀圖 + 行政區降價分析
- **市場熱度 & 物件特徵** — 關注度排名 + 3DVR/影片/車位/陽台/景觀採用率
- **深度交叉分析**（需 detail 資料）— 座向×單價、建築結構×單價、管理方式×管理費、房數×均價×坪數、屋齡×單價、邊間/暗房比較、門市委售排名
- **標籤熱度分析** — 全台 + 各城市 Top 標籤

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
