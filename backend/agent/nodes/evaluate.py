"""evaluate + synthesize 节点

evaluate: LLM语义评估检索充分性 + 规则质量分计算
synthesize: 多源整合 + 强制内联引用 [N] + 参考资料列表
"""

import json
import re
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from agent.state import AgentState
from config import get_settings
from agent.runtime_cfg import get_param
from agent.nodes.context_budget import allocate_per_source_chars, truncate_with_ellipsis
from agent.nodes.history_utils import smart_truncate

settings = get_settings()


# === evaluate 节点（LLM语义评估 + 规则质量分） ===

EVALUATE_PROMPT = """你是药物原辅料信息检索的评估专家。
根据当前检索结果，判断是否有充分信息回答用户的原始问题。

请严格按以下JSON格式输出：
{
  "is_sufficient": true或false,
  "confidence": "high/medium/low",
  "missing_info": ["缺失项1", "缺失项2"],
  "suggestion": "如果信息不足，建议下一步的检索方向（具体的工具名和查询策略）"
}

判断标准（非常重要）：
- 用户问到的每个关键方面都必须有对应的检索结果覆盖
- 如果用户问的是"临床试验"的上层信息（入组人数、剂量、主要终点等），仅有摘要或标题远远不够，需要具体数据
- 不要因为关键词在内容中出现就判定为充分——必须内容实质覆盖了用户的问题
- 数值型事实必须有明确来源
- 如果关键方面缺失 → 必须标记为 insufficient，并具体指出缺失什么、建议用什么工具补充
"""


def _calc_content_quality(state: AgentState) -> float:
    """纯规则计算内容质量分（与 validate.py 一致，供 decide 做安全网）"""
    keywords_zh = state.get("keywords_zh", [])
    keywords_en = state.get("keywords_en", [])
    entities = state.get("entities", [])
    retrieval_results = state.get("retrieval_results", [])

    if not retrieval_results:
        return 0.0

    all_keywords = set(kw.lower() for kw in keywords_zh + keywords_en + entities)
    all_content = " ".join(r.get("content", "") for r in retrieval_results).lower()

    matched_keywords = sum(1 for kw in all_keywords if kw in all_content)
    total_keywords = max(len(all_keywords), 1)
    keyword_score = matched_keywords / total_keywords

    total_length = sum(len(r.get("content", "")) for r in retrieval_results)
    length_score = min(total_length / 2000.0, 1.0)

    success_sources = sum(1 for r in retrieval_results if r.get("success"))
    source_score = min(success_sources / 3.0, 1.0)

    return round(keyword_score * 0.5 + length_score * 0.3 + source_score * 0.2, 2)


