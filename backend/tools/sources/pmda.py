"""PMDA (日本药品医疗器械综合机构) 工具 - 日本注册审评

无公开稳定 API，使用 AnySearch health 垂直领域搜索兜底。
"""

import json
import asyncio

from langchain_core.tools import tool
from agent.state import Citation, SearchResult
from tools.engines.anysearch_engine import anysearch_vertical


@tool
async def pmda_tool(query: str) -> str:
    """查询日本 PMDA 药品注册审评信息：日本上市许可、审评报告、副作用情报。
    适用场景：查询药物在日本 (PMDA) 的注册状态、审评资料、安全信息。
    Input: 药品名（中英文均可，英文更佳）"""
    result = await _search_pmda(query)
    if not result.success:
        return f"[PMDA] 未找到 '{query}' 的相关信息。"
    citations_json = json.dumps([c.to_dict() for c in result.citations], ensure_ascii=False)
    return f"[PMDA] {result.content}\n\n__citations__: {citations_json}"


async def _search_pmda(query: str) -> SearchResult:
    result = await asyncio.to_thread(anysearch_vertical, query + " PMDA 日本 承認", domain="health", max_results=8)
    if not result.success or "No results" in result.content:
        return SearchResult.empty("PMDA", "搜索无结果")
    return SearchResult(source_name="PMDA", content=result.content[:2200], citations=result.citations, success=True)
