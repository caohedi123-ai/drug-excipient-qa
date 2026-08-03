"""CDE (国家药品审评中心) 工具 - 中国药品注册

无公开 API，使用 AnySearch health 垂直领域搜索
"""

import json
import asyncio

from langchain_core.tools import tool
from agent.state import SearchResult
from tools.engines.anysearch_engine import anysearch_vertical


@tool
async def cde_tool(query: str) -> str:
    """查询中国药品注册审评信息：CDE审评进度、受理号、注册分类。
    适用场景：查询中国NMPA/CDE药品注册状态、审评序列。
    Input: 药品名/受理号（中文）"""
    result = await _search_cde(query)
    if not result.success:
        return f"[CDE] 未找到 '{query}' 的相关信息（请确认药品名或受理号）。"

    citations_json = json.dumps([c.to_dict() for c in result.citations], ensure_ascii=False)
    return f"[CDE] {result.content}\n\n__citations__: {citations_json}"


async def _search_cde(query: str) -> SearchResult:
    # 结论式检索：直接问批准/上市/参比制剂/受理号，而非泛搜"药品审评"新闻流。
    # 注意：不用 freshness="past_year"，附条件批准/参比制剂结论常早于一年。
    return await asyncio.to_thread(anysearch_vertical,
        f"{query} 国家药监局 NMPA 批准上市 受理号 参比制剂",
        domain="health",
        max_results=8,
    )
