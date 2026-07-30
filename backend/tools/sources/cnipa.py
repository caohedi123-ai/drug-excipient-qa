"""CNIPA 国家知识产权局工具 - 中国专利

无公开 API，使用 AnySearch ip 领域 + sub_domain=patent 搜索兜底。
"""

import json
import asyncio

from langchain_core.tools import tool
from agent.state import Citation, SearchResult
from tools.engines.anysearch_engine import anysearch_vertical


@tool
async def cnipa_tool(query: str) -> str:
    """查询中国专利（CNIPA）中的药物/辅料相关发明专利、制剂工艺专利。
    适用场景：查询药物或辅料的中国专利布局、制备方法专利、晶型专利。
    Input: 药物名/化合物名/工艺关键词（中英文均可）"""
    result = await _search_cnipa(query)
    if not result.success:
        return f"[CNIPA] 未找到 '{query}' 的相关专利信息。"
    citations_json = json.dumps([c.to_dict() for c in result.citations], ensure_ascii=False)
    return f"[CNIPA] {result.content}\n\n__citations__: {citations_json}"


async def _search_cnipa(query: str) -> SearchResult:
    result = await asyncio.to_thread(anysearch_vertical, query + " 专利", domain="ip", sub_domain="patent", max_results=8)
    if not result.success or "No results" in result.content:
        return SearchResult.empty("CNIPA", "搜索无结果")
    return SearchResult(source_name="CNIPA", content=result.content[:2200], citations=result.citations, success=True)
