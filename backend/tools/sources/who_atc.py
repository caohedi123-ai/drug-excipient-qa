"""WHO ATC 解剖治疗化学分类工具 - 药物分类标准

无公开 API，使用 AnySearch health 垂直领域搜索兜底。
"""

import json
import asyncio

from langchain_core.tools import tool
from agent.state import Citation, SearchResult
from tools.engines.anysearch_engine import anysearch_vertical


@tool
async def who_atc_tool(query: str) -> str:
    """查询 WHO ATC 解剖治疗化学分类代码、药物分类层级、用药统计。
    适用场景：查询药物的 ATC 编码、分类归属、同类药物对照。
    Input: 药物名/分类名（英文更佳）"""
    result = await _search_who_atc(query)
    if not result.success:
        return f"[WHO ATC] 未找到 '{query}' 的分类信息。"
    citations_json = json.dumps([c.to_dict() for c in result.citations], ensure_ascii=False)
    return f"[WHO ATC] {result.content}\n\n__citations__: {citations_json}"


async def _search_who_atc(query: str) -> SearchResult:
    result = await asyncio.to_thread(anysearch_vertical, query + " ATC classification WHO", domain="health", max_results=8)
    if not result.success or "No results" in result.content:
        return SearchResult.empty("WHO ATC", "搜索无结果")
    return SearchResult(source_name="WHO ATC", content=result.content[:2200], citations=result.citations, success=True)
