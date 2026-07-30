"""TTD (治疗靶点数据库) 工具 - 疾病治疗靶点

无公开 API，使用 AnySearch health 垂直领域搜索兜底。
"""

import json
import asyncio

from langchain_core.tools import tool
from agent.state import Citation, SearchResult
from tools.engines.anysearch_engine import anysearch_vertical


@tool
async def ttd_tool(query: str) -> str:
    """查询疾病治疗靶点、靶点-药物关联、可药性蛋白信息（TTD 风格）。
    适用场景：查询某疾病/药物的已知治疗靶点、靶点机制、生物标志物。
    Input: 靶点名/疾病名（英文更佳）"""
    result = await _search_ttd(query)
    if not result.success:
        return f"[TTD] 未找到 '{query}' 的相关靶点信息。"
    citations_json = json.dumps([c.to_dict() for c in result.citations], ensure_ascii=False)
    return f"[TTD] {result.content}\n\n__citations__: {citations_json}"


async def _search_ttd(query: str) -> SearchResult:
    result = await asyncio.to_thread(anysearch_vertical, query + " therapeutic target", domain="health", max_results=8)
    if not result.success or "No results" in result.content:
        return SearchResult.empty("TTD", "搜索无结果")
    return SearchResult(source_name="TTD", content=result.content[:2200], citations=result.citations, success=True)
