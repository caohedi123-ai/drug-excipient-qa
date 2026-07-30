"""understand 节点 - 实体识别 + 意图分类 + 子问题拆分

使用 DeepSeek LLM 分析用户问题，提取关键实体和意图，
将复杂问题拆分为可独立检索的子问题。
"""

import json
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from agent.state import AgentState
from config import get_settings

settings = get_settings()

SYSTEM_PROMPT = """你是药物原辅料领域的专家分析助手。你的任务是将用户提出的药物相关问题进行结构化分析。

请严格按以下JSON格式输出，不要输出任何其他内容：

{
  "entities": ["实体1英文名", "实体2英文名", ...],
  "intent": "查询意图分类",
  "sub_questions": ["子问题1（英文）", "子问题2（英文）", ...],
  "keywords_en": ["关键词1", "关键词2", ...],
  "keywords_zh": ["关键词1", "关键词2", ...]
}

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


def run_understand(state: AgentState) -> dict:
    """执行 understand 节点"""
    user_query = state.get("user_query", "")
    thinking_steps = state.get("thinking_steps", [])
    messages = state.get("messages", [])

    llm = ChatOpenAI(
        model=settings.deepseek_model,
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        temperature=0.1,
    )

    # 构造上下文：注入最近 2 轮对话历史用于指代消解
    history_text = ""
    if len(messages) > 1:
        recent = messages[-4:]  # 最近 2 轮（每轮 user+assistant）= 4 条
        history_parts = []
        for m in recent:
            # 兼容多种消息格式：LangChain对象、dict、tuple
            role = "助手"
            content = ""
            if isinstance(m, dict):
                r = m.get("role", "")
                role = "用户" if r == "user" or r == "human" else "助手"
                content = m.get("content", str(m))
            elif hasattr(m, "type"):
                role = "用户" if m.type == "human" else "助手"
                content = getattr(m, "content", str(m))
            elif hasattr(m, "role"):
                role = "用户" if m.role == "user" or m.role == "human" else "助手"
                content = getattr(m, "content", str(m))
            else:
                cls = m.__class__.__name__.lower()
                role = "用户" if "human" in cls or "user" in cls else "助手"
                content = getattr(m, "content", "")
            # 截断长回答，指代消解只需要知道主题
            if role == "助手":
                content = content[:200]
            history_parts.append(f"{role}: {content}")
        history_text = "\n".join(history_parts)

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

        return {
            "entities": entities,
            "intent": intent,
            "sub_questions": sub_questions,
            "keywords_en": keywords_en,
            "keywords_zh": keywords_zh,
            "thinking_steps": thinking_steps,
        }

    except Exception as e:
        # 解析失败时使用原始 query 作为唯一子问题
        thinking_steps.append(f"① 实体识别: LLM解析异常,使用原始query")
        return {
            "sub_questions": [user_query],
            "thinking_steps": thinking_steps,
        }
