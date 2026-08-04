"""retrieve 节点 - 并行调用工具 + Citation 自动追加

根据 plan 节点输出的检索计划，并行调用对应的工具函数，
将每个工具的返回结果追加到 state.citations。
"""

import asyncio
import json
from agent.state import AgentState, Citation, SearchResult
from tools import TOOLS_BY_NAME
from tools.engines import anysearch_engine
from config import get_settings
from agent.runtime_cfg import get_param
from agent.nodes.context_budget import truncate_with_ellipsis

settings = get_settings()


async def run_retrieve(state: AgentState) -> dict:
    """执行 retrieve 节点（异步，避免自建事件循环嵌套）"""
    return await _run_retrieve_async(state)


async def _run_retrieve_async(state: AgentState) -> dict:
    """异步执行并行检索"""
    plan = state.get("_plan", [])
    thinking_steps = state.get("thinking_steps", [])
    sub_questions = state.get("sub_questions", [])
    user_query = state.get("user_query", "")
    round_count = state.get("round_count", 0) + 1

    # 累积引用列表（追加不覆盖）
    existing_citations: list[dict] = state.get("citations", [])
    next_citation_id = len(existing_citations) + 1

    # 如果没有 plan（plan 节点异常），直接构造默认 plan
    if not plan:
        plan = [
            {"tool": "pubchem_tool", "query_en": user_query, "query_zh": user_query, "reason": "默认检索"}
        ]

    # 并行调用所有工具
    tasks = []
    skipped_tools = []
    for item in plan:
        tool_name = item.get("tool", "")
        query = item.get("query_en", item.get("query_zh", user_query))
        tool_fn = TOOLS_BY_NAME.get(tool_name)

        if tool_fn:
            tasks.append(_invoke_tool(tool_fn, query, tool_name))
        else:
            skipped_tools.append(tool_name)

    if skipped_tools:
        thinking_steps.append(f"③ 跳过未注册工具: {', '.join(skipped_tools)}")

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 处理结果：提取 citation 并重新编号
    all_results: list[dict] = []
    new_citations: list[dict] = []

    for i, (item, result) in enumerate(zip(plan, results)):
        tool_name = item.get("tool", f"tool_{i}")
        if isinstance(result, Exception):
            all_results.append({
                "source_name": tool_name,
                "content": f"[异常] {str(result)}",
                "success": False,
            })
            continue

        # 解析工具返回字符串（格式: [SourceName] content\n\n__citations__: [...]）
        result_str = str(result)
        content_part = result_str
        tool_citations: list[dict] = []

        if "__citations__:" in result_str:
            parts = result_str.split("__citations__:", 1)
            content_part = parts[0].strip()
            try:
                tool_citations = json.loads(parts[1].strip())
            except json.JSONDecodeError:
                pass

        # 重新编号 citations
        for tc in tool_citations:
            tc["id"] = next_citation_id
            next_citation_id += 1
            new_citations.append(tc)

        # === 真实成功判定（修复原 'success: True' 硬编码 bug）===
        # 有结构化引用 → 成功；否则内容非空且非失败占位（未找到/调用失败/No results）才视为成功
        FAILURE_MARKERS = [
            "未找到", "未返回", "未查询到", "调用失败", "异常",
            "[无结果]", "无结果", "无匹配", "no results found", "not found",
            "无相关信息", "API无返回", "搜索无结果", "no match",
        ]
        has_citations = bool(tool_citations)
        is_failure = (not has_citations) and any(
            m.lower() in content_part.lower() for m in FAILURE_MARKERS
        )
        real_success = has_citations or (content_part.strip() != "" and not is_failure)

        all_results.append({
            "source_name": tool_name,
            "content": truncate_with_ellipsis(content_part, get_param("retrieval_max_store_chars", settings.retrieval_max_store_chars)),
            "citations": tool_citations,
            "success": real_success,
            "failure": (not real_success),
        })

    # === 轮次级硬保底：本轮无有效结果，或决策层强制兜底时，自动启用 AnySearch 泛搜 ===
    valid_results = [r for r in all_results if r.get("success") and r.get("content", "").strip()]
    force_fallback = bool(state.get("force_fallback")) and not any(
        r.get("source_name") == "anysearch_fallback" for r in all_results
    )
    if not valid_results or force_fallback:
        try:
            fb = await asyncio.to_thread(
                anysearch_engine.anysearch_vertical, user_query, domain="health", max_results=10
            )
            if "No results" not in fb.content:
                fb_citations = [c.to_dict() for c in fb.citations]
                for tc in fb_citations:
                    tc["id"] = next_citation_id
                    next_citation_id += 1
                    new_citations.append(tc)
                all_results.append({
                    "source_name": "anysearch_fallback",
                    "content": truncate_with_ellipsis(fb.content, get_param("retrieval_max_store_chars", settings.retrieval_max_store_chars)),
                    "citations": fb_citations,
                    "success": True,
                    "failure": False,
                })
                thinking_steps.append("③ 兜底: 已自动启用 AnySearch 泛搜保底")
            else:
                thinking_steps.append("③ 兜底: AnySearch 泛搜亦无结果")
        except Exception as e:
            thinking_steps.append(f"③ 兜底: AnySearch 保底调用异常: {e}")

    # 统计本轮成败：供 plan/adjust 排除失效源，并提升可观测性（修复"查不到无日志"痛点）
    failed_tool_names = [r["source_name"] for r in all_results if not r.get("success")]
    error_count = sum(
        1 for r in all_results
        if "调用失败" in r.get("content", "") or "异常" in r.get("content", "")[:30]
    )
    success_count = len(all_results) - len(failed_tool_names)
    noresult_count = len(failed_tool_names) - error_count
    thinking_steps.append(
        f"③ 本轮: {success_count} 成功 / {noresult_count} 未找到 / {error_count} 异常"
    )
    existing_failed: list[str] = state.get("failed_tools", [])
    failed_tools = existing_failed + [n for n in failed_tool_names if n not in existing_failed]

    # 累积检索结果（追加而非覆盖） + 记录检索历史
    existing_results: list[dict] = state.get("retrieval_results", [])
    existing_history: list[dict] = state.get("search_history", [])

    round_entry = {
        "round": round_count,
        "query": user_query,
        "tools_used": [p.get("tool") for p in plan],
        "results_count": sum(1 for r in all_results if r.get("success")),
        "citation_count": len(new_citations),
    }
    existing_history.append(round_entry)

    thinking_message = (
        f"③ 第 {round_count} 轮检索: 调用 {len(plan)} 个工具, "
        f"获得 {sum(1 for r in all_results if r.get('success'))} 个有效结果, "
        f"新增 {len(new_citations)} 条引用"
    )
    thinking_steps.append(thinking_message)

    return {
        "retrieval_results": existing_results + all_results,
        "citations": existing_citations + new_citations,
        "round_count": round_count,
        "search_history": existing_history,
        "thinking_steps": thinking_steps,
        "failed_tools": failed_tools,
    }


async def _invoke_tool(tool_fn, query: str, tool_name: str) -> str:
    """调用单个工具 - 兼容 async/sync 与不同 LangChain 版本

    调用策略（单参数 query 工具）：
      1. 优先用原始函数 tool.func（若存在且可异步/同步直接调用）
      2. 否则统一用 ainvoke(query)（传字符串，所有工具均为单参数）
      3. 最后回退到 invoke(query)
    """
    try:
        func = getattr(tool_fn, "func", None)
        if func is not None and asyncio.iscoroutinefunction(func):
            result = await func(query)
        elif func is not None and callable(func):
            result = func(query)
        elif hasattr(tool_fn, "ainvoke"):
            result = await tool_fn.ainvoke(query)
        else:
            result = tool_fn.invoke(query)
            if asyncio.iscoroutine(result):
                result = await result
        return result if isinstance(result, str) else str(result)
    except Exception as e:
        return f"[{tool_name}] 调用失败: {e}"
