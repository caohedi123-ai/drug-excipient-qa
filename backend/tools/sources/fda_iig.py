"""FDA IIG (Inactive Ingredient Database) 工具 - 辅料数据库

API: openFDA drug/label (免费)
     使用 inactive_ingredient 字段搜索辅料信息
Fallback: Tavily 域名定向 (accessdata.fda.gov, dailymed.nlm.nih.gov)
"""

import asyncio
import httpx
import json
from langchain_core.tools import tool
from agent.state import Citation, SearchResult
from tools.engines.tavily_engine import tavily_domain_search
from tools.sanitize import sanitize_query

FDA_IIG_URL = "https://api.fda.gov/drug/label.json"


@tool
async def fda_iig_tool(query: str) -> str:
    """查询FDA批准的辅料(Inactive Ingredient)信息：辅料名、给药途径、最大用量、剂型。
    适用场景：查询药用辅料的FDA批准状态、用量上限、适用剂型。
    Input: 辅料名称/UNII（英文）"""
    result = await _search_fda_iig(query)
    if not result.success:
        return f"[FDA IIG] 未找到辅料 '{query}' 的相关信息。"

    citations_json = json.dumps([c.to_dict() for c in result.citations], ensure_ascii=False)
    return f"[FDA IIG] {result.content}\n\n__citations__: {citations_json}"


async def _search_fda_iig(query: str) -> SearchResult:
    q = sanitize_query(query)
    citations: list[Citation] = []
    content_parts: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
            # 使用 inactive_ingredient 字段搜索
            resp = await client.get(
                FDA_IIG_URL,
                params={
                    "search": f"inactive_ingredient:{q}",
                    "limit": 10
                }
            )
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", [])

                for i, item in enumerate(results[:10], 1):
                    # 提取辅料信息
                    inactive_ingredients = item.get("inactive_ingredient", [])
                    brand_name = item.get("openfda", {}).get("brand_name", ["N/A"])[0]
                    manufacturer = item.get("openfda", {}).get("manufacturer_name", ["N/A"])[0]
                    route = item.get("openfda", {}).get("route", ["N/A"])[0]
                    set_id = item.get("set_id", "")

                    # 过滤出包含目标辅料的记录
                    matching_ingredients = [
                        ing for ing in inactive_ingredients
                        if q.lower() in ing.lower()
                    ]

                    if matching_ingredients:
                        content_parts.append(
                            f"[{i}] {brand_name}\n"
                            f"    生产商: {manufacturer}\n"
                            f"    给药途径: {route}\n"
                            f"    含辅料的制剂: {matching_ingredients[0][:200]}"
                        )

                        if set_id:
                            url = f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={set_id}"
                            citations.append(Citation(
                                id=len(citations) + 1,
                                source_name="FDA IIG",
                                source_url=url,
                                snippet=f"{brand_name} 含 {query}",
                                retrieval_query=query,
                                retrieval_timestamp=Citation.make_timestamp(),
                            ))

        if citations:
            return SearchResult(
                source_name="FDA IIG",
                content="\n".join(content_parts)[:3000],
                citations=citations,
                success=True,
            )

    except Exception as e:
        return SearchResult.empty("FDA IIG", f"API错误: {e}")

    # 降级到 Tavily 域名搜索
    return await asyncio.to_thread(
        tavily_domain_search,
        q + " inactive ingredient FDA",
        domains=["accessdata.fda.gov", "dailymed.nlm.nih.gov"],
        max_results=6,
    )
