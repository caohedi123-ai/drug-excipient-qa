"""Espacenet (EPO 欧洲专利局) 工具 - 全球专利

Espacenet OPS 需 OAuth token，不稳定；统一用 AnySearch ip 领域 + sub_domain=patent 兜底。
"""

import json
import asyncio

from langchain_core.tools import tool
from agent.state import Citation, SearchResult
from tools.engines.anysearch_engine import anysearch_vertical


@tool
async def espacenet_tool(query: str) -> str:
    """查询全球药物/辅料相关专利（Espacenet/EPO）：化合物专利、制剂工艺专利、晶型专利。
    适用场景：查询药物或辅料的全球专利布局、同族专利、法律状态。
    Input: 药物名/化合物名/工艺关键词（英文更佳）"""
    result = await _search_espacenet(query)
    if not result.success:
        return f"[Espacenet] 未找到 '{query}' 的相关专利信息。"
    citations_json = json.dumps([c.to_dict() for c in result.citations], ensure_ascii=False)
    return f"[Espacenet] {result.content}\n\n__citations__: {citations_json}"


async def _search_espacenet(query: str) -> SearchResult:
    result = await asyncio.to_thread(anysearch_vertical, query + " patent", domain="ip", sub_domain="patent", max_results=8)
    if not result.success or "No results" in result.content:
        return SearchResult.empty("Espacenet", "搜索无结果")
    return SearchResult(source_name="Espacenet", content=result.content[:2200], citations=result.citations, success=True)
