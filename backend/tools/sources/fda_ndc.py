"""FDA NDC (国家药品代码) 工具 - 药品标识与包装

API: openFDA NDC REST (免费, https://api.fda.gov/drug/ndc.json)
兜底: Tavily 域名定向 (fda.gov)
"""

import httpx
import asyncio
import json
from langchain_core.tools import tool
from agent.state import Citation, SearchResult
from tools.engines.tavily_engine import tavily_domain_search

NDC_URL = "https://api.fda.gov/drug/ndc.json"


@tool
async def fda_ndc_tool(query: str) -> str:
    """查询 FDA 国家药品代码(NDC)：包装、剂型、标签商、产品类型。
    适用场景：查询美国上市药品的 NDC 编码、包装信息、OTC/处方药分类。
    Input: 药品名/品牌名（英文）"""
    result = await _search_fda_ndc(query)
    if not result.success:
        return f"[FDA NDC] 未找到 '{query}' 的相关信息。"
    citations_json = json.dumps([c.to_dict() for c in result.citations], ensure_ascii=False)
    return f"[FDA NDC] {result.content}\n\n__citations__: {citations_json}"


async def _search_fda_ndc(query: str) -> SearchResult:
    citations: list[Citation] = []
    content_parts: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
            resp = await client.get(
                NDC_URL,
                params={
                    "search": f'brand_name:"{query}"+OR+generic_name:"{query}"',
                    "limit": 3,
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                for i, item in enumerate(data.get("results", [])[:3], 1):
                    product = item.get("product", {})
                    name = product.get("brand_name", query)
                    ndc = item.get("product_ndc", "")
                    route = ", ".join(product.get("route", []))
                    url = "https://www.accessdata.fda.gov/scripts/cder/ndc/index.cfm"
                    content_parts.append(f"[{i}] {name}\n    NDC: {ndc}\n    给药途径: {route}")
                    citations.append(Citation(
                        id=len(citations) + 1,
                        source_name="FDA NDC",
                        source_url=url,
                        snippet=f"{name} NDC:{ndc}",
                        retrieval_query=query,
                        retrieval_timestamp=Citation.make_timestamp(),
                    ))
    except Exception:
        pass

    if not citations:
        try:
            tv = await asyncio.to_thread(tavily_domain_search, query + " NDC code", domains=["fda.gov"], max_results=3)
            if tv.success:
                content_parts.append(f"[FDA公告]\n{tv.content[:800]}")
                citations.extend(tv.citations)
        except Exception:
            pass

    if not citations:
        return SearchResult.empty("FDA NDC", "API无返回")

    return SearchResult(
        source_name="FDA NDC",
        content="\n".join(content_parts)[:3000],
        citations=citations,
        success=True,
    )
