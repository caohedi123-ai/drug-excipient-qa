"""adjust_plan 节点 — 基于缺失信息调整检索策略"""

import json
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from config import get_settings
from agent.state import AgentState
from agent.prompts import get_tool_descriptions
from tools import TOOLS_BY_NAME

settings = get_settings()

ADJUST_SYSTEM_PROMPT = f"""你是药物检索策略调整助手。根据当前缺失的信息，重新规划检索方案。

{get_tool_descriptions()}

请严格按以下JSON格式输出，不要输出任何其他内容：

{{
  "plan": [
    {{
      "tool": "工具名",
      "query_en": "英文检索词",
      "query_zh": "中文检索词",
      "reason": "选择原因"
    }}
  ]
}}

调整策略指南（核心：本轮需与前几轮形成差异化）：
- 如果"关键词匹配率低" → 中英文切换、使用同义词、使用药物别名
- 如果"内容过短" → 切换到更详细的源（DailyMed标签全文、Wikipedia长文章）
- 如果"来源不足" → 增加数据源数量、使用更通用的查询
- PubChem/DrugBank/DrugCentral 只用纯化合物英文名（≤3词）
- Wikipedia 可用完整自然语言查询
- **重点：优先选择本轮尚未使用过的工具，换查询角度（如同义词、中文词、相关概念），避免与前述已用查询词重复**"""


def _finalize_plan(plan: list, force_fallback: bool, failed_tools: list) -> list:
    """去重、剔除未注册工具、必要时强制加入 AnySearch 泛搜兜底"""
    seen: set = set()
    out: list = []
    for p in plan:
        name = p.get("tool", "")
        if not name or name in seen or name not in TOOLS_BY_NAME:
            continue
        seen.add(name)
        out.append(p)
    if force_fallback and "anysearch_fallback_tool" not in seen:
        out.append({
            "tool": "anysearch_fallback_tool",
            "query_en": "",
            "query_zh": "",
            "reason": "决策级强制泛搜兜底",
        })
    return out


def run_adjust(state: AgentState) -> dict:
    """基于 validate + decide 的反馈调整检索计划"""
    missing_info = state.get("missing_info", [])
    suggestions = state.get("suggestions", [])
    feedback = state.get("failure_reasons", [])
    user_query = state.get("user_query", "")
    entities = state.get("entities", [])
    thinking_steps = state.get("thinking_steps", [])

    missing_text = ", ".join(missing_info) if missing_info else "未知"
    suggestion_text = "; ".join(suggestions) if suggestions else "自动调整策略"
    entity_text = ", ".join(entities) if entities else "unknown"

    # 提取前几轮已使用的工具和查询词，避免重复
    retrieval_results = state.get("retrieval_results", [])
    tried_entries = []
    for r in retrieval_results:
        src = r.get("source_name", "?")
        snippet = r.get("content", "")[:80].replace("\n", " ")
        tried_entries.append(f"  - {src}: {snippet}...")
    tried_tools_text = "\n".join(tried_entries[:20]) if tried_entries else "（无历史记录）"

    # 读取查询词扩充阶段的结果（expand_queries 节点输出）
    expanded_queries = state.get("expanded_queries", [])
    expanded_names = state.get("expanded_names", {})
    expanded_text = "（无扩充结果）"
    if expanded_queries:
        lines = []
        for eq in expanded_queries:
            dim = eq.get("dimension", "?")
            en_q = eq.get("queries_en", [])
            zh_q = eq.get("queries_zh", [])
            tools = eq.get("best_tools", [])
            lines.append(f"  维度【{dim}】→ 推荐工具: {', '.join(tools[:4]) if tools else '不限'}")
            if en_q:
                lines.append(f"    英文查询词: {', '.join(en_q[:3])}")
            if zh_q:
                lines.append(f"    中文查询词: {', '.join(zh_q[:3])}")
        expanded_text = "\n".join(lines)
        # 追加实体别名信息
        if expanded_names:
            aliases = []
            for k in ("brand_names", "code_names", "chinese_names"):
                vals = expanded_names.get(k, [])
                if vals:
                    aliases.extend(vals[:3])
            if aliases:
                expanded_text += f"\n  药物别名/代号: {', '.join(aliases)}"

    human_text = (
        f"原始问题: {user_query}\n"
        f"已知实体: {entity_text}\n"
        f"缺失信息: {missing_text}\n"
        f"调整建议: {suggestion_text}\n"
        f"失败原因: {', '.join(feedback) if feedback else '无'}\n"
        f"\n=== 查询词扩充建议（请基于此生成 plan，每个工具使用专属查询词，不要所有工具共用同一个词）===\n"
        f"{expanded_text}\n"
        f"\n前几轮已用工具和已查内容（请优先选择不同工具和不同查询角度）:\n{tried_tools_text}\n"
        f"\n请生成新的检索计划。每个工具的查询词必须根据其特性差异化——"
        f"PubChem用纯化合物名，DailyMed用'药名 prescribing information'格式，"
        f"PubMed用'药名 mechanism of action'格式，中文源用中文名。"
    )

    llm = ChatOpenAI(
        model=settings.deepseek_model,
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        temperature=0.3,
    )

    try:
        response = llm.invoke([
            SystemMessage(content=ADJUST_SYSTEM_PROMPT),
            HumanMessage(content=human_text),
        ])
        content = response.content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()

        result = json.loads(content)
        new_plan = result.get("plan", [])
        new_plan = _finalize_plan(new_plan, state.get("force_fallback", False), state.get("failed_tools", []))
        thinking_steps.append(f"⑦ 计划调整: 生成 {len(new_plan)} 个新检索项")
        return {
            "_plan": new_plan,
            "thinking_steps": thinking_steps,
            "force_fallback": False,
        }
    except Exception as e:
        # JSON 解析失败 → 使用降级 plan
        fallback_plan = [
            {"tool": "pubchem_tool", "query_en": user_query, "query_zh": user_query, "reason": "fallback"},
            {"tool": "wikipedia_tool", "query_en": user_query, "query_zh": user_query, "reason": "fallback"},
        ]
        fallback_plan = _finalize_plan(fallback_plan, state.get("force_fallback", False), state.get("failed_tools", []))
        thinking_steps.append(f"⑦ 计划调整: LLM异常({e}) → 使用降级计划({len(fallback_plan)}项)")
        return {
            "_plan": fallback_plan,
            "thinking_steps": thinking_steps,
            "force_fallback": False,
        }
