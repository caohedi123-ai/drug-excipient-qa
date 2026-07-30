"""validate_content 节点 — 内容质量校验（纯规则，无LLM调用）"""

from agent.state import AgentState


def run_validate(state: AgentState) -> dict:
    """纯规则评分：关键词匹配率 + 内容长度 + 来源数量 → 综合评分 0-1

    - 不调用 LLM，纯规则判断
    - 评分不达标时生成 missing_info 供 adjust_plan 使用
    """
    user_query = state.get("user_query", "")
    retrieval_results = state.get("retrieval_results", [])
    round_count = state.get("round_count", 1)
    keywords_zh = state.get("keywords_zh", [])
    keywords_en = state.get("keywords_en", [])
    entities = state.get("entities", [])
    thinking_steps = state.get("thinking_steps", [])

    if not retrieval_results:
        thinking_steps.append("⑤ 内容校验: 无检索结果")
        return {
            "content_quality": 0.0,
            "missing_info": ["No retrieval results at all — all tools failed or returned empty"],
            "thinking_steps": thinking_steps,
        }

    # 1) 关键词匹配率（在内容中出现的比例）
    all_keywords = set(kw.lower() for kw in keywords_zh + keywords_en + entities)
    all_content = " ".join(r.get("content", "") for r in retrieval_results).lower()

    matched_keywords = sum(1 for kw in all_keywords if kw in all_content)
    total_keywords = max(len(all_keywords), 1)
    keyword_score = matched_keywords / total_keywords  # 0-1

    # 2) 内容长度评分（总字符数/2000，上限 1.0）
    total_length = sum(len(r.get("content", "")) for r in retrieval_results)
    length_score = min(total_length / 2000.0, 1.0)

    # 3) 来源数量评分（≥3 满分）
    success_sources = sum(1 for r in retrieval_results if r.get("success"))
    source_score = min(success_sources / 3.0, 1.0)

    # 综合评分
    content_quality = round(keyword_score * 0.5 + length_score * 0.3 + source_score * 0.2, 2)

    missing_info = []
    if keyword_score < 0.4:
        missing_info.append("关键词匹配率低")
    if length_score < 0.3:
        missing_info.append("检索结果内容过短")
    if source_score < 0.5:
        missing_info.append("有效来源不足")

    thinking_steps.append(
        f"⑤ 内容校验: 综合评分={content_quality:.2f} "
        f"(关键词={keyword_score:.2f}, 长度={length_score:.2f}, 来源={source_score:.2f})"
        + (f"\n   缺失: {', '.join(missing_info)}" if missing_info else "")
    )

    return {
        "content_quality": content_quality,
        "missing_info": missing_info,
        "thinking_steps": thinking_steps,
    }
