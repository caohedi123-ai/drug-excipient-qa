"""ChEMBL 化合物数据库工具 - 化学结构与活性

API: ChEMBL REST (EBI 免费, https://www.ebi.ac.uk/chembl/api/data)
兜底: AnySearch health 垂直领域搜索
"""

import httpx
import asyncio
import json
import logging
from langchain_core.tools import tool
from agent.state import Citation, SearchResult
from tools.engines.anysearch_engine import anysearch_vertical
from config import get_settings

log = logging.getLogger("chembl")

CHEMBL_BASE = "https://www.ebi.ac.uk/chembl/api/data"


@tool
async def chembl_tool(query: str) -> str:
    """查询 ChEMBL 化合物标识符与基础化学信息（ChEMBL REST）。
    适用场景：查询活性成分的 ChEMBL ID、规范名称与基础结构标识；ChEMBL MCP 接入后提供靶点/作用机制/生物活性/ADMET 等深度数据。
    Input: 化合物名/ChEMBL ID（英文）"""
    result = await _search_chembl(query)
    if not result.success:
        return f"[ChEMBL] 未找到 '{query}' 的相关信息。"
    citations_json = json.dumps([c.to_dict() for c in result.citations], ensure_ascii=False)
    return f"[ChEMBL] {result.content}\n\n__citations__: {citations_json}"


async def _search_chembl(query: str) -> SearchResult:
    # P0.4 优先：ChEMBL MCP（深度数据）。任何失败均降级到 REST，检索永不中断。
    try:
        from tools.sources.chembl_mcp_client import ChemblMCPClient
        if get_settings().chembl_mcp_enabled:
            client = ChemblMCPClient.instance()
            if client.enabled:
                text = await asyncio.wait_for(
                    client.search_full(query), timeout=get_settings().chembl_mcp_timeout + 5
                )
                if text and text.strip():
                    return SearchResult(
                        source_name="ChEMBL (MCP)",
                        content=text,
                        citations=[],
                        success=True,
                    )
    except Exception as e:  # noqa
        log.warning(f"[chembl] MCP 不可用，降级 REST: {e}")

    # 降级：原有 REST + AnySearch 兜底
    citations: list[Citation] = []
    content_parts: list[str] = []
    rest_status: Optional[int] = None  # REST 返回的非 200 状态码（如 500 服务端故障）

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
            else:
                rest_status = resp.status_code
    except Exception:
        pass

    if not content_parts:
        try:
            any_result = await asyncio.to_thread(anysearch_vertical, query + " chembl molecule", domain="health", max_results=6)
            if any_result.success and "No results" not in any_result.content:
                prefix = ""
                if rest_status:
                    prefix = f"[ChEMBL 官方服务暂不可用（HTTP {rest_status}），以下为网络检索兜底]\n"
                content_parts.append(prefix + f"[降级搜索]\n{any_result.content[:1200]}")
                citations.extend(any_result.citations)
        except Exception:
            pass

    if not citations:
        if rest_status:
            return SearchResult.empty("ChEMBL", f"ChEMBL 官方服务暂不可用（HTTP {rest_status}）")
        return SearchResult.empty("ChEMBL", "API无返回,搜索无结果")

    return SearchResult(
        source_name="ChEMBL",
        content="\n".join(content_parts)[:3000],
        citations=citations,
        success=True,
    )
