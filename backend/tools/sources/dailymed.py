"""DailyMed 工具 - FDA批准的药品说明书

API: DailyMed REST (免费)
策略: spls.json(查目录) → spls/{setid}.xml(取全文) → 章节提取 → Tavily降级
"""

import httpx
import asyncio
import json
import re
import xml.etree.ElementTree as ET
from langchain_core.tools import tool
from agent.state import Citation, SearchResult
from tools.engines.tavily_engine import tavily_domain_search

DAILYMED_URL = "https://dailymed.nlm.nih.gov/dailymed/services/v2"

# 目标章节列表（按优先级排序）
TARGET_SECTIONS = [
    "DOSAGE AND ADMINISTRATION",
    "INDICATIONS AND USAGE",
    "ADVERSE REACTIONS",
    "WARNINGS AND PRECAUTIONS",
    "CONTRAINDICATIONS",
    "DRUG INTERACTIONS",
    "CLINICAL PHARMACOLOGY",
    "DESCRIPTION",
    "HOW SUPPLIED",
    "INFORMATION FOR PATIENTS",
    "OVERDOSAGE",
    "USE IN SPECIFIC POPULATIONS",
    "CLINICAL STUDIES",
    "MECHANISM OF ACTION",
    "PHARMACOKINETICS",
    "NONCLINICAL TOXICOLOGY",
]


def _extract_sections_from_xml(
    xml_text: str, max_chars: int = 12000, section_max_chars: int = 2000
) -> str:
    """从 SPL XML 提取目标章节内容

    max_chars: 总返回字符上限（默认放开到 12000）
    section_max_chars: 单个章节上限（放开到 2000，避免长章节被过度截断）
    """
    try:
        # 移除命名空间前缀（SPL XML 可能有多个命名空间）
        xml_clean = re.sub(r'<(/)?[a-zA-Z0-9_]+:', r'<\1', xml_text)
        xml_clean = re.sub(r'\s+xmlns(:\w+)?="[^"]*"', '', xml_clean)
        root = ET.fromstring(xml_clean)

        sections_found = []
        for section_name in TARGET_SECTIONS:
            # 搜索 <text><paragraph> 结构的 section
            for elem in root.iter():
                # 匹配 section 标题
                title_elem = elem.find('.//{*}title')
                if title_elem is None:
                    title_elem = elem if (elem.tag == 'title' or 'title' in (elem.get('class', []) if isinstance(elem.get('class'), list) else [])) else None

                if title_elem is not None:
                    title_text = ''.join(title_elem.itertext()).strip().upper()
                    if section_name in title_text or title_text.startswith(section_name):
                        # 提取该 section 下的所有文本
                        parent = title_elem.getparent() if title_elem != elem else elem.getparent()
                        text = ' '.join(parent.itertext()) if parent is not None else ''
                        text = re.sub(r'\s+', ' ', text).strip()
                        if len(text) > 50:  # 过滤空章节
                            sections_found.append(f"### {section_name}\n{text[:section_max_chars]}")
                        break

            if len('\n'.join(sections_found)) > max_chars:
                break

        if sections_found:
            return '\n\n'.join(sections_found)[:max_chars]
    except Exception:
        pass

    # Fallback: 纯文本提取（去除 XML 标签）
    text = re.sub(r'<[^>]+>', ' ', xml_text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:max_chars]


@tool
async def dailymed_tool(query: str) -> str:
    """查询FDA批准的药品说明书信息：适应症、用法用量、不良反应、禁忌症、辅料列表。
    适用场景：查询药品的完整标签信息、说明书内容、辅料组成。
    Input: 药品名/NDC编号（英文，美国上市药品）"""
    result = await _search_dailymed(query)
    if not result.success:
        return f"[DailyMed] 未找到 '{query}' 的说明书信息。"

    citations_json = json.dumps([c.to_dict() for c in result.citations], ensure_ascii=False)
    return f"[DailyMed] {result.content}\n\n__citations__: {citations_json}"


async def _search_dailymed(query: str) -> SearchResult:
    citations: list[Citation] = []
    content_parts: list[str] = []

    # Layer 1: DailyMed API → 查目录
    try:
        async with httpx.AsyncClient(timeout=20.0, trust_env=False) as client:
            resp = await client.get(
                f"{DAILYMED_URL}/spls.json",
                params={"search_text": query, "limit": 5}
            )
            if resp.status_code == 200:
                data = resp.json()
                spls = data.get("data", [])
                # 一致性校验：spls.json 为全文搜索，可能返回无关药品的 SPL（如搜 Acalabrutinib 返回
                # METOPROLOL 说明书）。brand/generic 必须与查询词核心 token 匹配，否则丢弃该 SPL。
                q_core = re.sub(r"[^a-z0-9]+", "", query.lower())
                matched_spls = []
                for spl in spls:
                    hay = f"{spl.get('brand_name', '') or ''} {spl.get('generic_name', '') or spl.get('substance_name', '') or ''}".lower()
                    hay_core = re.sub(r"[^a-z0-9]+", "", hay)
                    if not q_core or len(q_core) < 4 or q_core in hay_core or hay_core in q_core:
                        matched_spls.append(spl)
                spls = matched_spls or spls  # 全部不匹配时退回原列表（避免误杀同义词查询）
                for i, spl in enumerate(spls[:5], 1):
                    setid = spl.get("setid", "")
                    brand = spl.get("brand_name", query)
                    generic = spl.get("generic_name", spl.get("substance_name", ""))
                    manufacturer = spl.get("manufacturer_name", "")
                    label_url = f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={setid}"

                    # Layer 1.5: 抓取 SPL XML 全文并提取目标章节
                    section_text = ""
                    if setid:
                        try:
                            xml_resp = await client.get(
                                f"{DAILYMED_URL}/spls/{setid}.xml",
                                timeout=15.0,
                            )
                            if xml_resp.status_code == 200:
                                section_text = _extract_sections_from_xml(xml_resp.text, max_chars=12000)
                        except Exception:
                            pass

                    if section_text:
                        content_parts.append(
                            f"[{i}] {brand} ({generic})\n{section_text}\nURL: {label_url}"
                        )
                    else:
                        content_parts.append(
                            f"[{i}] {brand}\n通用名: {generic}\n生产商: {manufacturer}\nURL: {label_url}"
                        )

                    if setid:
                        citations.append(Citation(
                            id=len(citations) + 1,
                            source_name="DailyMed",
                            source_url=label_url,
                            snippet=f"{brand} ({generic}), {manufacturer}",
                            retrieval_query=query,
                            retrieval_timestamp=Citation.make_timestamp(),
                        ))

        if content_parts:
            # 多 SPL 场景：至多保留前 2 个结果（各自已在章节层截断），
            # 整体再以 12000 字符钳制，避免拼接超限
            limited_parts = content_parts[:2]
            content = "\n\n".join(limited_parts)
            return SearchResult(
                source_name="DailyMed",
                content=content[:12000],
                citations=citations,
                success=True,
            )

    except Exception:
        pass

    # Layer 2: Tavily 域名搜索
    return await asyncio.to_thread(tavily_domain_search, 
        query + " drug label prescribing information",
        domains=["dailymed.nlm.nih.gov"],
        max_results=6,
    )
