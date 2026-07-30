"""Agent 核心数据模型：AgentState、Citation、SearchResult"""

from dataclasses import dataclass, field
from typing import TypedDict, Annotated
from datetime import datetime, timezone
import operator


@dataclass
class Citation:
    """引用元数据 - 每条事实性陈述的可追溯来源"""
    id: int                             # 引用序号 [1], [2], ...
    source_name: str                    # 数据源名，如 "PubChem" / "PubMed"
    source_url: str                     # 可点击直达的 URL
    snippet: str                        # 被引用段落的原文摘录（≤200字）
    retrieval_query: str                # 检索时使用的 query
    retrieval_timestamp: str            # ISO 8601 检索时间戳

    @staticmethod
    def make_timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source_name": self.source_name,
            "source_url": self.source_url,
            "snippet": self.snippet[:200],
            "retrieval_query": self.retrieval_query,
            "retrieval_timestamp": self.retrieval_timestamp,
        }


@dataclass
class SearchResult:
    """单个检索结果的统一容器"""
    source_name: str                            # 数据源名
    content: str                                # 检索内容（API + 搜索摘要 ≤ 3000字符）
    citations: list[Citation] = field(default_factory=list)
    raw_urls: list[str] = field(default_factory=list)
    success: bool = True

    @property
    def has_content(self) -> bool:
        return bool(self.content.strip())

    @classmethod
    def empty(cls, source_name: str, reason: str = "") -> "SearchResult":
        return cls(
            source_name=source_name,
            content=f"[无结果] {reason}" if reason else "[无结果]",
            success=False,
        )


class AgentState(TypedDict):
    """LangGraph Agent 状态定义"""
    # --- 对话核心 ---
    messages: Annotated[list, operator.add]    # 对话历史（LangGraph add_messages reducer）
    user_query: str                             # 原始用户问题
    final_answer: str                           # synthesize 生成的最终回答
    thinking_steps: list[str]                   # 思考过程记录（前端可折叠展示）

    # --- understand 输出 ---
    entities: list[str]                         # 识别到的实体名（中英文均有）
    intent: str                                 # 查询意图分类
    sub_questions: list[str]                    # 拆分后的子问题
    keywords_en: list[str]                      # 英文关键词
    keywords_zh: list[str]                      # 中文关键词

    # --- plan 输出 ---
    _plan: list[dict]                           # 检索计划（跨节点暂存）

    # --- retrieve 输出 ---
    retrieval_results: list[dict]               # 累积检索结果（跨轮次追加）
    search_history: list[dict]                  # 检索历史（query/tool/results_urls）
    citations: list[dict]                       # 累积引用列表（Citation 序列化）
    round_count: int                            # 当前检索轮次（≤ max_rounds）
    failed_tools: list[str]                     # 跨轮次累积的失败工具名（供 plan/adjust 排除）

    # --- validate 输出 ---
    content_quality: float                      # 内容质量评分 0-1
    missing_info: list[str]                     # 缺失信息项

    # --- decide → evaluate ---
    is_sufficient: bool                         # 信息是否充分
    next_action: str                            # 下一步动作（synthesize / adjust_plan）
    suggestions: list[str]                      # adjust_plan 调整建议
    failure_reasons: list[str]                  # 失败原因记录
    evaluation_details: dict                    # evaluate 评估详情（confidence/suggestion/missing）
    force_fallback: bool                        # 决策层强制引入 anysearch_fallback 兜底标志
    cannot_answer: bool                         # 已达上限仍证据不足 → 显式"无法充分回答"
    low_confidence: bool                        # 低置信度合成（前端可提示核实）
    final_search_done: bool                     # 末轮缺失补全搜索(final_search)是否已执行（防重入）

    # --- expand_queries 输出 ---
    expanded_queries: list[dict]                # 查询词扩充结果 [{dimension, queries_en, queries_zh, best_tools}]
    expanded_names: dict                         # 实体名穷举 {chemical_name, brand_names, code_names, chinese_names}
