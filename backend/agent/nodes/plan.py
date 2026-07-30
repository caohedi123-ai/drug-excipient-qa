"""plan 节点 - 数据源选择 + 查询词构造

根据 understand 拆分的子问题和工具描述，选择最相关的数据源工具，
并对每个择选构造差异化的中英文查询词。
"""

import json
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from agent.state import AgentState
from tools import get_tool_descriptions, TOOLS_BY_NAME
from config import get_settings

settings = get_settings()

SYSTEM_PROMPT = f"""你是药物原辅料知识问答系统的检索规划助手。
你的任务是为给定的子问题选择最合适的数据源工具，并构造检索查询词。

{get_tool_descriptions()}

请严格按以下JSON格式输出，不要输出任何其他内容：

{{
  "plan": [
    {{
      "tool": "工具名1",
      "query_en": "英文检索关键词（精炼，≤15词）",
      "query_zh": "中文检索变体",
      "reason": "选择原因"
    }},
    ...
  ]
}}

选择原则：
- 尽可能多地选择相关数据源（不限制工具数量）
- 优先选择有明确 API 覆盖的源
- 药物基础信息 → pubchem, drugbank, drugcentral, chembl, coconut
- 辅料/制剂信息 → fda_iig, fda_unii, fda_ndc, dailymed, fda_orange
- 药品说明书/标签/注册审批 → dailymed, fda_drugs, fda_orange, ema, cde(中国), pmda(日本)
- 安全性/相互作用 → fda_faers, sider, ddinter
- 靶点/基因/药物基因组 → open_targets, bindingdb, pharmgkb, ttd
- 分类标准/指南 → rxnorm, who_atc, ich
- 文献/专利/综合 → pubmed, espacenet(专利), cnipa(中国专利), wikipedia, clinicaltrials(临床试验)
- 若上述专有源均不足以回答，或问题偏冷门/跨领域，务必加入 **anysearch_fallback_tool** 做全网泛搜兜底
- 对每个源构造不同的查询角度（不要所有源用同一个query）
- 中英文变体都要提供

查询词构造规范（极其重要）：
- PubChem/DrugBank/DrugCentral：使用纯化合物英文名（如 "aspirin"、"ibuprofen"），不超过3个词，不要附加属性词（molecular weight/solubility等）
- Wikipedia：可用完整自然语言查询，如 "aspirin pharmacokinetics and dosage"
- PubMed/DailyMed：使用结构化关键词，如 "aspirin dosage adults clinical trial"
- DailyMed/FDA Drugs：使用药物英文通用名，如 "aspirin"
"""


MAX_PLAN_TOOLS = 8


def _validate_plan(plan: list, failed_tools: list) -> list:
    """校验并约束 plan：去重、剔除未注册工具、数量上限、优先保留非失效源"""
    seen: set = set()
    valid: list = []
    for p in plan:
        name = p.get("tool", "")
        if not name or name in seen or name not in TOOLS_BY_NAME:
            continue
        seen.add(name)
        valid.append(p)
    failed = set(failed_tools)
    non_failed = [p for p in valid if p.get("tool") not in failed]
    failed_only = [p for p in valid if p.get("tool") in failed]
    return (non_failed + failed_only)[:MAX_PLAN_TOOLS]


def run_plan(state: AgentState) -> dict:
    """执行 plan 节点"""
    sub_questions = state.get("sub_questions", [])
    user_query = state.get("user_query", "")
    thinking_steps = state.get("thinking_steps", [])

    # 如果没有子问题（understand失败），用原始query
    if not sub_questions:
        sub_questions = [user_query]

    llm = ChatOpenAI(
        model=settings.deepseek_model,
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        temperature=0.1,
    )

    # 构建 prompt
    query_text = "\n".join(f"- {q}" for q in sub_questions)
    user_prompt = f"用户原始问题: {user_query}\n\n子问题列表:\n{query_text}"

    try:
        response = llm.invoke([
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ])

        content = response.content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()

        result = json.loads(content)
        plan = result.get("plan", [])
        plan = _validate_plan(plan, state.get("failed_tools", []))

        # 构造 plan 文本记录
        tool_names = [p.get("tool", "?") for p in plan]
        queries_en = [p.get("query_en", "") for p in plan]

        thinking_message = (
            f"② 检索规划: 选择 {len(plan)} 个数据源（已去重/校验）\n"
            f"   工具: {', '.join(tool_names)}\n"
            f"   查询词: {', '.join(queries_en[:5])}"
        )
        thinking_steps.append(thinking_message)

        return {
            "thinking_steps": thinking_steps,
            # 将 plan 信息存储到 state 的临时字段（retrieve 节点消费）
            "_plan": plan,
        }

    except Exception as e:
        thinking_steps.append(f"② 检索规划: LLM解析异常,使用默认plan")
        # 降级: 对所有子问题都用核心工具
        default_plan = [
            {"tool": "pubchem_tool", "query_en": q, "query_zh": user_query, "reason": "默认选择"}
            for q in sub_questions[:3]
        ]
        default_plan = _validate_plan(default_plan, state.get("failed_tools", []))
        return {
            "thinking_steps": thinking_steps,
            "_plan": default_plan,
        }
