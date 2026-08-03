# -*- coding: utf-8 -*-
"""集成验证：图装配 + checkpointer 状态 + 新状态字段连通性"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import asyncio


def test_graph_compiles_and_checkpointer_status():
    from agent.graph import get_agent_graph, get_checkpointer_status
    g = asyncio.run(get_agent_graph())
    assert g is not None
    cp = get_checkpointer_status()
    print(f"checkpointer_status={cp}")
    assert cp["backend"] in ("postgres", "memory")
    assert "degraded" in cp


def test_state_has_new_fields():
    from agent.state import AgentState
    defaults = AgentState.__required_keys__ if hasattr(AgentState, "__required_keys__") else {}
    all_keys = set(AgentState.__annotations__.keys())
    for f in ("session_summary", "summary_rounds", "entity_memory", "compressed_this_round"):
        assert f in all_keys, f"state 缺少字段 {f}"
    print("state 新字段 OK:", [f for f in ("session_summary", "summary_rounds", "entity_memory", "compressed_this_round") if f in all_keys])


def test_graph_nodes_registered():
    from agent.graph import get_agent_graph
    g = asyncio.run(get_agent_graph())
    nodes = set(g.get_graph().nodes.keys())
    expected = {"understand", "plan", "retrieve", "evaluate", "decide", "synthesize"}
    assert expected.issubset(nodes), f"缺少节点: {expected - nodes}"
    print("节点注册 OK:", sorted(expected))


def test_main_imports():
    import main  # noqa: F401
    print("main.py import OK")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        try:
            fn()
            passed += 1
            print(f"  PASS {fn.__name__}")
        except Exception as e:
            import traceback
            print(f"  FAIL {fn.__name__}: {e}")
            traceback.print_exc()
    print(f"\n{passed}/{len(fns)} passed")
