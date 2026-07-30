"""ClinicalTrials.gov 工具 - 临床试验

API: ClinicalTrials.gov API v2 (免费, https://clinicaltrials.gov/api/v2/studies)
兜底: AnySearch health 垂直领域搜索
"""

import httpx
import asyncio
import json
from langchain_core.tools import tool
from agent.state import Citation, SearchResult
from tools.engines.anysearch_engine import anysearch_vertical

CT_URL = "https://clinicaltrials.gov/api/v2/studies"


@tool
async def clinicaltrials_tool(query: str) -> str:
    """查询临床试验注册信息（ClinicalTrials.gov）：试验设计、阶段、入排标准、结果。
    适用场景：查询药物在研临床试验、适应症扩展、疗效与安全性证据。
    Input: 药物名/适应症/疾病名（英文更佳）"""
    result = await _search_clinicaltrials(query)
    if not result.success:
        return f"[ClinicalTrials] 未找到 '{query}' 的相关试验信息。"
    citations_json = json.dumps([c.to_dict() for c in result.citations], ensure_ascii=False)
    return f"[ClinicalTrials] {result.content}\n\n__citations__: {citations_json}"


async def _search_clinicaltrials(query: str) -> SearchResult:
    citations: list[Citation] = []
    content_parts: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
            resp = await client.get(
                CT_URL,
                params={"query.term": query, "pageSize": 3, "format": "json"},
            )
            if resp.status_code == 200:
                data = resp.json()
                studies = data.get("studies", [])
                for i, s in enumerate(studies[:3], 1):
                    ps = s.get("protocolSection", {})
                    ident = ps.get("identificationModule", {})
                    title = ident.get("briefTitle", query)
                    nct = ident.get("nctId", "")
                    phase = ps.get("designModule", {}).get("phases", [""])[0]
                    url = f"https://clinicaltrials.gov/study/{nct}" if nct else "https://clinicaltrials.gov"
                    content_parts.append(f"[{i}] {title}\n    NCT: {nct} | 阶段: {phase}")
                    citations.append(Citation(
                        id=len(citations) + 1,
                        source_name="ClinicalTrials",
                        source_url=url,
                        snippet=f"{title} ({nct})",
                        retrieval_query=query,
                        retrieval_timestamp=Citation.make_timestamp(),
                    ))
    except Exception:
        pass

    if not citations:
        try:
            any_result = await asyncio.to_thread(anysearch_vertical, query + " clinical trial", domain="health", max_results=6)
            if any_result.success and "No results" not in any_result.content:
                content_parts.append(f"[降级搜索]\n{any_result.content[:1200]}")
                citations.extend(any_result.citations)
        except Exception:
            pass

    if not citations:
        return SearchResult.empty("ClinicalTrials", "API无返回,搜索无结果")

    return SearchResult(
        source_name="ClinicalTrials",
        content="\n".join(content_parts)[:3000],
        citations=citations,
        success=True,
    )
