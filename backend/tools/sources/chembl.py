"""ChEMBL 化合物数据库工具 - 化学结构与活性

API: ChEMBL REST (EBI 免费, https://www.ebi.ac.uk/chembl/api/data)
兜底: AnySearch health 垂直领域搜索
"""

import httpx
import asyncio
import json
from langchain_core.tools import tool
from agent.state import Citation, SearchResult
from tools.engines.anysearch_engine import anysearch_vertical

CHEMBL_BASE = "https://www.ebi.ac.uk/chembl/api/data"


@tool
async def chembl_tool(query: str) -> str:
    """查询化合物化学结构、靶点、药理活性数据（ChEMBL）。
    适用场景：查询活性成分的结构-活性关系、靶点结合、生物活性测定。
    Input: 化合物名/ChEMBL ID（英文）"""
    result = await _search_chembl(query)
    if not result.success:
        return f"[ChEMBL] 未找到 '{query}' 的相关信息。"
    citations_json = json.dumps([c.to_dict() for c in result.citations], ensure_ascii=False)
    return f"[ChEMBL] {result.content}\n\n__citations__: {citations_json}"


async def _search_chembl(query: str) -> SearchResult:
    citations: list[Citation] = []
    content_parts: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
            resp = await client.get(
                f"{CHEMBL_BASE}/molecule.json",
                params={"search_terms": query, "limit": 3},
            )
            if resp.status_code == 200:
                data = resp.json()
                for i, m in enumerate(data.get("molecules", [])[:3], 1):
                    name = m.get("pref_name") or m.get("full_name") or query
                    chembl_id = m.get("molecule_chembl_id", "")
                    url = f"https://www.ebi.ac.uk/chembl/compound_report_card/{chembl_id}" if chembl_id else ""
                    content_parts.append(f"[{i}] {name} ({chembl_id})")
                    if url:
                        citations.append(Citation(
                            id=len(citations) + 1,
                            source_name="ChEMBL",
                            source_url=url,
                            snippet=f"{name} ({chembl_id})",
                            retrieval_query=query,
                            retrieval_timestamp=Citation.make_timestamp(),
                        ))
    except Exception:
        pass

    if not content_parts:
        try:
            any_result = await asyncio.to_thread(anysearch_vertical, query + " chembl molecule", domain="health", max_results=6)
            if any_result.success and "No results" not in any_result.content:
                content_parts.append(f"[降级搜索]\n{any_result.content[:1200]}")
                citations.extend(any_result.citations)
        except Exception:
            pass

    if not citations:
        return SearchResult.empty("ChEMBL", "API无返回,搜索无结果")

    return SearchResult(
        source_name="ChEMBL",
        content="\n".join(content_parts)[:3000],
        citations=citations,
        success=True,
    )
