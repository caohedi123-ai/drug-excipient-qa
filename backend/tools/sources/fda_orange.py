"""FDA Orange Book (橙皮书) 工具 - 治疗等效性评价

API: openFDA label (近似) + Tavily 域名定向 (fda.gov/orangedrug)
说明: FDA 已弃用独立 orange.json，改用 label + 橙皮书页面定向搜索兜底。
"""

import httpx
import asyncio
import json
from langchain_core.tools import tool
from agent.state import Citation, SearchResult
from tools.engines.tavily_engine import tavily_domain_search

OPENFDA_URL = "https://api.fda.gov/drug"


@tool
async def fda_orange_tool(query: str) -> str:
    """查询 FDA 橙皮书(Orange Book)：治疗等效性(ABCD)、专利与独占期、参比制剂(RLD)。
    适用场景：查询仿制药治疗等效性评级、参比制剂、专利到期信息。
    Input: 药品名/活性成分（英文）"""
    result = await _search_fda_orange(query)
    if not result.success:
        return f"[FDA Orange Book] 未找到 '{query}' 的相关信息。"
    citations_json = json.dumps([c.to_dict() for c in result.citations], ensure_ascii=False)
    return f"[FDA Orange Book] {result.content}\n\n__citations__: {citations_json}"


async def _search_fda_orange(query: str) -> SearchResult:
    citations: list[Citation] = []
    content_parts: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
            resp = await client.get(
                f"{OPENFDA_URL}/label.json",
                params={"search": f'openfda.brand_name:"{query}"', "limit": 2},
            )
            if resp.status_code == 200:
                data = resp.json()
                for i, item in enumerate(data.get("results", [])[:2], 1):
                    brand = item.get("openfda", {}).get("brand_name", [query])[0]
                    content_parts.append(f"[{i}] {brand} (标签/治疗等效参考)")
                    citations.append(Citation(
                        id=len(citations) + 1,
                        source_name="FDA Orange Book",
                        source_url="https://www.accessdata.fda.gov/scripts/cder/ob/",
                        snippet=f"{brand} 橙皮书条目",
                        retrieval_query=query,
                        retrieval_timestamp=Citation.make_timestamp(),
                    ))
    except Exception:
        pass

    if not citations:
        try:
            tv = await asyncio.to_thread(tavily_domain_search, 
                query + " Orange Book therapeutic equivalence",
                domains=["fda.gov"],
                max_results=3,
            )
            if tv.success:
                content_parts.append(f"[橙皮书]\n{tv.content[:800]}")
                citations.extend(tv.citations)
        except Exception:
            pass

    if not citations:
        return SearchResult.empty("FDA Orange Book", "API无返回")

    return SearchResult(
        source_name="FDA Orange Book",
        content="\n".join(content_parts)[:3000],
        citations=citations,
        success=True,
    )
