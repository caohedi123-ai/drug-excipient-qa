"""Tavily 搜索引擎封装 - 域名定向精搜

设计要点：
- 仅用于有明确权威域名的数据源，保护付费额度
- search_depth=advanced 确保深层次搜索
- include_answer=True 生成AI摘要，加速evaluate判断
- 默认不拉取raw_content，非必要不消耗额度
"""

import asyncio
from tavily import TavilyClient
from tavily.errors import InvalidAPIKeyError, UsageLimitExceededError
from agent.state import Citation, SearchResult
from config import get_settings

settings = get_settings()
_client: TavilyClient | None = None


def _get_client() -> TavilyClient:
    global _client
    if _client is None:
        _client = TavilyClient(api_key=settings.tavily_api_key)
    return _client


def tavily_domain_search(
    query: str,
    domains: list[str],
    max_results: int = 8,
    search_depth: str = "advanced",
    include_answer: bool = True,
    include_raw_content: bool = False,
    days: int = 36500,
    topic: str = "general",
) -> SearchResult:
    """Tavily 域名定向精搜

    Args:
        query: 检索关键词（英文，已由plan节点构造）
        domains: 权威源域名列表，如 ["pubchem.ncbi.nlm.nih.gov"]
        max_results: 最大返回结果数
        search_depth: "basic" 或 "advanced"
        include_answer: 是否生成AI答案摘要
        include_raw_content: 是否拉取原始网页全文（保护额度，默认False）
        days: 时日范围（天），默认不限
        topic: "general" 或 "news"

    Returns:
        SearchResult 统一结果容器，含 Citation 列表
    """
    try:
        client = _get_client()
        response = client.search(
            query=query,
            search_depth=search_depth,
            include_domains=domains,
            include_answer=include_answer,
            include_raw_content=include_raw_content,
            max_results=max_results,
            include_images=False,
            days=days,
            topic=topic,
        )

        citations: list[Citation] = []
        content_parts: list[str] = []

        # 1. AI 答案摘要
        if response.get("answer"):
            content_parts.append(f"[AI摘要] {response['answer']}")

        # 2. 逐条搜索结果 → Citation
        for i, result in enumerate(response.get("results", []), 1):
            snippet = (result.get("content") or "")[:300]
            url = result.get("url", "")
            title = result.get("title", "")

            if url:
                citations.append(Citation(
                    id=i,
                    source_name=title or domains[0],
                    source_url=url,
                    snippet=snippet,
                    retrieval_query=query,
                    retrieval_timestamp=Citation.make_timestamp(),
                ))

            content_parts.append(
                f"[{i}] {title}\n{snippet}\n{url}"
            )

        source_name = f"Tavily({','.join(domains)})"
        content = "\n\n---\n".join(content_parts)[:3000]

        return SearchResult(
            source_name=source_name,
            content=content,
            citations=citations,
            raw_urls=[r.get("url", "") for r in response.get("results", [])],
            success=bool(citations),
        )

    except (InvalidAPIKeyError, UsageLimitExceededError) as e:
        return SearchResult.empty(
            source_name=f"Tavily({','.join(domains)})",
            reason=f"Tavily [{type(e).__name__}]: {e}",
        )
    except Exception as e:
        return SearchResult.empty(
            source_name=f"Tavily({','.join(domains)})",
            reason=f"未知错误: {e}",
        )


async def tavily_fulltext_search(query: str, max_results: int = 5) -> str:
    """Tavily 全文抓取（供 fallback_chain Layer 4 使用），返回纯文本"""
    result = await asyncio.to_thread(
        tavily_domain_search,
        query, domains=[], max_results=max_results,
        include_raw_content=True, include_answer=True,
    )
    return result.content if result else ""