def run_evaluate(state: AgentState) -> dict:
    """LLM语义评估（主）+ 规则质量分（辅）"""
    user_query = state.get("user_query", "")
    retrieval_results = state.get("retrieval_results", [])
    round_count = state.get("round_count", 1)
    thinking_steps = state.get("thinking_steps", [])
    messages = state.get("messages", [])

    # 规则质量分
    content_quality = _calc_content_quality(state)

    # 注入对话历史上下文（用于追问场景的评估，智能截断保护数值/实体）
    history_ctx = ""
    if len(messages) > 1:
        recent = messages[-2 * max(get_param("history_inject_rounds", settings.history_inject_rounds), 1):]
        history_ctx = "\n对话历史（注意用户是追问）:\n" + "\n".join(
            f"{'用户' if getattr(m, 'type', None) == 'human' else '助手'}: {smart_truncate(str(getattr(m, 'content', m)), get_param('history_smart_truncate_chars', settings.history_smart_truncate_chars))}"
            for m in recent
        )

    # 构造检索结果文本（动态预算：按源数分配，单源≤上限、总量≤预算）
    per_source = allocate_per_source_chars(
        len(retrieval_results),
        get_param("retrieval_max_total_chars", settings.retrieval_max_total_chars),
        get_param("retrieval_max_chars_per_source", settings.retrieval_max_chars_per_source),
    )
    results_text = "\n\n".join(
        f"[{r.get('source_name', '?')}]\n{truncate_with_ellipsis(r.get('content', ''), per_source)}"
        for r in retrieval_results
    )

    # 跨轮次评估记忆：注入上一轮的缺失信息，帮助LLM做增量判断
    prev_missing = state.get("missing_info", [])
    missing_context = ""
    if prev_missing and round_count > 1:
        missing_context = (
            f"\n上一轮缺失信息: {', '.join(prev_missing)}\n"
            f"请检验本轮检索结果是否已覆盖上述缺失项。\n"
        )

    human_text = (
        f"用户问题: {user_query}\n"
        f"检索轮次: {round_count}\n"
        f"当前检索源数量: {len(retrieval_results)}\n"
        f"规则质量分: {content_quality:.2f} (仅供参考，不作为主要判断依据)\n"
        f"{missing_context}\n"
        f"检索结果（动态预算，单源≤{settings.retrieval_max_chars_per_source}字符/源）:\n{results_text}"
    )
    if history_ctx:
        human_text = history_ctx + "\n\n" + human_text

    llm = ChatOpenAI(
        model=settings.deepseek_model,
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        temperature=0.1,
    )

    try:
        response = llm.invoke([
            SystemMessage(content=EVALUATE_PROMPT),
            HumanMessage(content=human_text),
        ])

        content = response.content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()

        result = json.loads(content)
        is_sufficient = result.get("is_sufficient", False)
        confidence = result.get("confidence", "medium")
        missing = result.get("missing_info", [])
        suggestion = result.get("suggestion", "")

        thinking_message = (
            f"④ 信息评估(LLM): {'充分' if is_sufficient else '不足'} "
            f"(置信度={confidence}, 规则分={content_quality:.2f}, 第{round_count}轮)"
        )
        if missing:
            thinking_message += f"\n   缺失: {', '.join(missing[:3])}"
        thinking_steps.append(thinking_message)

        return {
            "is_sufficient": is_sufficient,
            "confidence": confidence,
            "content_quality": content_quality,
            "missing_info": missing if missing else [],
            "suggestions": [suggestion] if suggestion else [],
            "evaluation_details": {"confidence": confidence, "suggestion": suggestion, "missing": missing, "content_quality": content_quality},
            "thinking_steps": thinking_steps,
        }

    except Exception as e:
        # LLM 解析失败：用规则质量分作为降级判断
        force_sufficient = content_quality >= 0.6
        thinking_steps.append(
            f"④ 信息评估: LLM异常({e}) → 降级到规则判断 (规则分={content_quality:.2f}, 判定={'充分' if force_sufficient else '不足'})"
        )
        return {
            "is_sufficient": force_sufficient,
            "confidence": "low",
            "content_quality": content_quality,
            "missing_info": [],
            "suggestions": [],
            "evaluation_details": {"confidence": "low", "suggestion": "", "missing": [], "content_quality": content_quality},
            "thinking_steps": thinking_steps,
        }


# === synthesize 节点 ===

