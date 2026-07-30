"""DrugCentral 数据源工具 - 药物监管与科学数据

API: DrugCentral REST (免费)
Search: AnySearch health 垂直领域补充
"""

import httpx
import asyncio
import json
from langchain_core.tools import tool
from agent.state import Citation, SearchResult
from tools.engines.anysearch_engine import anysearch_vertical

DRUGCENTRAL_BASE = "https://drugcentral.org/api/v1"


@tool
async def drugcentral_tool(query: str) -> str:
    """查询药物监管状态、临床试验、科学文献整合数据。
    适用场景：查询药物全球监管批准状态、临床证据、结构-活性关系。
    Input: 药物名/INN（支持中英文，英文更佳）"""
    result = await _search_drugcentral(query)
    if not result.success:
        return f"[DrugCentral] 未找到 '{query}' 的相关信息。"

    citations_json = json.dumps([c.to_dict() for c in result.citations], ensure_ascii=False)
    return f"[DrugCentral] {result.content}\n\n__citations__: {citations_json}"


async def _search_drugcentral(query: str) -> SearchResult:
    citations: list[Citation] = []
    content_parts: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
            # DrugCentral 的药物搜索接口
            resp = await client.get(
                f"{DRUGCENTRAL_BASE}/drug/search",
                params={"q": query, "limit": 3}
            )
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", data.get("drugs", []))
                for i, drug in enumerate(results[:3], 1):
                    name = drug.get("name", query)
                    drug_id = drug.get("struct_id", drug.get("id", ""))
                    url = f"https://drugcentral.org/drugcard/{drug_id}" if drug_id else ""
                    indication = drug.get("indication", drug.get("description", ""))

                    content_parts.append(f"[{i}] {name}: {indication[:200]}")
                    if url:
                        citations.append(Citation(
                            id=len(citations) + 1,
                            source_name="DrugCentral",
                            source_url=url,
                            snippet=indication[:200],
                            retrieval_query=query,
                            retrieval_timestamp=Citation.make_timestamp(),
                        ))
    except Exception:
        pass

    # Layer 2: AnySearch 降级（仅当 API 无结果时）
    if len(content_parts) == 0:
        try:
            any_result = await asyncio.to_thread(anysearch_vertical, query, domain="health", max_results=5)
            if any_result.success:
                content_parts.append(f"[降级搜索]\n{any_result.content[:1200]}")
                citations.extend(any_result.citations)
        except Exception:
            pass

    if not citations:
        return SearchResult.empty("DrugCentral", "API无返回,搜索无结果")

    return SearchResult(
        source_name="DrugCentral",
        content="\n".join(content_parts)[:3000],
        citations=citations,
        success=True,
    )
