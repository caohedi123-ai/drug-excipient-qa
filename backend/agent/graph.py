"""LangGraph Agent 状态图 - 9节点编排 v4

新拓扑 (v4: 新增 expand_queries 查询词扩充 + 异步化 LLM 节点):
START → understand → plan → retrieve → evaluate → decide
                        ↑                             │
                        │   adjust ←── expand ←────────┘ (不足 & 轮次<max)
                        │                               │ (充分 or 轮次≥max)
                        └── 回调 ─────────────────── synthesize → END
"""

import asyncio
import logging
from datetime import datetime, timezone
from langgraph.graph import StateGraph, END
from agent.state import AgentState
from config import get_settings
from agent.runtime_cfg import get_param

settings = get_settings()

logger = logging.getLogger("agent.graph")

# === B4: checkpointer 降级状态（供健康检查 / 运维可观测） ===
CHECKPOINTER_STATE: dict = {
    "backend": "unknown",
    "degraded": False,
    "reason": "",
    "at": "",
}


def get_checkpointer_status() -> dict:
    """返回 checkpointer 运行状态（main.py /api/health 读取）。"""
    return dict(CHECKPOINTER_STATE)


# === 节点 wrapper ===

async def understand_node(state: AgentState) -> dict:
    from agent.nodes.understand import run_understand
    return await asyncio.to_thread(run_understand, state)


async def plan_node(state: AgentState) -> dict:
    from agent.nodes.plan import run_plan
    return await asyncio.to_thread(run_plan, state)


async def retrieve_node(state: AgentState) -> dict:
    from agent.nodes.retrieve import run_retrieve
    return await run_retrieve(state)


async def evaluate_node(state: AgentState) -> dict:
    """evaluate: LLM语义评估 + 规则质量分（异步化，避免阻塞事件循环）"""
    from agent.nodes.evaluate import run_evaluate
    return await asyncio.to_thread(run_evaluate, state)


async def decide_node(state: AgentState) -> dict:
    """decide: 白盒路由决策（异步化，统一节点类型）"""
    from agent.nodes.decide import run_decide
    return await asyncio.to_thread(run_decide, state)


async def adjust_node(state: AgentState) -> dict:
    """adjust: 基于缺失信息调整检索计划（异步化）"""
    from agent.nodes.adjust import run_adjust
    return await asyncio.to_thread(run_adjust, state)


async def expand_queries_node(state: AgentState) -> dict:
    """expand_queries: 查询词扩充 — 为不同维度/工具生成差异化查询词"""
    from agent.nodes.expand import run_expand
    return await run_expand(state)


async def synthesize_node(state: AgentState) -> dict:
    """synthesize: 多源整合 + 强制引用（异步化）"""
    from agent.nodes.synthesize import run_synthesize
    result = await asyncio.to_thread(run_synthesize, state)
    return await asyncio.to_thread(_maybe_compress_history, state, result)


def _maybe_compress_history(state: AgentState, result: dict) -> dict:
    """B1: 会话摘要压缩 — synthesize 完成后检查历史长度，超过阈值则滚动压缩。

    仅附加 session_summary/summary_rounds 字段，不修改 messages（避免与 reducer 冲突）。
    """
    from agent.nodes.history_utils import should_compress, summarize_oldest
    from langchain_openai import ChatOpenAI

    messages = state.get("messages", [])
    if not messages:
        return result
    compressed_this_round = state.get("compressed_this_round", False)
    if not should_compress(len(messages), get_param("history_compress_rounds", settings.history_compress_rounds), compressed_this_round):
        return result

    summary = state.get("session_summary", "") or ""
    rounds = state.get("summary_rounds", 0) or 0
    llm = ChatOpenAI(
        model=settings.deepseek_model,
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        temperature=0.1,
    )
    new_summary, new_rounds = summarize_oldest(
        messages, llm, existing_summary=summary, summary_rounds=rounds
    )
    if new_rounds > rounds:
        logger.info(
            "[memory] 会话摘要压缩: 轮次 %s -> %s（消息 %s 条）",
            rounds, new_rounds, len(messages),
        )
        return {
            **result,
            "session_summary": new_summary,
            "summary_rounds": new_rounds,
            "compressed_this_round": True,
        }
    return result


async def final_search_node(state: AgentState) -> dict:
    """final_search: 末轮缺失补全 — LLM 定制 AnySearch query 做最后补救检索（异步化）"""
    from agent.nodes.final_search import run_final_search
    return await asyncio.to_thread(run_final_search, state)


# === 条件路由 ===

def route_after_understand(state: AgentState) -> str:
    """understand 后的路由: 闲聊意图直接结束（已有 final_answer），否则进入检索规划"""
    if state.get("skip_retrieval"):
        return "end_chat"
    return "plan"


