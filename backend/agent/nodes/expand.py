"""expand_queries 节点 — 查询词扩充 + 思考模板

在 adjust 之前运行，用结构化思考让 LLM 为不同维度/工具生成差异化查询词，
解决"所有工具用同一个词反复搜"的核心问题。
"""

import json
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from config import get_settings
from agent.state import AgentState

settings = get_settings()

EXPAND_SYSTEM_PROMPT = """你是药物检索查询词专家。你的任务是为每个信息维度生成最有效的检索查询词。

## 思考模板（请在输出前完成以下推理）：

### 第一步：实体名穷举
- 该药物的化学名、IUPAC 名、商品名、研发代号、中文名、常见缩写
- 如果是辅料：功能分类名（如"非离子表面活性剂"）、INCI 名

### 第二步：信息维度分解
根据用户问题，列出需要覆盖的全部信息维度。常见维度：
- 化学性质（分子量、CAS号、结构式、溶解性）
- 作用机制（靶点、通路、结合方式）
- 适应证与用法用量（FDA批准适应症、标准剂量）
- 安全性（不良反应、禁忌、相互作用）
- 制剂应用（辅料功能、配比、配伍）
- 法规状态（FDA/EMA/NMPA批准、橙皮书、IIG）
- 临床试验（关键试验、主要终点）
- 文献证据（PubMed最新研究）

### 第三步：工具-查询词映射
为每个维度选择最佳数据源，并生成该源最优的查询词：
- PubChem/DrugBank → 纯化合物英文名或CID
- DailyMed/FDA Drugs → "药物名 prescribing information" 或 "药物名 AND indication"
- PubMed → "药物名 mechanism of action" 或 "药物名 clinical trial"
- ClinicalTrials → "药物名" 或 "brand name"
- Wikipedia → 完整自然语言描述
- SIDER/FAERS → "药物名 adverse events" 或 "药物名 side effects"
- FDA IIG/UNII → 辅料英文名或UNII码
- **中文源（CDE/CNIPA）→ 使用中文名查询**

## 输出格式（严格 JSON）：

{
  "dimensions": [
    {
      "dimension": "维度名（如 作用机制）",
      "queries_en": ["英文查询词1", "英文查询词2"],
      "queries_zh": ["中文查询词1"],
      "best_tools": ["工具名1", "工具名2"]
    }
  ],
  "all_names": {
    "chemical_name": "",
    "brand_names": [],
    "code_names": [],
    "chinese_names": []
  }
}

## 核心原则：
- **绝不把同一个词分配给所有工具**——每个维度/工具都要有专属的差异化查询词
- 药物别名、商品名是突破同义词死循环的关键
- 中文查询词用于中文数据源（CDE、CNIPA、中文 Wikipedia）
- 如果用户问了多个方面 → 每个方面都要有对应的维度条目
"""


async def run_expand(state: AgentState) -> dict:
    """查询词扩充节点：生成多维度差异化查询词"""
    user_query = state.get("user_query", "")
    entities = state.get("entities", [])
    missing_info = state.get("missing_info", [])
    suggestions = state.get("suggestions", [])
    thinking_steps = state.get("thinking_steps", [])
    round_count = state.get("round_count", 1)

    entity_text = ", ".join(entities) if entities else user_query[:60]
    missing_text = ", ".join(missing_info) if missing_info else "（无明确缺失信息，尽可能广覆盖）"
    suggestion_text = "; ".join(suggestions) if suggestions else "（无建议，自行分解维度）"

    human_text = (
        f"## 用户原始问题\n{user_query}\n\n"
        f"## 已识别实体\n{entity_text}\n\n"
        f"## 当前缺失的信息维度\n{missing_text}\n\n"
        f"## 检索建议\n{suggestion_text}\n\n"
        f"## 当前检索轮次\n第 {round_count} 轮\n\n"
        f"请按思考模板逐步分析，然后输出差异化的查询词映射。"
    )

    llm = ChatOpenAI(
        model=settings.deepseek_model,
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        temperature=0.3,
    )

    try:
        response = await llm.ainvoke([
            SystemMessage(content=EXPAND_SYSTEM_PROMPT),
            HumanMessage(content=human_text),
        ])
        content = response.content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()

        result = json.loads(content)
        dimensions = result.get("dimensions", [])
        all_names = result.get("all_names", {})

        # 扁平化为 adjust 可用的格式
        expanded_queries = []
        for d in dimensions:
            dim_name = d.get("dimension", "")
            queries_en = d.get("queries_en", [])
            queries_zh = d.get("queries_zh", [])
            best_tools = d.get("best_tools", [])
            expanded_queries.append({
                "dimension": dim_name,
                "queries_en": queries_en,
                "queries_zh": queries_zh,
                "best_tools": best_tools,
            })

        all_query_texts = []
        for eq in expanded_queries:
            if eq["queries_en"]:
                all_query_texts.extend(eq["queries_en"][:2])
            if eq["queries_zh"]:
                all_query_texts.extend(eq["queries_zh"][:1])

        thinking_steps.append(
            f"⑧ 查询词扩充: 分解为 {len(expanded_queries)} 个维度，"
            f"生成 {len(all_query_texts)} 个差异化查询词"
        )

        return {
            "expanded_queries": expanded_queries,
            "expanded_names": all_names,
            "thinking_steps": thinking_steps,
        }

    except Exception as e:
        # 降级：用实体名和缺失信息构造简单查询词
        fallback_queries = [
            {
                "dimension": "基础信息",
                "queries_en": entities[:2] if entities else [user_query[:60]],
                "queries_zh": [],
                "best_tools": ["pubchem_tool", "drugbank_tool", "wikipedia_tool"],
            }
        ]
        thinking_steps.append(
            f"⑧ 查询词扩充: LLM异常({e}) → 降级为实体名查询"
        )
        return {
            "expanded_queries": fallback_queries,
            "expanded_names": {},
            "thinking_steps": thinking_steps,
        }
