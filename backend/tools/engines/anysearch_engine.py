"""AnySearch MCP 搜索引擎封装 - 泛搜引擎

设计要点：
- 不限域名宽泛搜索，配合 health/academic/ip 垂直领域分类
- batch_search 多 query 并行搜索
- extract 页面正文深度抓取
- 免费额度 1000次/天，作为 Tavily 降级和扩展的主力
"""

import asyncio
import httpx
from datetime import datetime, timezone
from agent.state import Citation, SearchResult
from config import get_settings

settings = get_settings()
ANYSEARCH_BASE = "https://api.anysearch.ai/v1"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.anysearch_api_key}",
        "Content-Type": "application/json",
    }


def anysearch_vertical(
    query: str,
    domain: str = "health",
    sub_domain: str | None = None,
    freshness: str = "any",
    content_types: list[str] | None = None,
    max_results: int = 10,
) -> SearchResult:
    """AnySearch 垂直领域搜索（不限域名）

    Args:
        query: 检索关键词
        domain: 垂直领域，支持 health/academic/ip/news/code 等22个领域
        sub_domain: 子领域，如 paper/patent
        freshness: 时效过滤 "any" / "past_day" / "past_week" / "past_month" / "past_year"
        content_types: 内容类型过滤 ["article", "news", "government", "journal", ...]
        max_results: 最大返回数

    Returns:
        SearchResult 统一结果容器
    """
    try:
        payload = {
            "query": query,
            "domain": domain,
            "freshness": freshness,
            "max_results": max_results,
        }
        if sub_domain:
            payload["sub_domain"] = sub_domain
        if content_types:
            payload["content_types"] = content_types

        resp = httpx.post(
            f"{ANYSEARCH_BASE}/search",
            json=payload,
            headers=_headers(),
            timeout=30.0,
            trust_env=False,
        )
        resp.raise_for_status()
        data = resp.json()

        citations: list[Citation] = []
        content_parts: list[str] = []
        results = data.get("results", data.get("data", []))

        for r in results[:max_results]:
            abstract = r.get("content") or r.get("snippet") or r.get("abstract") or ""
            url = r.get("url", "")
            title = r.get("title", "")
            if abstract or url:
                citations.append(Citation(
                    id=len(citations) + 1,
                    source_name="AnySearch",
                    source_url=url,
                    snippet=abstract[:500],
                    retrieval_query=query,
                    retrieval_timestamp=Citation.make_timestamp(),
                ))
            content_parts.append(f"### {title}\n{abstract}\n[来源]({url})")

        return SearchResult(
            source_name="AnySearch",
            content="\n\n".join(content_parts) if content_parts else "No results found.",
            citations=citations or [
                Citation(id=1, source_name="AnySearch", source_url="", snippet="No results found", retrieval_query="", retrieval_timestamp=Citation.make_timestamp())
            ],
            success=bool(content_parts),
        )

    except Exception as e:
        return SearchResult(
            source_name="AnySearch",
            content=f"AnySearch({domain}) error: {e}",
            citations=[
                Citation(id=1, source_name="AnySearch", source_url="", snippet=str(e), retrieval_query="", retrieval_timestamp=Citation.make_timestamp())
            ],
            success=False,
        )


async def anysearch_search(query: str, domain: str = "health") -> str:
    """简易异步包装：供 fallback_chain 使用，返回纯文本"""
    result = await asyncio.to_thread(anysearch_vertical, query, domain=domain, max_results=5)
    return result.content if result else ""
