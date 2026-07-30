"""FDA FAERS 工具 - 药品不良事件报告系统

API: openFDA FAERS REST (免费)
"""

import httpx
import json
from langchain_core.tools import tool
from agent.state import Citation, SearchResult
from tools.sanitize import escape_openfda_value

OPENFDA_EVENT_URL = "https://api.fda.gov/drug/event.json"


@tool
async def fda_faers_tool(query: str) -> str:
    """查询FDA不良事件报告系统(FAERS)数据：不良反应报告、严重程度、发生率统计。
    适用场景：查询药品上市后的安全性数据、不良反应信号、reporting odds ratio。
    Input: 药品名/活性成分（英文）"""
    result = await _search_faers(query)
    if not result.success:
        return f"[FDA FAERS] 未找到 '{query}' 的不良事件数据。"

    citations_json = json.dumps([c.to_dict() for c in result.citations], ensure_ascii=False)
    return f"[FDA FAERS] {result.content}\n\n__citations__: {citations_json}"


async def _search_faers(query: str) -> SearchResult:
    citations: list[Citation] = []
    content_parts: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=20.0, trust_env=False) as client:
            # 查询不良事件总数和严重事件
            resp = await client.get(
                OPENFDA_EVENT_URL,
                params={
                    "search": f"patient.drug.openfda.generic_name:\"{escape_openfda_value(query)}\"",
                    "count": "serious",
                    "limit": 1,
                }
            )
            if resp.status_code == 200:
                data = resp.json()
                total = data.get("meta", {}).get("results", {}).get("total", 0)
                content_parts.append(f"FAERS 不良事件报告总数: {total}")

                # 严重性分布
                serious_counts = data.get("results", [])
                for item in serious_counts:
                    s = item.get("term", "")
                    c = item.get("count", 0)
                    content_parts.append(f"  {s}: {c}")

            # 查询最常见的不良事件类型
            resp2 = await client.get(
                OPENFDA_EVENT_URL,
                params={
                    "search": f"patient.drug.openfda.generic_name:\"{escape_openfda_value(query)}\"",
                    "count": "patient.reaction.reactionmeddrapt.exact",
                    "limit": 10,
                }
            )
            if resp2.status_code == 200:
                data2 = resp2.json()
                content_parts.append("\n最常见不良事件 (MedDRA PT):")
                for item in data2.get("results", []):
                    pt = item.get("term", "")
                    c = item.get("count", 0)
                    content_parts.append(f"  {pt}: {c}次")

            # 构造引用
            faers_url = f"https://fda.gov/drugs/questions-and-answers-fdas-adverse-event-reporting-system-faers"
            if total > 0:
                citations.append(Citation(
                    id=1,
                    source_name="FDA FAERS",
                    source_url=faers_url,
                    snippet=f"{query}: 共 {total} 份不良事件报告",
                    retrieval_query=query,
                    retrieval_timestamp=Citation.make_timestamp(),
                ))

        if citations:
            return SearchResult(
                source_name="FDA FAERS",
                content="\n".join(content_parts)[:3000],
                citations=citations,
                success=True,
            )

    except Exception as e:
        return SearchResult.empty("FDA FAERS", f"API错误: {e}")

    return SearchResult.empty("FDA FAERS", "API无返回")
