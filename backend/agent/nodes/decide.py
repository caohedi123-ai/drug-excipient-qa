"""decide_next 节点 — 基于 LLM评估 + 规则下限 的白盒路由决策"""

from agent.state import AgentState
from config import get_settings
from agent.runtime_cfg import get_param

settings = get_settings()


def run_decide(state: AgentState) -> dict:
    """路由决策：LLM is_sufficient 做主判断，content_quality 做安全网

    决策逻辑：
    1. is_sufficient=True 且 confidence=high/medium → synthesize
    2. is_sufficient=True 但 confidence=low → 需要 content_quality≥0.5 才通过
    3. is_sufficient=False → adjust_plan（重新检索）
    4. 防死循环: round_count ≥ max_rounds → 强制 synthesize
    """
    is_sufficient = state.get("is_sufficient", False)
    content_quality = state.get("content_quality", 0.0)
    confidence = state.get("confidence", "low")
    round_count = state.get("round_count", 1)
    missing_info = state.get("missing_info", [])
    suggestions = state.get("suggestions", [])
    failure_reasons = state.get("failure_reasons", [])
    thinking_steps = state.get("thinking_steps", [])

    max_rounds = get_param("max_retrieval_rounds", settings.max_retrieval_rounds)

    retrieval_results = state.get("retrieval_results", [])
    any_success = any(r.get("success") for r in retrieval_results)
    failed_tools = state.get("failed_tools", [])
    used_fallback = any(r.get("source_name") == "anysearch_fallback" for r in retrieval_results)

    # 终止与置信度默认值
    cannot_answer = False
    low_confidence = content_quality < 0.5
    force_fallback = False

    # 防死循环：绝对上限保护
    if round_count >= max_rounds:
        final_search_done = state.get("final_search_done", False)
        still_insufficient = (not is_sufficient) or (not any_success) or (content_quality < 0.35)
        # 到顶仍不足 → 先走末轮缺失补全搜索(final_search)做最后补救，再合成
        if still_insufficient and not final_search_done:
            thinking_steps.append(
                f"⑥ 路由决策: 已达最大轮次({max_rounds})仍不足 → 末轮补全搜索(final_search)"
            )
            return {
                "next_action": "final_search",
                "thinking_steps": thinking_steps,
            }
        cannot_answer = (not any_success) or (content_quality < 0.35)
        thinking_steps.append(
            f"⑥ 路由决策: 已达最大轮次({max_rounds}) → 强制合成 "
            f"(证据充足={any_success}, 质量分={content_quality:.2f}, cannot_answer={cannot_answer})"
        )
        return {
            "next_action": "synthesize",
            "is_sufficient": True,
            "cannot_answer": cannot_answer,
            "low_confidence": low_confidence or cannot_answer,
            "thinking_steps": thinking_steps,
        }

    # 核心决策：LLM is_sufficient 为主，规则质量分为安全网
    if is_sufficient:
        if confidence in ("high", "medium"):
            action = "synthesize"
            reason = f"LLM评估充分(confidence={confidence})"
        elif content_quality >= 0.5:
            action = "synthesize"
            reason = f"LLM标记充分但置信度低，规则质量分{content_quality:.2f}≥0.5通过"
        else:
            action = "adjust_plan"
            reason = f"LLM标记充分但置信度=low且质量分{content_quality:.2f}<0.5 → 继续检索"
        thinking_steps.append(f"⑥ 路由决策: {reason} → {'合成回答' if action=='synthesize' else '调整检索'}")
    else:
        action = "adjust_plan"
        adj_suggestions = []
        if missing_info:
            adj_suggestions = [f"补充: {m}" for m in missing_info[:3]]
        if not adj_suggestions:
            adj_suggestions = ["切换查询角度: 扩展同义词、中英文切换、切换数据源"]
        # 决策级兜底：证据不足/失败源较多时，强制下一轮引入 AnySearch 泛搜（程序化保证，非仅文本建议）
        force_fallback = (content_quality < 0.4) or (not any_success) or (len(failed_tools) >= 3 and not used_fallback)
        if force_fallback:
            adj_suggestions.append("已强制下一轮引入 anysearch_fallback_tool 做全网泛搜兜底")
        else:
            adj_suggestions.append("若专有源仍不足，下一轮务必加入 anysearch_fallback_tool 做全网泛搜兜底")
        suggestions = adj_suggestions
        failure_reasons = missing_info.copy()
        thinking_steps.append(
            f"⑥ 路由决策: LLM评估不足(confidence={confidence},质量分={content_quality:.2f}) "
            f"→ 调整计划重试 (第{round_count}轮/{max_rounds}轮)"
        )

    return {
        "next_action": action,
        "is_sufficient": action == "synthesize",
        "suggestions": suggestions,
        "failure_reasons": failure_reasons,
        "force_fallback": force_fallback,
        "cannot_answer": cannot_answer,
        "low_confidence": low_confidence,
        "thinking_steps": thinking_steps,
    }
