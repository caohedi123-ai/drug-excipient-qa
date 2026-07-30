"""Exa 搜索引擎封装 - 语义深研引擎

设计要点：
- 语义神经搜索（非关键词匹配），适合深度研究场景
- deep-reasoning 多步推理搜索
- findSimilar 关联发现
- outputSchema 结构化数据抽取
- Phase 2 接入，Phase 1 可用但非必须
"""

import httpx
from datetime import datetime, timezone
from agent.state import Citation, SearchResult
from config import get_settings

settings = get_settings()
EXA_BASE = "https://api.exa.ai"


def _headers() -> dict:
    return {
        "x-api-key": settings.exa_api_key,
        "Content-Type": "application/json",
    }


def _is_available() -> bool:
    return bool(settings.exa_api_key)


def exa_deep_search(
    query: str,
    search_type: str = "auto",
    category: str = "research publication",
    include_domains: list[str] | None = None,
    num_results: int = 10,
    output_schema: dict | None = None,
) -> SearchResult:
    """Exa 语义深研搜索

    Args:
        query: 研究问题（自然语言）
        search_type: "auto" / "deep-reasoning" / "neural"
        category: "research publication" 限定学术出版物
        include_domains: 域名限定（可选）
        num_results: 返回数量
        output_schema: 结构化抽取 schema（可选）

    Returns:
        SearchResult 统一结果容器
    """
    if not _is_available():
        return SearchResult.empty("Exa", "Exa API Key 未配置，Phase 2 启用")

    try:
        payload = {
            "query": query,
            "type": search_type,
            "numResults": num_results,
            "contents": {"text": {"maxCharacters": 1000}},
        }
        if category:
            payload["category"] = category
        if include_domains:
            payload["includeDomains"] = include_domains

        resp = httpx.post(
            f"{EXA_BASE}/search",
            json=payload,
            headers=_headers(),
            timeout=60.0,
            trust_env=False,
        )
        resp.raise_for_status()
        data = resp.json()

        citations: list[Citation] = []
        content_parts: list[str] = []
        results = data.get("results", [])

        for i, item in enumerate(results, 1):
            url = item.get("url", "")
            text = item.get("text", "")
            title = item.get("title", "")
            snippet = text[:300] if text else ""

            if url:
                citations.append(Citation(
                    id=i,
                    source_name=title or "Exa",
                    source_url=url,
                    snippet=snippet,
                    retrieval_query=query,
                    retrieval_timestamp=Citation.make_timestamp(),
                ))
            content_parts.append(f"[{i}] {title}\n{snippet}\n{url}")

        return SearchResult(
            source_name="Exa(deep)",
            content="\n\n---\n".join(content_parts)[:3000],
            citations=citations,
            raw_urls=[r.get("url", "") for r in results],
            success=bool(citations),
        )

    except Exception as e:
        return SearchResult.empty("Exa", f"搜索异常: {e}")


def exa_find_similar(
    url: str,
    num_results: int = 10,
    exclude_source_domain: bool = False,
) -> SearchResult:
    """Exa 相似内容发现 - 基于已知文献找引用链和类似研究

    Args:
        url: 已知文献 URL
        num_results: 返回数量
        exclude_source_domain: 是否排除同域名

    Returns:
        SearchResult 统一结果容器
    """
    if not _is_available():
        return SearchResult.empty("Exa(findSimilar)", "Exa API Key 未配置")

    try:
        payload = {
            "url": url,
            "numResults": num_results,
            "excludeSourceDomain": exclude_source_domain,
            "contents": {"text": {"maxCharacters": 1000}},
        }
        resp = httpx.post(
            f"{EXA_BASE}/findSimilar",
            json=payload,
            headers=_headers(),
            timeout=30.0,
            trust_env=False,
        )
        resp.raise_for_status()
        data = resp.json()

        citations: list[Citation] = []
        content_parts: list[str] = [f"来源: {url}"]
        results = data.get("results", [])

        for i, item in enumerate(results, 1):
            item_url = item.get("url", "")
            text = item.get("text", "")
            title = item.get("title", "")
            snippet = text[:300] if text else ""

            if item_url:
                citations.append(Citation(
                    id=i,
                    source_name=title or "Exa(findSimilar)",
                    source_url=item_url,
                    snippet=snippet,
                    retrieval_query=f"findSimilar({url})",
                    retrieval_timestamp=Citation.make_timestamp(),
                ))
            content_parts.append(f"[{i}] {title}\n{snippet}\n{item_url}")

        return SearchResult(
            source_name="Exa(findSimilar)",
            content="\n\n---\n".join(content_parts)[:3000],
            citations=citations,
            success=bool(citations),
        )

    except Exception as e:
        return SearchResult.empty("Exa(findSimilar)", f"异常: {e}")
