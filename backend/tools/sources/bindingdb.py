"""BindingDB 工具 - 蛋白质-配体结合亲和力

无简单稳定免费 REST，统一用 AnySearch health 垂直领域搜索兜底。
"""

import json
import asyncio
from langchain_core.tools import tool
from agent.state import Citation, SearchResult
from tools.engines.anysearch_engine import anysearch_vertical


@tool
async def bindingdb_tool(query: str) -> str:
    """查询蛋白质-配体结合亲和力数据（BindingDB 风格）：Ki/Kd/IC50、靶点结合。
    适用场景：查询活性成分与靶点的体外结合亲和力、构效关系。
    Input: 化合物名/靶点名（英文更佳）"""
    result = await _search_bindingdb(query)
    if not result.success:
        return f"[BindingDB] 未找到 '{query}' 的相关信息。"
    citations_json = json.dumps([c.to_dict() for c in result.citations], ensure_ascii=False)
    return f"[BindingDB] {result.content}\n\n__citations__: {citations_json}"


async def _search_bindingdb(query: str) -> SearchResult:
    result = await asyncio.to_thread(anysearch_vertical, query + " binding affinity Ki Kd", domain="health", max_results=8)
    if not result.success or "No results" in result.content:
        return SearchResult.empty("BindingDB", "搜索无结果")
    return SearchResult(source_name="BindingDB", content=result.content[:2200], citations=result.citations, success=True)
