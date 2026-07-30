"""Open Targets 工具 - 靶点-疾病-药物关联

API: Open Targets GraphQL (免费, https://api.opentargets.org/api/v4/graphql)
兜底: AnySearch academic 垂直领域搜索
"""

import httpx
import asyncio
import json
from langchain_core.tools import tool
from agent.state import Citation, SearchResult
from tools.engines.anysearch_engine import anysearch_vertical

OT_URL = "https://api.opentargets.org/api/v4/graphql"

GQL = """
query SearchTargets($q: String!) {
  search(query: $q, entityNames: ["target", "disease", "drug"]) {
    hits {
      id
      name
      entity
    }
  }
}
"""


@tool
async def open_targets_tool(query: str) -> str:
    """查询靶点-疾病-药物关联证据（Open Targets）：靶点多效性、疾病关联、药物机制。
    适用场景：查询靶点可药性、疾病-靶点关联强度、关联药物。
    Input: 靶点名/疾病名/药物名（英文）"""
    result = await _search_open_targets(query)
    if not result.success:
        return f"[Open Targets] 未找到 '{query}' 的相关信息。"
    citations_json = json.dumps([c.to_dict() for c in result.citations], ensure_ascii=False)
    return f"[Open Targets] {result.content}\n\n__citations__: {citations_json}"


async def _search_open_targets(query: str) -> SearchResult:
    citations: list[Citation] = []
    content_parts: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
            resp = await client.post(
                OT_URL,
                json={"query": GQL, "variables": {"q": query}},
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code == 200:
                data = resp.json()
                hits = data.get("data", {}).get("search", {}).get("hits", [])
                for i, hit in enumerate(hits[:5], 1):
                    name = hit.get("name", query)
                    entity = hit.get("entity", "")
                    hid = hit.get("id", "")
                    url = f"https://platform.opentargets.org/{entity.lower()}/{hid}" if hid else "https://platform.opentargets.org"
                    content_parts.append(f"[{i}] {name} ({entity}: {hid})")
                    citations.append(Citation(
                        id=len(citations) + 1,
                        source_name="Open Targets",
                        source_url=url,
                        snippet=f"{name} ({entity})",
                        retrieval_query=query,
                        retrieval_timestamp=Citation.make_timestamp(),
                    ))
    except Exception:
        pass

    if not citations:
        try:
            any_result = await asyncio.to_thread(anysearch_vertical, query + " target disease association", domain="academic", max_results=6)
            if any_result.success and "No results" not in any_result.content:
                content_parts.append(f"[降级搜索]\n{any_result.content[:1200]}")
                citations.extend(any_result.citations)
        except Exception:
            pass

    if not citations:
        return SearchResult.empty("Open Targets", "API无返回,搜索无结果")

    return SearchResult(
        source_name="Open Targets",
        content="\n".join(content_parts)[:3000],
        citations=citations,
        success=True,
    )
