"""FDA UNII (Unique Ingredient Identifier) 工具 - 成分唯一标识

API: openFDA drug/label (免费)
     使用 openfda.substance_name 或 openfda.unii 字段搜索物质信息
"""

import httpx
import json
from langchain_core.tools import tool
from agent.state import Citation, SearchResult

FDA_UNII_URL = "https://api.fda.gov/drug/label.json"


@tool
async def fda_unii_tool(query: str) -> str:
    """查询FDA UNII编号和物质注册信息：物质的唯一标识符、物质类型、分子式。
    适用场景：查找药物成分或辅料的UNII编号、确认物质分类。
    Input: 物质名称/UNII编号"""
    result = await _search_fda_unii(query)
    if not result.success:
        return f"[FDA UNII] 未找到 '{query}' 的相关信息。"

    citations_json = json.dumps([c.to_dict() for c in result.citations], ensure_ascii=False)
    return f"[FDA UNII] {result.content}\n\n__citations__: {citations_json}"


async def _search_fda_unii(query: str) -> SearchResult:
    citations: list[Citation] = []
    content_parts: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
            # 使用 openfda.substance_name 字段搜索
            resp = await client.get(
                FDA_UNII_URL,
                params={
                    "search": f'openfda.substance_name:"{query}"',
                    "limit": 5
                }
            )
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", [])

                for i, item in enumerate(results[:5], 1):
                    openfda = item.get("openfda", {})
                    substance_name = openfda.get("substance_name", ["N/A"])[0]
                    unii_list = openfda.get("unii", [])
                    unii = unii_list[0] if unii_list else "N/A"
                    brand_name = openfda.get("brand_name", ["N/A"])[0]
                    generic_name = openfda.get("generic_name", ["N/A"])[0]
                    set_id = item.get("set_id", "")

                    content_parts.append(
                        f"[{i}] {substance_name}\n"
                        f"    UNII: {unii}\n"
                        f"    品牌名: {brand_name}\n"
                        f"    通用名: {generic_name}"
                    )

                    if unii and unii != "N/A":
                        url = f"https://precision.fda.gov/uniisearch/srs/unii/{unii}"
                        citations.append(Citation(
                            id=len(citations) + 1,
                            source_name="FDA UNII",
                            source_url=url,
                            snippet=f"{substance_name}, UNII={unii}",
                            retrieval_query=query,
                            retrieval_timestamp=Citation.make_timestamp(),
                        ))

        if citations:
            return SearchResult(
                source_name="FDA UNII",
                content="\n".join(content_parts)[:3000],
                citations=citations,
                success=True,
            )

    except Exception:
        pass

    return SearchResult.empty("FDA UNII", "API无返回")
