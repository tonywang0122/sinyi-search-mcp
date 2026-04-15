#!/usr/bin/env bash
# 快速啟動爬取工具
cd "$(dirname "$0")"
.venv/bin/python -m house_search_mcp.crawler "$@"