SYNTHESIZE_PROMPT = """你是药物原辅料知识问答助手。你的知识来源于以下检索结果，你必须严格遵守引用规则回答用户问题。

## 铁律（必须遵守，违反任何一条的回答无效）：

1. **每一个事实性陈述必须用 [N] 标注引用序号**
2. **无法找到来源的信息 → 明确告知用户"该信息在已检索的权威源中未找到"**
3. **绝不编造引用链接，绝不伪造 source_url**
4. **对于数值型事实（分子量、剂量、LD50等），每个数值必须单独标注其来源引用**
5. **回答开头必须用 1-2 句直接回应核心问题（结论前置），然后再展开细节；禁止以长篇铺垫开头**
6. **回答末尾必须包含 `## 总结` 章节（2-4 句核心结论）；缺失此章节视为回答无效**
7. **若证据不足（cannot_answer / low_confidence 为真）：必须在 `## 总结` 中追加"证据有限，建议核实 FDA/NMPA/PubChem 等官方来源"**

## 回答组织（核心调整）：

- 根据用户问题意图（{intent}）和实际检索内容**自行组织章节**，只展开与问题相关且有证据支撑的维度；检索未覆盖的维度要明确说"未找到"。
- **禁止机械套用固定结构**：不要对所有问题都套"基本信息/适应证/制剂/安全/法规"五段；只有当参考骨架明确适用时才采用。
- 窄问题（用户只问一个具体数值或事实，如"XX 最大用量是多少"）→ 直接回答该问题并补充必要上下文即可，不要强行展开无关维度。

## 质量三原则（必须满足）：

- **【详细】** 每个相关维度展开到"可直接使用"的深度，给出具体事实/数据/情形，不得仅列名词或一句话带过；浅尝辄止视为不合格。
- **【逻辑支撑】** 按"观点→证据→来源"链条组织；涉及因果/对比/权衡时写出推理过程，让读者看到"为什么"；无证据支撑的推断须标注"推测/未经检索证实"。
- **【可读】** 用层级小标题切分；宜对比处用对比表；长段落拆短；专业术语首次出现给简要解释；避免无标点罗列与重复表述。

## 参考骨架（仅当相关时使用，非强制）：

- comparison → 逐维度对比表（结构/机制/适应证/安全性/用法）
- excipient_info → 功能/用量范围/配伍/安全性/法规
- safety → 不良反应/禁忌/相互作用/特殊人群
- mechanism → 靶点/通路/结合方式
- 窄问题 → 1-2 段直给，不凑章节

## 收尾结构（必须遵守）：

`## 总结`（核心结论，2-4 句）
`---`
`📚 参考资料`（含来源 URL）

## 当前检索结果:
{results}

## 可用引用列表:
{citations}

## 用户问题: {query}

## 问题意图: {intent}

## 硬性输出格式（最后确认，必须严格遵守）：
1. **第 1 段**：用 1-2 句直接回答用户的核心问题（结论前置），不要以长篇铺垫开头。
2. **中间**：按上述自行组织的章节展开细节。
3. **结尾**：必须出现 `## 总结` 章节（2-4 句核心结论）；紧接着用 `---` 分隔并列出 `📚 参考资料`。**缺失 `## 总结` 章节视为不合格回答。**

请开始回答。"""


def _generate_summary(text: str, llm) -> str:
    """兜底：当主合成未生成 `## 总结` 章节时，基于已有答案再生成一段总结。"""
    try:
        resp = llm.invoke([
            SystemMessage(content=(
                "你是文本总结助手。请基于下面的回答，用 2-4 句中文写出核心结论总结，"
                "不要引入回答中未出现的新事实。只输出总结正文，不要加任何标题。"
            )),
            HumanMessage(content=text[:4000]),
        ])
        summary = resp.content.strip()
        if summary:
            return "## 总结\n\n" + summary
    except Exception:
        pass
    return ""


