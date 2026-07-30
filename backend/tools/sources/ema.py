"""EMA (欧洲药品管理局) 工具 - 欧盟注册审评

无公开稳定 REST，使用 Tavily 域名定向 (ema.europa.eu) + AnySearch health 兜底。
"""

import json
import asyncio
from langchain_core.tools import tool
from agent.state import Citation, SearchResult
from tools.engines.tavily_engine import tavily_domain_search
from tools.engines.anysearch_engine import anysearch_vertical


@tool
async def ema_tool(query: str) -> str:
    """查询欧盟 EMA 药品注册审评信息：上市许可、EPAR、审评报告、安全更新。
    适用场景：查询药物在欧盟(EMA)的批准状态、审评资料、风险提示。
    Input: 药品名（英文更佳）"""
    result = await _search_ema(query)
    if not result.success:
        return f"[EMA] 未找到 '{query}' 的相关信息。"
    citations_json = json.dumps([c.to_dict() for c in result.citations], ensure_ascii=False)
    return f"[EMA] {result.content}\n\n__citations__: {citations_json}"


async def _search_ema(query: str) -> SearchResult:
    citations: list[Citation] = []
    content_parts: list[str] = []

    try:
        tv = await asyncio.to_thread(tavily_domain_search, query + " EMA", domains=["ema.europa.eu"], max_results=5)
        if tv.success and tv.citations:
            content_parts.append(tv.content[:1500])
            citations.extend(tv.citations)
    except Exception:
        pass

    if not citations:
        try:
            any_result = await asyncio.to_thread(anysearch_vertical, query + " EMA European Medicines Agency", domain="health", max_results=6)
            if any_result.success and "No results" not in any_result.content:
                content_parts.append(any_result.content[:1500])
                citations.extend(any_result.citations)
        except Exception:
            pass

    if not citations:
        return SearchResult.empty("EMA", "搜索无结果")

    return SearchResult(
        source_name="EMA",
        content="\n".join(content_parts)[:3000],
        citations=citations,
        success=True,
    )
