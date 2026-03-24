# sinyi-search-mcp

台灣房屋物件搜尋 MCP Server — 搜尋信義房屋物件，供 Claude Desktop / Claude Code 使用。

## 安裝

```bash
# Claude Desktop config (~/.config/claude/claude_desktop_config.json)
{
  "mcpServers": {
    "sinyi-search": {
      "command": "uvx",
      "args": ["sinyi-search-mcp"]
    }
  }
}
```

## Tools

- `sinyi_search` — 搜尋物件列表（城市、行政區、房數、價格、坪數等篩選）
- `sinyi_get_detail` — 查詢單一物件完整明細（座向、結構、生活圈步行距離等）
