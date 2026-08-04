"""understand 节点 - 实体识别 + 意图分类 + 子问题拆分

使用 DeepSeek LLM 分析用户问题，提取关键实体和意图，
将复杂问题拆分为可独立检索的子问题。
"""

import json
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from agent.state import AgentState
from config import get_settings
from agent.runtime_cfg import get_param
from agent.nodes.history_utils import (
    smart_truncate,
    update_entity_memory,
    entity_memory_prompt,
    apply_total_budget,
)

settings = get_settings()

SYSTEM_PROMPT = """你是药物原辅料领域的专家分析助手。你的任务是将用户提出的药物相关问题进行结构化分析。

请严格按以下JSON格式输出，不要输出任何其他内容：

{
  "entities": ["实体1英文名", "实体2英文名", ...],
  "entity_aliases": {"实体规范名": ["别名1", "别名2", ...], ...},
  "intent": "查询意图分类",
  "sub_questions": ["子问题1（英文）", "子问题2（英文）", ...],
  "keywords_en": ["关键词1", "关键词2", ...],
  "keywords_zh": ["关键词1", "关键词2", ...]
}

entity_aliases 说明（可选，用于会话级实体记忆）：
- 为每个核心药物/辅料实体提供别名清单（化学名、商品名、CAS号、中文名等）
- 如 {"aspirin": ["acetylsalicylic acid", "阿司匹林", "Bayer aspirin"]}
- 无法确定别名时可省略该字段或输出空对象 {}

意图分类可选值：
- "drug_info": 药物基本信息查询（分子量、结构、性质）
- "excipient_info": 辅料信息查询（辅料批准、用量、配伍）
- "registration": 注册审批信息查询（FDA/EMA/NMPA批准状态）
- "safety": 安全性/不良反应查询
- "mechanism": 作用机制/靶点查询
- "interaction": 药物相互作用查询
- "literature": 文献/专利搜索
- "comparison": 多药对比分析
- "general": 综合查询
- "chat": 闲聊/非学术问题（问候、寒暄、无关话题、与药物/原辅料无关的问题等）

**闲聊判定规则（chat 意图）**：
- 当用户的问题与药物、原辅料、医疗健康、化学等专业领域完全无关时（如"你好"、"今天天气怎么样"、"你会做什么"、"讲个笑话"、"推荐一部电影"等），归类为 "chat"
- 只要问题涉及任何药物/原辅料/健康相关实体，即使表述随意，也必须归类为对应专业意图，不得误判为 "chat"
- 当 intent 为 "chat" 时，entities/sub_questions/keywords 均输出空数组 []

子问题拆分原则：
- 用药名+主要动词+限定词构成
- 中英文各一个变体
- 每个子问题聚焦一个方面（不要混合机制+安全性+注册在同一子问题）
- 优先使用英文查询词（PubMed/FDA等源以英文为主）

**追问处理规则（极其重要）**：
- 如果当前问题是追问（包含指代词如"它"、"这个"、"那"、"其"、"该"等），必须从对话历史中提取被指代的真实实体
- entities 字段始终包含真正的药品英文名，不要填入指代词
- 如果对话历史中提到多个药物，优先选择最近一轮讨论的实体

示例：
用户问："阿司匹林的作用机制和常见副作用是什么？"
输出：
{
  "entities": ["aspirin"],
  "intent": "mechanism",
  "sub_questions": [
    "aspirin mechanism of action COX inhibition prostaglandin pathway",
    "aspirin common adverse effects side effects gastrointestinal bleeding",
    "aspirin pharmacology molecular target COX-1 COX-2 acetylation"
  ],
  "keywords_en": ["aspirin", "acetylsalicylic acid", "COX inhibitor", "NSAID", "mechanism of action"],
  "keywords_zh": ["阿司匹林", "乙酰水杨酸", "COX抑制剂", "作用机制", "不良反应"]
}
"""


def _format_msg(m) -> tuple:
    """兼容多种消息格式：LangChain对象、dict、tuple。返回 (role, content)"""
    role = "助手"
    content = ""
    if isinstance(m, dict):
        r = m.get("role", "")
        role = "用户" if r in ("user", "human") else "助手"
        content = m.get("content", str(m))
    elif hasattr(m, "type"):
        role = "用户" if m.type == "human" else "助手"
        content = getattr(m, "content", str(m))
    elif hasattr(m, "role"):
        role = "用户" if m.role in ("user", "human") else "助手"
        content = getattr(m, "content", str(m))
    else:
        cls = m.__class__.__name__.lower()
        role = "用户" if "human" in cls or "user" in cls else "助手"
        content = getattr(m, "content", "")
    return role, str(content)


