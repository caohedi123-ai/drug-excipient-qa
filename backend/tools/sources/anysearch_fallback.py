"""AnySearch 通用泛搜兜底工具 - 全链路最后一道兜底

设计定位：当专有数据源（PubChem/DrugBank/FDA 等）均无法找到答案时启用。
对任意 query 不限域名泛搜，优先 health 领域，无果再尝试 academic，
确保"配了泛搜就一定用得上"。
"""

import json
import asyncio

from langchain_core.tools import tool
from agent.state import SearchResult
from tools.engines.anysearch_engine import anysearch_batch, anysearch_vertical


@tool
async def anysearch_fallback_tool(query: str) -> str:
    """通用泛搜兜底工具：当其他所有专有数据源（PubChem/DrugBank/FDA/DrugCentral 等）均返回空或不足时，
    对任意问题做不限域名的全网泛搜，覆盖 health/academic/ip 垂直领域。
    适用场景：其他工具均失败时作为最后兜底，保证用户最终拿到有来源的答案而非"未找到"。
    Input: 用户的原始问题或子问题（中英文均可）"""
    # health + academic 合并为 1 次 batch_search（配额友好），不再串行两次
    results = await asyncio.to_thread(anysearch_batch, [
        {"query": query, "domain": "health", "max_results": 10},
        {"query": query, "domain": "academic", "max_results": 10},
    ])
    # 优先取 health，其次 academic
    result = next((r for r in results if getattr(r, "success", False) and r.citations), None)
    if result is None:
        result = results[0] if results else SearchResult(
            source_name="AnySearch", content="No results found.", citations=[])

    if "No results" in result.content and not result.citations:
        return f"[AnySearch兜底] 泛搜未找到 '{query}' 的相关信息。"

    citations_json = json.dumps([c.to_dict() for c in result.citations], ensure_ascii=False)
    return f"[AnySearch兜底] {result.content}\n\n__citations__: {citations_json}"
