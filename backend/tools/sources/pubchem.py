"""PubChem 数据源工具 - 化合物基础信息

API: PubChem REST (免费, 无 API Key)
Search: Tavily 域名定向搜索 (pubchem.ncbi.nlm.nih.gov)
"""

import httpx
import asyncio
import json
from langchain_core.tools import tool
from agent.state import Citation, SearchResult
from tools.engines.tavily_engine import tavily_domain_search

PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"


@tool
async def pubchem_tool(query: str) -> str:
    """查询化合物基础信息：分子量、分子式、SMILES、LogP、CAS号、IUPAC名称、结构等。
    适用场景：查询药品活性成分(API)的理化性质、化学结构、标识符。
    Input: 化合物名/CAS号/InChIKey（支持中英文）"""
    result = await _search_pubchem(query)
    if not result.success:
        return f"[PubChem] 未找到 '{query}' 的相关信息。"

    citations_json = json.dumps([c.to_dict() for c in result.citations], ensure_ascii=False)
    return f"[PubChem] {result.content}\n\n__citations__: {citations_json}"


async def _search_pubchem(query: str) -> SearchResult:
    """PubChem API 主搜索逻辑"""
    citations: list[Citation] = []
    content_parts: list[str] = []

    try:
        # Step 1: 自动识别化合物名称 → 获取 CID
        # 关键：PubChem name lookup 需要纯化合物名，不能用 "aspirin molecular weight" 这种多词描述
        cids: list = []
        lookup_query = query
        async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
            cid_resp = await client.get(
                f"{PUBCHEM_BASE}/compound/name/{lookup_query}/cids/JSON"
            )
            if cid_resp.status_code == 200:
                cid_data = cid_resp.json()
                cids = cid_data.get("IdentifierList", {}).get("CID", [])

            # 降级1: full query 失败 → 尝试只用第一个词（通常是药物名）
            if not cids and " " in query:
                fallback_name = query.split()[0]
                if fallback_name != query:
                    fb_resp = await client.get(
                        f"{PUBCHEM_BASE}/compound/name/{fallback_name}/cids/JSON"
                    )
                    if fb_resp.status_code == 200:
                        fb_data = fb_resp.json()
                        cids = fb_data.get("IdentifierList", {}).get("CID", [])

            if not cids:
                # 降级2: Tavily 域名搜索
                return await asyncio.to_thread(tavily_domain_search, query, ["pubchem.ncbi.nlm.nih.gov"], max_results=5)

            cid = cids[0]
            pubchem_url = f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}"

            # Step 2: 获取化合物属性
            props_resp = await client.get(
                f"{PUBCHEM_BASE}/compound/cid/{cid}/property/MolecularWeight,MolecularFormula,CanonicalSMILES,IUPACName,XLogP/JSON"
            )
            props = props_resp.json().get("PropertyTable", {}).get("Properties", [{}])[0]

            mol_weight = props.get("MolecularWeight", "N/A")
            mol_formula = props.get("MolecularFormula", "N/A")
            smiles = props.get("CanonicalSMILES", "N/A")
            iupac = props.get("IUPACName", "N/A")
            logp = props.get("XLogP", "N/A")

            content_parts.append(
                f"化合物: {query}\n"
                f"CID: {cid}\n"
                f"分子量: {mol_weight} g/mol\n"
                f"分子式: {mol_formula}\n"
                f"SMILES: {smiles}\n"
                f"IUPAC: {iupac}\n"
                f"LogP: {logp}\n"
                f"PubChem URL: {pubchem_url}"
            )

            citations.append(Citation(
                id=1,
                source_name="PubChem",
                source_url=pubchem_url,
                snippet=f"{query}: MW={mol_weight}, Formula={mol_formula}",
                retrieval_query=query,
                retrieval_timestamp=Citation.make_timestamp(),
            ))

        # Step 3: 用 Tavily 域名搜索补充文献
        try:
            tavily_result = await asyncio.to_thread(tavily_domain_search, query, ["pubchem.ncbi.nlm.nih.gov"], max_results=3)
            if tavily_result.success:
                content_parts.append(f"\n[补充文献]\n{tavily_result.content[:1000]}")
                citations.extend(tavily_result.citations)
        except Exception:
            pass

        return SearchResult(
            source_name="PubChem",
            content="\n".join(content_parts)[:3000],
            citations=citations,
            success=True,
        )

    except Exception as e:
        return SearchResult.empty("PubChem", f"API异常: {e}")
