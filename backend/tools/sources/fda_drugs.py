"""FDA Drugs (openFDA) 工具 - 药品注册审批信息

API: openFDA REST (免费)
Search: Tavily 域名定向 (open.fda.gov, fda.gov)
"""

import httpx
import asyncio
import json
from langchain_core.tools import tool
from agent.state import Citation, SearchResult
from tools.engines.tavily_engine import tavily_domain_search

OPENFDA_URL = "https://api.fda.gov/drug"


@tool
async def fda_drugs_tool(query: str) -> str:
    """查询FDA药品批准信息：申请号(ANDA/NDA)、批准日期、剂型、给药途径、活性成分、辅料、标签信息。
    适用场景：查询FDA药品批准状态、审评历史、标签变更。
    Input: 药品名/申请号/活性成分（英文）"""
    result = await _search_fda_drugs(query)
    if not result.success:
        return f"[FDA Drugs] 未找到 '{query}' 的相关审批信息。"

    citations_json = json.dumps([c.to_dict() for c in result.citations], ensure_ascii=False)
    return f"[FDA Drugs] {result.content}\n\n__citations__: {citations_json}"


async def _search_fda_drugs(query: str) -> SearchResult:
    citations: list[Citation] = []
    content_parts: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
            # openFDA 药品标签端点
            resp = await client.get(
                f"{OPENFDA_URL}/label.json",
                params={
                    "search": f"openfda.brand_name:\"{query}\"+OR+openfda.generic_name:\"{query}\"",
                    "limit": 3,
                }
            )
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", [])
                for i, item in enumerate(results[:3], 1):
                    openfda = item.get("openfda", {})
                    brand = openfda.get("brand_name", [query])[0]
                    generic = openfda.get("generic_name", [""])[0]
                    manufacturer = openfda.get("manufacturer_name", [""])[0]
                    route = openfda.get("route", [""])[0]
                    application = openfda.get("application_number", [""])[0]

                    fda_url = f"https://fda.gov/drugsatfda"
                    content_parts.append(
                        f"[{i}] {brand}\n"
                        f"    通用名: {generic}\n"
                        f"    生产商: {manufacturer}\n"
                        f"    给药途径: {route}\n"
                        f"    申请号: {application}"
                    )
                    citations.append(Citation(
                        id=len(citations) + 1,
                        source_name="FDA Drugs",
                        source_url=fda_url,
                        snippet=f"品牌: {brand}, 通用名: {generic}, 申请号: {application}",
                        retrieval_query=query,
                        retrieval_timestamp=Citation.make_timestamp(),
                    ))

            # 补充 FDA FAERS 不良事件端点
            if not citations:
                resp2 = await client.get(
                    f"{OPENFDA_URL}/event.json",
                    params={"search": f"patient.drug.openfda.generic_name:\"{query}\"", "limit": 1}
                )
                if resp2.status_code == 200:
                    ev_data = resp2.json()
                    total = ev_data.get("meta", {}).get("results", {}).get("total", 0)
                    if total > 0:
                        content_parts.append(f"\n不良事件报告总数: {total}")

    except Exception:
        pass

    # 降级：仅当 API 无结果时补充 Tavily 搜索
    if not citations:
        try:
            tavily_result = await asyncio.to_thread(tavily_domain_search, 
                query + " FDA approval",
                domains=["fda.gov"],
                max_results=3,
            )
            if tavily_result.success:
                content_parts.append(f"\n[FDA公告]\n{tavily_result.content[:800]}")
                citations.extend(tavily_result.citations)
        except Exception:
            pass

    if not citations:
        return SearchResult.empty("FDA Drugs", "API无返回")

    return SearchResult(
        source_name="FDA Drugs",
        content="\n".join(content_parts)[:3000],
        citations=citations,
        success=True,
    )