def run_understand(state: AgentState) -> dict:
    """执行 understand 节点"""
    user_query = state.get("user_query", "")
    thinking_steps = state.get("thinking_steps", [])
    messages = state.get("messages", [])
    entity_memory = state.get("entity_memory", {}) or {}
    session_summary = state.get("session_summary", "") or ""
    summary_rounds = state.get("summary_rounds", 0) or 0

    llm = ChatOpenAI(
        model=settings.deepseek_model,
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        temperature=0.1,
    )

    # 构造上下文：注入最近 N 轮对话历史（可配置），跳过已压缩最旧消息，使用智能截断
    history_text = ""
    skip = 2 * summary_rounds  # 已压缩的早期消息条数（注入时跳过）
    available = messages[skip:] if skip < len(messages) else messages
    if len(available) > 1:
        inject_rounds = max(get_param("history_inject_rounds", settings.history_inject_rounds), 1)
        recent = available[-2 * inject_rounds:]  # 最近 N 轮（每轮 user+assistant）
        history_parts = []
        for m in recent:
            role, content = _format_msg(m)
            # 智能截断长回答（保留数值/实体、词边界不切断），避免截掉关键信息
            if role == "助手":
                content = smart_truncate(content, get_param("history_smart_truncate_chars", settings.history_smart_truncate_chars))
            history_parts.append(f"{role}: {content}")
        history_text = "\n".join(history_parts)

    # 会话级实体记忆提示（帮助跨轮指代消解）
    entity_ctx = entity_memory_prompt(entity_memory)
    if entity_ctx:
        history_text = (history_text + "\n" + entity_ctx).strip()

    # 历史总预算钳制（优先保留最近内容）
    history_text = apply_total_budget(history_text, get_param("history_max_total_chars", settings.history_max_total_chars))

    query_text = f"对话历史:\n{history_text}\n\n当前问题: {user_query}" if history_text else user_query

    try:
        response = llm.invoke([
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=query_text),
        ])

        # 解析 JSON 输出
        content = response.content.strip()
        # 清理可能的 markdown 代码块包装
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()

        result = json.loads(content)

        entities = result.get("entities", [])
        entity_aliases = result.get("entity_aliases", {}) or {}
        intent = result.get("intent", "general")
        sub_questions = result.get("sub_questions", [user_query])
        keywords_en = result.get("keywords_en", [])
        keywords_zh = result.get("keywords_zh", [])

        thinking_message = (
            f"① 实体识别: {', '.join(entities) if entities else '无特定实体'}\n"
            f"   意图分类: {intent}\n"
            f"   子问题拆分: {len(sub_questions)} 个"
        )
        thinking_steps.append(thinking_message)

        # 更新会话级实体记忆（合并别名、计数+1）；Aliases 优先取 LLM 输出
        round_no = len(messages) // 2
        # 将 LLM 别名并入 entities_en/zh 的归一化
        alias_map = {}
        for k, v in (entity_aliases or {}).items():
            alias_map[k] = v if isinstance(v, list) else [v]
        merged_memory = update_entity_memory(
            entity_memory,
            entities_en=entities,
            entities_zh=keywords_zh,
            round_no=round_no,
        )
        # 补充 LLM 明确给出的别名映射
        for canon, aliases in alias_map.items():
            ck = canon.lower().strip()
            if ck in merged_memory:
                merged_memory[ck]["aliases"] = list(
                    dict.fromkeys(merged_memory[ck].get("aliases", []) + [a for a in aliases if a])
                )

        # 闲聊意图：礼貌拒绝，短路检索流程
        if intent == "chat":
            refusal = (
                "您好，我是药物原辅料知识问答助手，专注于药物、药用辅料及相关专业领域的问题解答"
                "（如药物信息、辅料特性、注册审批、安全性、作用机制、相互作用、文献专利等）。\n\n"
                "您刚才的问题不在我的专业范围内，我暂时无法回答。如果涉及药物或原辅料相关的问题，"
                "欢迎随时向我提问！"
            )
            thinking_steps.append("   识别为闲聊意图，礼貌拒绝并跳过检索。")
            return {
                "entities": entities,
                "intent": intent,
                "sub_questions": [],
                "keywords_en": [],
                "keywords_zh": [],
                "thinking_steps": thinking_steps,
                "skip_retrieval": True,
                "final_answer": refusal,
                "citations": [],
                "entity_memory": merged_memory,
            }

        return {
            "entities": entities,
            "intent": intent,
            "sub_questions": sub_questions,
            "keywords_en": keywords_en,
            "keywords_zh": keywords_zh,
            "thinking_steps": thinking_steps,
            "entity_memory": merged_memory,
        }

    except Exception as e:
        # 解析失败时使用原始 query 作为唯一子问题
        thinking_steps.append(f"① 实体识别: LLM解析异常,使用原始query")
        return {
            "sub_questions": [user_query],
            "thinking_steps": thinking_steps,
        }
