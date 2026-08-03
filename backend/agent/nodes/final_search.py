"""final_search 节点 — 末轮缺失补全检索

触发条件：decide 判定已达最大轮次(max_rounds)且仍证据不足时，路由到此节点。
行为：汇总缺失信息与已检索内容 → LLM 生成 1-3 条针对性 AnySearch query（英文优先）
→ 并行调用 AnySearch（health 无果转 academic）→ 结果按既有结构并入 retrieval_results
→ 重新编号引用 → 重算 cannot_answer/low_confidence → 路由 synthesize。
"""

import json
import re

from agent.state import AgentState
from config import get_settings
from agent.nodes.context_budget import truncate_with_ellipsis

settings = get_settings()

GAP_QUERY_PROMPT = """你是一个药物原辅料检索查询生成器。用户的某轮检索后证据仍不足，需要补充检索。

## 用户原始问题
{query}

## 当前已检索到的内容摘要（避免重复检索）
{existing}

## 当前判定缺失的信息
{missing}

## 已有的调整建议
{suggestions}

请基于"缺失信息"与"已检索内容"，生成 1-3 条**针对性补充检索 query**（优先英文，因学术/健康库对英文更友好；中文专有名词可保留中文）。每条 query 聚焦一个尚未覆盖的具体维度。

只输出 JSON，不要任何额外文字，格式：
{{"queries": ["query1", "query2"]}}"""


def _extract_queries(text: str, fallback: str) -> list[str]:
    """从 LLM 输出中稳健解析 JSON 的 queries 列表，失败回退为单条 fallback。"""
    try:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            data = json.loads(m.group(0))
            qs = data.get("queries", [])
            if isinstance(qs, list) and qs:
                return [str(q).strip() for q in qs if str(q).strip()][:3]
    except Exception:
        pass
    return [fallback]


def run_final_search(state: AgentState) -> dict:
    """执行末轮缺失补全检索"""
    thinking_steps = list(state.get("thinking_steps", []))

    # 防重入守卫
    if state.get("final_search_done", False):
        thinking_steps.append("末轮补全: 已执行过，跳过")
        return {"thinking_steps": thinking_steps}

    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import SystemMessage, HumanMessage
        from tools.engines import anysearch_engine

        user_query = state.get("user_query", "")
        missing_info = state.get("missing_info", [])
        suggestions = state.get("suggestions", [])
        retrieval_results = state.get("retrieval_results", [])

        # 构造已检索内容摘要，避免重复
        existing_lines = []
        for r in retrieval_results[:20]:
            sn = r.get("source_name", "")
            first_line = r.get("content", "").strip().split("\n")[0][:80]
            existing_lines.append(f"- {sn}: {first_line}")
        existing_digest = "\n".join(existing_lines) if existing_lines else "（无）"

        prompt = GAP_QUERY_PROMPT.format(
            query=user_query,
            existing=existing_digest,
            missing="\n".join(f"- {m}" for m in missing_info) if missing_info else "（无）",
            suggestions="\n".join(f"- {s}" for s in suggestions) if suggestions else "（无）",
        )

        llm = ChatOpenAI(
            model=settings.deepseek_model,
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            temperature=0.2,
        )
        resp = llm.invoke([
            SystemMessage(content="你是严谨的检索查询生成器，只输出要求的 JSON。"),
            HumanMessage(content=prompt),
        ])
        queries = _extract_queries(resp.content, user_query)

        # 调用 AnySearch：health 优先 + academic 并行兜底，合并为 1 次 batch（配额友好）
        added_results = []
        batch_items = []
        for q in queries:
            # 每个 query 同时发起 health 垂直 + academic 生物医学双通道，一次 batch 全含
            batch_items.append({"query": q, "domain": "health", "max_results": 8})
            batch_items.append({"query": q, "domain": "academic",
                                "sub_domain": "academic.biomedical", "max_results": 8})
        batch_res = anysearch_engine.anysearch_batch(batch_items)
        for i, q in enumerate(queries):
            r_health = batch_res[i * 2] if i * 2 < len(batch_res) else None
            r_acad = batch_res[i * 2 + 1] if i * 2 + 1 < len(batch_res) else None
            r = r_health if (r_health and "No results" not in r_health.content) else r_acad
            if r is None:
                r = r_health
            has_citations = bool(r and r.citations)
            added_results.append({
                "source_name": "anysearch_fallback",
                "content": truncate_with_ellipsis(r.content, settings.retrieval_max_store_chars),
                "citations": [c.to_dict() for c in r.citations] if r else [],
                "success": has_citations,
                "failure": not has_citations,
            })

        # 引用重新编号并入
        existing_citations = list(state.get("citations", []))
        next_id = len(existing_citations) + 1
        new_citations = []
        for res in added_results:
            for c in res["citations"]:
                c["id"] = next_id
                new_citations.append(c)
                next_id += 1

        updated_results = retrieval_results + added_results
        updated_citations = existing_citations + new_citations

        any_success_final = any(x.get("success") for x in updated_results)
        cannot_answer = not any_success_final
        low_confidence = not any_success_final

        hit = sum(1 for x in added_results if x["success"])
        thinking_steps.append(
            f"末轮补全: LLM生成 {len(queries)} 条 query，命中 {hit} 条结果 "
            f"(cannot_answer={cannot_answer})"
        )

        return {
            "retrieval_results": updated_results,
            "citations": updated_citations,
            "final_search_done": True,
            "cannot_answer": cannot_answer,
            "low_confidence": low_confidence,
            "thinking_steps": thinking_steps,
        }
    except Exception as e:
        thinking_steps.append(f"末轮补全: 执行异常，跳过 → {e}")
        return {"thinking_steps": thinking_steps}
