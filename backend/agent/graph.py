"""LangGraph Agent 状态图 - 9节点编排 v4

新拓扑 (v4: 新增 expand_queries 查询词扩充 + 异步化 LLM 节点):
START → understand → plan → retrieve → evaluate → decide
                        ↑                             │
                        │   adjust ←── expand ←────────┘ (不足 & 轮次<max)
                        │                               │ (充分 or 轮次≥max)
                        └── 回调 ─────────────────── synthesize → END
"""

import asyncio
from langgraph.graph import StateGraph, END
from agent.state import AgentState
from config import get_settings

settings = get_settings()


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
    return await asyncio.to_thread(run_synthesize, state)


async def final_search_node(state: AgentState) -> dict:
    """final_search: 末轮缺失补全 — LLM 定制 AnySearch query 做最后补救检索（异步化）"""
    from agent.nodes.final_search import run_final_search
    return await asyncio.to_thread(run_final_search, state)


# === 条件路由 ===

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
    workflow.add_edge("understand", "plan")
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


def get_agent_graph():
    """获取编译后的 Agent 图实例（延迟初始化）"""
    global _graph_instance
    if _graph_instance is not None:
        return _graph_instance

    graph = build_graph()

    # 尝试接入 PostgreSQL checkpoint，失败则用 MemorySaver 保证对话记忆可用
    try:
        from langgraph.checkpoint.postgres import PostgresSaver
        checkpointer = PostgresSaver.from_conn_string(settings.database_url_sync)
        checkpointer.setup()
        # recursion_limit 在调用时通过 config 传入（见 main.py / 测试），
        # 需覆盖最坏路径：understand+plan+retrieve+evaluate+decide
        # + (adjust+plan+retrieve+evaluate+decide)*(max_rounds-1) + synthesize ≈ 5+5*(n-1)+1
        _graph_instance = graph.compile(checkpointer=checkpointer)
    except Exception as e:
        from langgraph.checkpoint.memory import MemorySaver
        print(f"[graph] PG checkpointer 不可用，降级为 MemorySaver: {e}")
        _graph_instance = graph.compile(checkpointer=MemorySaver())

    return _graph_instance
