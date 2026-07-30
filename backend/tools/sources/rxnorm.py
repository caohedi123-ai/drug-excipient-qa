"""RxNorm 工具 - 临床药品标准术语

API: RxNorm REST (免费, UMLS)
"""

import httpx
import json
from langchain_core.tools import tool
from agent.state import Citation, SearchResult

RXNORM_URL = "https://rxnav.nlm.nih.gov/REST"


@tool
async def rxnorm_tool(query: str) -> str:
    """查询RxNorm标准术语：RxCUI编号、语义类型、术语关系、ATC分类映射。
    适用场景：查询药品的标准临床术语、跨系统术语互映射。
    Input: 药品名/RxCUI编号（英文）"""
    result = await _search_rxnorm(query)
    if not result.success:
        return f"[RxNorm] 未找到 '{query}' 的相关信息。"

    citations_json = json.dumps([c.to_dict() for c in result.citations], ensure_ascii=False)
    return f"[RxNorm] {result.content}\n\n__citations__: {citations_json}"


async def _search_rxnorm(query: str) -> SearchResult:
    citations: list[Citation] = []
    content_parts: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
            # 搜索 RxCUI
            resp = await client.get(
                f"{RXNORM_URL}/rxcui.json",
                params={"name": query, "search": 1}
            )
            if resp.status_code == 200:
                data = resp.json()
                rxcuis = data.get("idGroup", {}).get("rxnormId", [])
                if rxcuis:
                    rxcui = rxcuis[0]
                    url = f"https://rxnav.nlm.nih.gov/REST/rxcui/{rxcui}"
                    content_parts.append(f"RxCUI: {rxcui}")
                    content_parts.append(f"RxNav URL: {url}")

                    # 获取属性
                    props_resp = await client.get(
                        f"{RXNORM_URL}/rxcui/{rxcui}/allProperties.json",
                        params={"prop": "all"}
                    )
                    if props_resp.status_code == 200:
                        pdata = props_resp.json()
                        props = pdata.get("propConceptGroup", {}).get("propConcept", [])
                        for p in props[:10]:
                            cat = p.get("propCategory", "")
                            val = p.get("propValue", "")
                            content_parts.append(f"  {cat}: {val}")

                    citations.append(Citation(
                        id=1,
                        source_name="RxNorm",
                        source_url=url,
                        snippet=f"RxCUI={rxcui}, query={query}",
                        retrieval_query=query,
                        retrieval_timestamp=Citation.make_timestamp(),
                    ))

        if citations:
            return SearchResult(
                source_name="RxNorm",
                content="\n".join(content_parts)[:3000],
                citations=citations,
                success=True,
            )

    except Exception:
        pass

    return SearchResult.empty("RxNorm", "未找到RxCUI")
