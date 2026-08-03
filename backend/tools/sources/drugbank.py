"""DrugBank 数据源工具 - 药物综合信息

API: DrugBank REST (需 API Key, MVP阶段用 Tavily 域名搜索替代)
Search: Tavily 域名定向搜索 (go.drugbank.com)
"""

import json
import asyncio

from langchain_core.tools import tool
from agent.state import Citation, SearchResult
from tools.engines.tavily_engine import tavily_domain_search


@tool
async def drugbank_tool(query: str) -> str:
    """查询药物基础信息（经 Tavily 域名搜索 go.drugbank.com，非 DrugBank 官方 API）：常见靶点/适应症/相互作用的网页摘要。
    适用场景：作为 DrugBank 官方 API 缺失时的网页检索兜底，获取概览性信息；数据成色低于官方 API，仅供参考。
    Input: 药物名/DrugBank ID（英文搜索效果更好）"""
    result = await _search_drugbank(query)
    if not result.success:
        return f"[DrugBank] 未找到 '{query}' 的相关信息。"

    citations_json = json.dumps([c.to_dict() for c in result.citations], ensure_ascii=False)
    return f"[DrugBank] {result.content}\n\n__citations__: {citations_json}"


async def _search_drugbank(query: str) -> SearchResult:
    """DrugBank 搜索：MVP阶段使用 Tavily 域名定向搜索"""
    # 若配置了 DrugBank API Key，可在此处添加 API 调用
    return await asyncio.to_thread(tavily_domain_search, 
        query + " drugbank",
        domains=["go.drugbank.com"],
        max_results=8,
        search_depth="advanced",
    )
