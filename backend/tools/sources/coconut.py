"""COCONUT 天然产物数据库工具 - 天然产物结构

API: COCONUT REST (免费, https://coconut.naturalproducts.net/api)
兜底: AnySearch health 垂直领域搜索
"""

import httpx
import asyncio
import json
from langchain_core.tools import tool
from agent.state import Citation, SearchResult
from tools.engines.anysearch_engine import anysearch_vertical

COCONUT_BASE = "https://coconut.naturalproducts.net/api/search"


@tool
async def coconut_tool(query: str) -> str:
    """查询天然产物化学结构、来源生物、三维坐标（COCONUT）。
    适用场景：查询植物/微生物来源天然产物、次生代谢物结构信息。
    Input: 天然产物名/分子式（英文）"""
    result = await _search_coconut(query)
    if not result.success:
        return f"[COCONUT] 未找到 '{query}' 的相关信息。"
    citations_json = json.dumps([c.to_dict() for c in result.citations], ensure_ascii=False)
    return f"[COCONUT] {result.content}\n\n__citations__: {citations_json}"


async def _search_coconut(query: str) -> SearchResult:
    citations: list[Citation] = []
    content_parts: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
            resp = await client.get(f"{COCONUT_BASE}", params={"q": query, "size": 3})
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", data.get("data", []))
                for i, item in enumerate(results[:3], 1):
                    name = item.get("name") or item.get("standard_name") or query
                    coconut_id = item.get("coconut_id") or item.get("id") or ""
                    url = f"https://coconut.naturalproducts.net/compound/{coconut_id}" if coconut_id else ""
                    content_parts.append(f"[{i}] {name} ({coconut_id})")
                    if url:
                        citations.append(Citation(
                            id=len(citations) + 1,
                            source_name="COCONUT",
                            source_url=url,
                            snippet=f"{name} ({coconut_id})",
                            retrieval_query=query,
                            retrieval_timestamp=Citation.make_timestamp(),
                        ))
    except Exception:
        pass

    if not content_parts:
        try:
            any_result = await asyncio.to_thread(anysearch_vertical, query + " natural product", domain="health", max_results=6)
            if any_result.success and "No results" not in any_result.content:
                content_parts.append(f"[降级搜索]\n{any_result.content[:1200]}")
                citations.extend(any_result.citations)
        except Exception:
            pass

    if not citations:
        return SearchResult.empty("COCONUT", "API无返回,搜索无结果")

    return SearchResult(
        source_name="COCONUT",
        content="\n".join(content_parts)[:3000],
        citations=citations,
        success=True,
    )