def run_synthesize(state: AgentState) -> dict:
    """执行 synthesize 节点"""
    user_query = state.get("user_query", "")
    retrieval_results = state.get("retrieval_results", [])
    citations = state.get("citations", [])
    thinking_steps = state.get("thinking_steps", [])
    messages = state.get("messages", [])
    cannot_answer = state.get("cannot_answer", False)
    low_confidence = state.get("low_confidence", False)
    intent = state.get("intent", "") or "未指定"

    # 注入对话历史（帮助追问时保持一致性，智能截断保护数值/实体；
    # 跳过已压缩最旧消息，附加会话摘要与实体记忆）
    history_ctx = ""
    summary_rounds = state.get("summary_rounds", 0) or 0
    session_summary = state.get("session_summary", "") or ""
    entity_memory = state.get("entity_memory", {}) or {}
    available = messages[2 * summary_rounds:] if 2 * summary_rounds < len(messages) else messages
    history_parts = []
    if session_summary:
        history_parts.append(f"[会话摘要]\n{session_summary[:1200]}")
    if len(available) > 1:
        recent = available[-2 * max(get_param("history_inject_rounds", settings.history_inject_rounds), 1):]  # 最近 N 轮
        for m in recent:
            role = "用户" if getattr(m, "type", None) == "human" else "助手"
            history_parts.append(
                f"{role}: {smart_truncate(str(getattr(m,'content',m)), get_param('history_smart_truncate_chars', settings.history_smart_truncate_chars))}"
            )
    if history_parts:
        history_ctx = "\n对话历史:\n" + "\n".join(history_parts)

    # 构造检索结果文本（动态预算：按源数分配，单源≤上限、总量≤预算）
    per_source = allocate_per_source_chars(
        len(retrieval_results),
        get_param("retrieval_max_total_chars", settings.retrieval_max_total_chars),
        get_param("retrieval_max_chars_per_source", settings.retrieval_max_chars_per_source),
    )
    results_text = "\n\n".join(
        f"--- {r.get('source_name', '?')} ---\n{truncate_with_ellipsis(r.get('content', ''), per_source)}"
        for r in retrieval_results
    )

    # 构造引用文本
    citations_text = "\n".join(
        f"[{c.get('id', i+1)}] {c.get('source_name', '?')}: {c.get('source_url', '')}"
        for i, c in enumerate(citations)
    )

    llm = ChatOpenAI(
        model=settings.deepseek_model,
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        temperature=0.2,
    )

    prompt = SYNTHESIZE_PROMPT.format(
        results=results_text,
        citations=citations_text,
        query=user_query,
        intent=intent,
    )

    if history_ctx:
        prompt = history_ctx + "\n" + prompt

    if cannot_answer or low_confidence:
        prompt += (
            "\n\n## 重要提示\n"
            "本轮检索未能从权威数据库获取充分证据，请在回答中明确说明证据有限/不足，"
            "并建议用户核实官方来源（如 FDA、NMPA、PubChem 等）。不要编造具体数值或来源。"
        )

    try:
        response = llm.invoke([
            SystemMessage(content=prompt),
            HumanMessage(content=user_query),
        ])

        final_answer = response.content.strip()
        if cannot_answer:
            final_answer = "⚠️ 提示：检索未能从权威数据库找到充分证据，以下回答仅供参考，请核实官方来源。\n\n" + final_answer
        # 规范化：模型可能输出 "## N. 总结"，统一为 "## 总结"
        final_answer = re.sub(r"^##\s+\d+\.\s*总结\s*$", "## 总结", final_answer, flags=re.MULTILINE)
        if not re.search(r"^##\s+总结\s*$", final_answer, re.MULTILINE):
            summary = _generate_summary(final_answer, llm)
            if summary:
                final_answer = final_answer.rstrip() + "\n\n" + summary
            else:
                first_para = final_answer.strip().split("\n\n")[0][:200]
                final_answer = final_answer.rstrip() + f"\n\n## 总结\n\n{first_para}"
        thinking_steps.append(f"⑤ 答案合成: 完成, {len(final_answer)} 字符")

        return {
            "final_answer": final_answer,
            "messages": [{"role": "assistant", "content": final_answer}],
            "thinking_steps": thinking_steps,
        }

    except Exception as e:
        # 降级：直接拼接检索结果
        fallback = "\n\n".join(
            f"[{r.get('source_name', '?')}]\n{r.get('content', '')[:1000]}"
            for r in retrieval_results if r.get('success')
        )
        answer_text = fallback or f"抱歉，检索过程出现异常，无法回答 '{user_query}'。"
        if cannot_answer:
            answer_text = "⚠️ 检索未能从权威源找到充分信息，无法提供可靠回答。\n\n" + answer_text
        thinking_steps.append(f"⑤ 答案合成: LLM异常,使用降级拼接")

        return {
            "final_answer": answer_text,
            "messages": [{"role": "assistant", "content": answer_text}],
            "thinking_steps": thinking_steps,
        }
