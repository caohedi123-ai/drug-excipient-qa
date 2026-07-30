"""PubMed 工具 - 生物医学文献

API: NCBI E-utilities REST (免费)
Search: Exa 语义搜索补充 (Phase 2)
"""

import httpx
import json
import xml.etree.ElementTree as ET
from langchain_core.tools import tool
from agent.state import Citation, SearchResult

PUBMED_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


@tool
async def pubmed_tool(query: str) -> str:
    """查询生物医学文献(PUBMED/MEDLINE)：研究论文、综述、临床试验、病例报告。
    适用场景：查询药物的临床研究证据、机制研究论文、安全性文献、综述。
    Input: 检索关键词（英文，支持MeSH术语）"""
    result = await _search_pubmed(query)
    if not result.success:
        return f"[PubMed] 未找到与 '{query}' 相关的文献。"

    citations_json = json.dumps([c.to_dict() for c in result.citations], ensure_ascii=False)
    return f"[PubMed] {result.content}\n\n__citations__: {citations_json}"


async def _search_pubmed(query: str) -> SearchResult:
    citations: list[Citation] = []
    content_parts: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=20.0, trust_env=False) as client:
            # Step 1: ESearch 获取 PMIDs
            search_resp = await client.get(
                f"{PUBMED_BASE}/esearch.fcgi",
                params={
                    "db": "pubmed",
                    "term": query,
                    "retmax": 5,
                    "sort": "relevance",
                    "retmode": "xml",
                }
            )
            if search_resp.status_code != 200:
                return SearchResult.empty("PubMed", "ESearch失败")

            search_root = ET.fromstring(search_resp.text)
            pmids = [id_elem.text for id_elem in search_root.iter("Id") if id_elem.text]

            if not pmids:
                return SearchResult.empty("PubMed", "无匹配文献")

            # Step 2: EFetch 获取摘要
            fetch_resp = await client.get(
                f"{PUBMED_BASE}/efetch.fcgi",
                params={
                    "db": "pubmed",
                    "id": ",".join(pmids),
                    "retmode": "xml",
                    "rettype": "abstract",
                }
            )
            if fetch_resp.status_code != 200:
                return SearchResult.empty("PubMed", "EFetch失败")

            fetch_root = ET.fromstring(fetch_resp.text)
            for i, article in enumerate(fetch_root.iter("PubmedArticle"), 1):
                pmid = article.find(".//PMID")
                title = article.find(".//ArticleTitle")
                abstract = article.find(".//Abstract/AbstractText")
                journal = article.find(".//Journal/Title")
                pub_date = article.find(".//PubDate/Year")

                pmid_text = pmid.text if pmid is not None and pmid.text else "N/A"
                title_text = title.text if title is not None and title.text else "N/A"
                journal_text = journal.text if journal is not None and journal.text else ""
                year_text = pub_date.text if pub_date is not None and pub_date.text else ""
                abstract_text = abstract.text if abstract is not None and abstract.text else ""

                pubmed_url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid_text}/"

                # 限制摘要长度
                abstract_short = abstract_text[:300]

                content_parts.append(
                    f"[{i}] PMID: {pmid_text}\n"
                    f"    {title_text[:150]}\n"
                    f"    {journal_text} ({year_text})\n"
                    f"    {abstract_short}\n"
                    f"    {pubmed_url}"
                )

                citations.append(Citation(
                    id=len(citations) + 1,
                    source_name="PubMed",
                    source_url=pubmed_url,
                    snippet=f"{title_text[:150]}, {journal_text} ({year_text})",
                    retrieval_query=query,
                    retrieval_timestamp=Citation.make_timestamp(),
                ))

        return SearchResult(
            source_name="PubMed",
            content="\n\n".join(content_parts)[:3000],
            citations=citations,
            success=True,
        )

    except Exception as e:
        return SearchResult.empty("PubMed", f"API异常: {e}")
