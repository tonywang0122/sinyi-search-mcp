#!/usr/bin/env bash
# 快速產生市場分析報表
cd "$(dirname "$0")"
.venv/bin/python -m house_search_mcp.report "$@"
