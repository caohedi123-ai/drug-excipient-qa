"""真实图端到端冒烟测试（mock 节点，不依赖 LLM/网络）

目的：验证审查报告指出的高危回归 —— 多轮回溯路径步数远超旧 recursion_limit，
会抛 GraphRecursionError 导致跑不满 3 轮。本测试用与代码相同的编译公式跑满整轮，
并对照旧 limit=9 证明该回归确实存在且已修复。

场景：understand→plan→retrieve(失败)→evaluate(不足)→decide(调整)
      →adjust→plan→retrieve→evaluate→decide(调整)
      →adjust→plan→retrieve→evaluate→decide(达上限→合成, cannot_answer)
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from agent.state import AgentState
from config import get_settings
from agent import graph as graph_mod

settings = get_settings()
MAXR = settings.max_retrieval_rounds


# ---------- mock 节点（仅 decide 用真实逻辑，其余脚本化） ----------
def fake_understand(state):
    return {"thinking_steps": []}


def fake_plan(state):
    return {
        "_plan": [{"tool": "pubchem_tool", "query_en": "X"}],
        "thinking_steps": [],
    }


async def fake_retrieve(state):
    # 模拟每次检索都失败，并推进轮次
    rc = state.get("round_count", 0) + 1
    return {
        "retrieval_results": [
            {"source_name": "pubchem_tool", "success": False, "content": "[pubchem_tool] 未找到 X"}
        ],
        "citations": [],
        "round_count": rc,
        "search_history": [],
        "thinking_steps": [f"[mock] retrieve round {rc} -> 全部失败"],
        "failed_tools": ["pubchem_tool"],
    }


def fake_evaluate(state):
    ed = {"content_quality": 0.1, "is_sufficient": False, "confidence": "low", "missing_info": ["X"]}
    return {**ed, "evaluation_details": ed, "thinking_steps": []}


def fake_adjust(state):
    return {
        "_plan": [{"tool": "pubchem_tool", "query_en": "X"}],
        "force_fallback": False,
        "thinking_steps": [],
    }


def fake_synthesize(state):
    return {
        "final_answer": "（mock）综合回答",
        "confidence": "low",
        "thinking_steps": [],
    }


def _install():
    graph_mod.understand_node = fake_understand
    graph_mod.plan_node = fake_plan
    graph_mod.retrieve_node = fake_retrieve          # async，LangGraph 自行 await
    graph_mod.evaluate_node = fake_evaluate
    graph_mod.adjust_node = fake_adjust
    graph_mod.synthesize_node = fake_synthesize
    # decide 用真实 run_decide，验证真实路由逻辑
    import agent.nodes.decide as dec
    graph_mod.decide_node = dec.run_decide


def build_with_limit(limit):
    _install()
    wf = graph_mod.build_graph()
    return wf.compile(checkpointer=MemorySaver())


base_state = {
    "user_query": "某冷门辅料安全性",
    "round_count": 0,
    "citations": [],
    "retrieval_results": [],
    "search_history": [],
    "thinking_steps": [],
    "messages": [],
    "entities": [], "intent": "", "sub_questions": [], "keywords_en": [], "keywords_zh": [],
    "content_quality": 0.0, "missing_info": [], "is_sufficient": False,
    "next_action": "", "suggestions": [], "failure_reasons": [], "evaluation_details": {},
    "failed_tools": [], "force_fallback": False, "cannot_answer": False, "low_confidence": False,
}


async def run_once(limit):
    g = build_with_limit(limit)
    cfg = {"configurable": {"thread_id": f"t_limit_{limit}"}, "recursion_limit": limit}
    result = await g.ainvoke(base_state, config=cfg)
    return result


async def main():
    # 1) 旧 limit=9：应当抛 GraphRecursionError（证明回归存在）
    raised = False
    try:
        await run_once(9)
    except Exception as e:
        if "recursion" in str(e).lower() or "RecursionError" in type(e).__name__:
            raised = True
        else:
            raise
    assert raised, "旧 limit=9 应当触发 GraphRecursionError（证明回归真实存在）"
    print("[OK] 旧 recursion_limit=9 确实会 GraphRecursionError（回归存在，已被识别）")

    # 2) 修复后 limit=max_rounds*6+10：应当跑满 3 轮并到达 synthesize
    result = await run_once(MAXR * 6 + 10)
    assert result.get("next_action") == "synthesize", "应终止于 synthesize"
    assert "final_answer" in result, "应产生 final_answer"
    assert result.get("round_count", 0) >= MAXR, f"应跑满 {MAXR} 轮, 实际 {result.get('round_count')}"
    assert result.get("cannot_answer") is True, "达上限无证据应 cannot_answer=True"
    print(f"[OK] 修复后跑满 {result.get('round_count')} 轮到达 synthesize，"
          f"cannot_answer={result.get('cannot_answer')}, 无 GraphRecursionError")

    # 3) 决策级兜底链路：真实 decide 路由 —— 首轮失败+低质量 应 adjust_plan 且 force_fallback=True
    import agent.nodes.decide as dec
    st_dec = dict(base_state)
    st_dec["round_count"] = 1
    st_dec["retrieval_results"] = [{"source_name": "pubchem_tool", "success": False, "content": "未找到"}]
    st_dec["evaluation_details"] = {"content_quality": 0.1, "is_sufficient": False, "confidence": "low", "missing_info": ["X"]}
    od = dec.run_decide(st_dec)
    assert od["next_action"] == "adjust_plan", "首轮不足应 adjust_plan"
    assert od["force_fallback"] is True, "低质量+无证据应强制兜底"
    print(f"[OK] 决策级路由正常：首轮不足→adjust_plan，force_fallback={od['force_fallback']}")

    print("\n=== 真实图端到端冒烟全部通过 ===")


if __name__ == "__main__":
    asyncio.run(main())
