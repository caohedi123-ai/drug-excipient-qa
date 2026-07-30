"""ICH 国际人用药品技术要求协调会工具 - 指导原则

无公开 API，使用 AnySearch health + academic 双重领域搜索（指导原则文献）。
"""

import json
import asyncio

from langchain_core.tools import tool
from agent.state import Citation, SearchResult
from tools.engines.anysearch_engine import anysearch_vertical


@tool
async def ich_tool(query: str) -> str:
    """查询 ICH 指导原则（质量 Q / 安全 S /  efficacy E / 多学科 M 系列）。
    适用场景：查询原辅料相关的 GMP、稳定性、杂质、遗传毒性等指导原则要求。
    Input: 指导原则主题，如 "ICH Q3A impurities" """
    result = await _search_ich(query)
    if not result.success:
        return f"[ICH] 未找到 '{query}' 的相关指导原则。"
    citations_json = json.dumps([c.to_dict() for c in result.citations], ensure_ascii=False)
    return f"[ICH] {result.content}\n\n__citations__: {citations_json}"


async def _search_ich(query: str) -> SearchResult:
    r1 = await asyncio.to_thread(anysearch_vertical, query + " ICH guideline", domain="health", max_results=6)
    r2 = await asyncio.to_thread(anysearch_vertical, query + " ICH guidance document", domain="academic", max_results=6)
    citations = list(r1.citations) + list(r2.citations)
    content = "\n\n".join([r1.content, r2.content])
    if "No results" in r1.content and "No results" in r2.content:
        return SearchResult.empty("ICH", "搜索无结果")
    return SearchResult(source_name="ICH", content=content[:2600], citations=citations, success=True)
