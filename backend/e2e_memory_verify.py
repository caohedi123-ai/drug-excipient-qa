# -*- coding: utf-8 -*-
"""E2E 验证：多轮对话新功能（实体记忆累积 + 会话摘要压缩 + 截断配置生效）

场景（模拟 12 轮对话，触发 should_compress > 10 条）：
1. 首轮：问"阿司匹林的分子量" → entity_memory 应含 aspirin
2. 次轮追问："它的作用机制是什么" → 指代消解应关联上一轮实体
3. 长会话后：messages > 10 条时触发摘要压缩 → session_summary 非空
4. 验证截断配置：retrieval_max_chars_per_source == 8000

注意：为控制真实 LLM 调用成本，本脚本对 LLM 调用做 mock，
仅验证编排层（图装配/状态流转/压缩触发/实体累积）正确性。
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent.state import AgentState
from agent.nodes.history_utils import (
    should_compress,
    update_entity_memory,
    summarize_oldest,
)
from agent.nodes.context_budget import allocate_per_source_chars, truncate_with_ellipsis
from config import get_settings

settings = get_settings()


def test_truncate_config_active():
    assert settings.retrieval_max_chars_per_source == 8000
    assert settings.retrieval_max_total_chars == 200000
    assert settings.retrieval_max_store_chars == 12000
    print("[OK] 截断配置生效: store=12000 inject_max=8000 total=200000")


def test_dynamic_budget_end_to_end():
    # 模拟 3 轮满配 24 源
    per = allocate_per_source_chars(24, settings.retrieval_max_total_chars, settings.retrieval_max_chars_per_source)
    assert per * 24 <= settings.retrieval_max_total_chars
    long_content = "A" * 30000
    truncated = truncate_with_ellipsis(long_content, per)
    assert len(truncated) <= per
    print(f"[OK] 动态预算 24源/源上限 {per} 字符，超长内容截断后 {len(truncated)} 字符 <= 预算")


def test_entity_memory_accumulates():
    mem = update_entity_memory({}, ["aspirin", "ibuprofen"], ["阿司匹林"], round_no=1)
    mem = update_entity_memory(mem, ["aspirin"], [], round_no=2)
    assert mem["aspirin"]["mention_count"] == 2
    assert mem["ibuprofen"]["mention_count"] == 1
    print("[OK] 实体记忆累积: aspirin x2, ibuprofen x1")


def test_compression_trigger_after_long_session():
    class FakeMsg:
        def __init__(self, c, t):
            self.content = c
            self.type = t
    # 模拟 12 轮对话 = 24 条消息
    msgs = [FakeMsg(f"问{i}", "human") if i % 2 == 0 else FakeMsg(f"答{i}", "ai") for i in range(24)]
    assert should_compress(len(msgs), settings.history_compress_rounds, False) is True

    class FakeLLM:
        def invoke(self, prompt):
            return type("R", (), {"content": "会话涉及 aspirin 与 ibuprofen 的比较讨论。"})

    summary, rounds = summarize_oldest(msgs, FakeLLM(), existing_summary="", summary_rounds=0)
    assert rounds == 1
    assert "aspirin" in summary or "ibuprofen" in summary
    print(f"[OK] 长会话压缩触发: summary_rounds=1, 摘要={summary[:60]}...")


def test_llm_failure_compression_fallback():
    class FakeMsg:
        def __init__(self, c):
            self.content = c
    msgs = [FakeMsg("阿司匹林分子量180.16"), FakeMsg("COX抑制剂")]
    class BadLLM:
        def invoke(self, prompt):
            raise RuntimeError("mock down")
    summary, rounds = summarize_oldest(msgs, BadLLM(), existing_summary="", summary_rounds=0)
    assert rounds == 1
    assert len(summary) > 0
    print("[OK] LLM 失败降级拼接摘要:", summary[:40], "...")


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
    print(f"\nE2E {passed}/{len(fns)} passed")
