"""SIDER 药品副作用知识库工具 - 药物不良反应

无公开 API，使用 AnySearch health + academic 双重领域搜索。
"""

import json
import asyncio

from langchain_core.tools import tool
from agent.state import Citation, SearchResult
from tools.engines.anysearch_engine import anysearch_vertical


@tool
async def sider_tool(query: str) -> str:
    """查询药物不良反应(ADR)、副作用频率、目标器官系统信息（SIDER 风格）。
    适用场景：查询药物已知副作用、不良反应信号、用药安全警示。
    Input: 药物名（英文更佳）"""
    result = await _search_sider(query)
    if not result.success:
        return f"[SIDER] 未找到 '{query}' 的副作用信息。"
    citations_json = json.dumps([c.to_dict() for c in result.citations], ensure_ascii=False)
    return f"[SIDER] {result.content}\n\n__citations__: {citations_json}"


async def _search_sider(query: str) -> SearchResult:
    r1 = await asyncio.to_thread(anysearch_vertical, query + " side effects adverse reactions", domain="health", max_results=6)
    r2 = await asyncio.to_thread(anysearch_vertical, query + " adverse drug reaction frequency", domain="academic", max_results=6)
    citations = list(r1.citations) + list(r2.citations)
    content = "\n\n".join([r1.content, r2.content])
    if "No results" in r1.content and "No results" in r2.content:
        return SearchResult.empty("SIDER", "搜索无结果")
    return SearchResult(source_name="SIDER", content=content[:2600], citations=citations, success=True)