def route_after_decide(state: AgentState) -> str:
    """decide 后的路由: synthesize / adjust_plan / final_search"""
    next_action = state.get("next_action", "synthesize")
    return next_action if next_action in ("synthesize", "adjust_plan", "final_search") else "synthesize"


def route_after_adjust(state: AgentState) -> str:
    """adjust 后回到 plan 重新规划"""
    return "plan"


# === 图编译 ===

def build_graph() -> StateGraph:
    """构建 9 节点 Agent 状态图"""
    workflow = StateGraph(AgentState)

    # 注册所有节点
    workflow.add_node("understand", understand_node)
    workflow.add_node("plan", plan_node)
    workflow.add_node("retrieve", retrieve_node)
    workflow.add_node("evaluate", evaluate_node)
    workflow.add_node("decide", decide_node)
    workflow.add_node("expand_queries", expand_queries_node)
    workflow.add_node("adjust", adjust_node)
    workflow.add_node("synthesize", synthesize_node)
    workflow.add_node("final_search", final_search_node)

    # 主流程
    workflow.set_entry_point("understand")
    workflow.add_conditional_edges(
        "understand",
        route_after_understand,
        {
            "plan": "plan",
            "end_chat": END,
        }
    )
    workflow.add_edge("plan", "retrieve")
    workflow.add_edge("retrieve", "evaluate")
    workflow.add_edge("evaluate", "decide")

    # decide → synthesize 或 expand_queries（查询词扩充→调整）
    workflow.add_conditional_edges(
        "decide",
        route_after_decide,
        {
            "synthesize": "synthesize",
            "adjust_plan": "expand_queries",
            "final_search": "final_search",
        }
    )

    # expand_queries → adjust → plan（扩充查询词后调整检索计划）
    workflow.add_edge("expand_queries", "adjust")
    workflow.add_edge("adjust", "plan")

    # synthesize → END
    workflow.add_edge("synthesize", END)

    # final_search → synthesize（末轮补全后直接合成，无环路）
    workflow.add_edge("final_search", "synthesize")

    return workflow


# === 编译实例（单例） ===

_graph_instance = None
_agent_graph_lock: asyncio.Lock | None = None


async def get_agent_graph():
    """获取编译后的 Agent 图实例（延迟初始化，异步 PG checkpointer）"""
    global _graph_instance, _agent_graph_lock
    if _agent_graph_lock is None:
        _agent_graph_lock = asyncio.Lock()
    if _graph_instance is not None:
        return _graph_instance

    async with _agent_graph_lock:
        if _graph_instance is not None:
            return _graph_instance

        graph = build_graph()

        # 尝试接入 PostgreSQL 异步 checkpoint，失败则用 MemorySaver 保证对话记忆可用。
        # 注意：agent.astream()/aget_tuple 是异步路径，同步 PostgresSaver 的 aget_tuple
        # 会抛 NotImplementedError，必须用 AsyncPostgresSaver + AsyncConnectionPool。
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
            from psycopg_pool import AsyncConnectionPool
            # psycopg 的 AsyncConnectionPool 不认 SQLAlchemy 的 +asyncpg 前缀，需转换；
            # 若连接串已是 postgresql:// 则 replace 不匹配，原样使用。
            conninfo = settings.database_url.replace(
                "postgresql+asyncpg://", "postgresql://"
            )
            pool = AsyncConnectionPool(
                conninfo=conninfo,
                max_size=10,
                open=False,
            )
            await pool.open()
            checkpointer = AsyncPostgresSaver(pool)
            await checkpointer.setup()
            # recursion_limit 在调用时通过 config 传入（见 main.py / 测试），
            # 需覆盖最坏路径：understand+plan+retrieve+evaluate+decide
            # + (adjust+plan+retrieve+evaluate+decide)*(max_rounds-1) + synthesize ≈ 5+5*(n-1)+1
            _graph_instance = graph.compile(checkpointer=checkpointer)
            CHECKPOINTER_STATE.update(
                backend="postgres", degraded=False, reason="", at=_now_iso()
            )
        except Exception as e:
            from langgraph.checkpoint.memory import MemorySaver
            reason = str(e)
            logger.warning(
                "[WARN][MEMORY-DEGRADED] PG checkpointer 不可用，降级为 MemorySaver（会话重启后丢失）: %s",
                reason,
            )
            CHECKPOINTER_STATE.update(
                backend="memory", degraded=True, reason=reason, at=_now_iso()
            )
            _graph_instance = graph.compile(checkpointer=MemorySaver())

    return _graph_instance


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
