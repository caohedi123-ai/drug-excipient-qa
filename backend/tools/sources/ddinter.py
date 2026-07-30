"""DDInter 药物相互作用数据库工具 - 药物-药物相互作用

无公开 API，使用 AnySearch health 垂直领域搜索兜底。
"""

import json
import asyncio

from langchain_core.tools import tool
from agent.state import Citation, SearchResult
from tools.engines.anysearch_engine import anysearch_vertical


@tool
async def ddinter_tool(query: str) -> str:
    """查询药物-药物相互作用(DDI)：联用风险、机制、严重程度分级。
    适用场景：查询两种或多种药物联用时的相互作用、禁忌、风险提示。
    Input: 药物组合，如 "warfarin aspirin interaction" """
    result = await _search_ddinter(query)
    if not result.success:
        return f"[DDInter] 未找到 '{query}' 的相互作用信息。"
    citations_json = json.dumps([c.to_dict() for c in result.citations], ensure_ascii=False)
    return f"[DDInter] {result.content}\n\n__citations__: {citations_json}"


async def _search_ddinter(query: str) -> SearchResult:
    result = await asyncio.to_thread(anysearch_vertical, query + " drug interaction", domain="health", max_results=8)
    if not result.success or "No results" in result.content:
        return SearchResult.empty("DDInter", "搜索无结果")
    return SearchResult(source_name="DDInter", content=result.content[:2200], citations=result.citations, success=True)
