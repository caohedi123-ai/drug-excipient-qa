"""PharmGKB 工具 - 药物基因组学

无简单稳定免费 REST，统一用 AnySearch health 垂直领域搜索兜底。
"""

import json
import asyncio
from langchain_core.tools import tool
from agent.state import Citation, SearchResult
from tools.engines.anysearch_engine import anysearch_vertical


@tool
async def pharmgkb_tool(query: str) -> str:
    """查询药物基因组学证据（PharmGKB 风格）：基因-药物关联、CPIC 指南、变异影响。
    适用场景：查询药物代谢基因多态性、个体化用药、基因型-表型关联。
    Input: 药物名/基因名（英文更佳）"""
    result = await _search_pharmgkb(query)
    if not result.success:
        return f"[PharmGKB] 未找到 '{query}' 的相关信息。"
    citations_json = json.dumps([c.to_dict() for c in result.citations], ensure_ascii=False)
    return f"[PharmGKB] {result.content}\n\n__citations__: {citations_json}"


async def _search_pharmgkb(query: str) -> SearchResult:
    result = await asyncio.to_thread(anysearch_vertical, query + " pharmacogenomics CPIC", domain="health", max_results=8)
    if not result.success or "No results" in result.content:
        return SearchResult.empty("PharmGKB", "搜索无结果")
    return SearchResult(source_name="PharmGKB", content=result.content[:2200], citations=result.citations, success=True)
