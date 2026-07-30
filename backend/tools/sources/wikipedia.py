"""Wikipedia 工具 - 维基百科综合信息

API: Wikipedia REST (免费)
"""

import httpx
import asyncio
import json
from langchain_core.tools import tool
from agent.state import Citation, SearchResult
from tools.engines.tavily_engine import tavily_domain_search

WIKI_URL = "https://en.wikipedia.org/api/rest_v1"


@tool
async def wikipedia_tool(query: str) -> str:
    """查询维基百科中的药物综合信息：历史、机制、用途、副作用等概述。
    适用场景：获取药物的综述性背景信息、历史沿革、社会文化影响。
    Input: 药物名/术语（英文）"""
    result = await _search_wikipedia(query)
    if not result.success:
        return f"[Wikipedia] 未找到 '{query}' 的相关条目。"

    citations_json = json.dumps([c.to_dict() for c in result.citations], ensure_ascii=False)
    return f"[Wikipedia] {result.content}\n\n__citations__: {citations_json}"


async def _search_wikipedia(query: str) -> SearchResult:
    try:
        async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
            # Wikipedia 页面摘要 API
            resp = await client.get(
                f"{WIKI_URL}/page/summary/{query.replace(' ', '_')}",
            )
            if resp.status_code != 200:
                # 降级到 Tavily 域名搜索（Wikipedia API 不可达时）
                return await asyncio.to_thread(tavily_domain_search,
                    query,
                    domains=["en.wikipedia.org"],
                    max_results=5,
                )

            data = resp.json()
            title = data.get("title", query)
            extract = data.get("extract", "")[:1500]
            wiki_url = data.get("content_urls", {}).get("desktop", {}).get("page",
                f"https://en.wikipedia.org/wiki/{query.replace(' ', '_')}"
            )

            citation = Citation(
                id=1,
                source_name="Wikipedia",
                source_url=wiki_url,
                snippet=extract[:200],
                retrieval_query=query,
                retrieval_timestamp=Citation.make_timestamp(),
            )

            return SearchResult(
                source_name="Wikipedia",
                content=f"{title}\n\n{extract}\n\n来源: {wiki_url}",
                citations=[citation],
                success=True,
            )

    except Exception:
        pass

    # 降级到 Tavily
    return await asyncio.to_thread(tavily_domain_search, 
        query,
        domains=["en.wikipedia.org"],
        max_results=5,
    )
