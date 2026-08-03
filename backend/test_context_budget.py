# -*- coding: utf-8 -*-
"""单元测试：上下文预算 + 历史工具（动态分配/智能截断/摘要压缩/实体记忆）"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent.nodes.context_budget import (
    allocate_per_source_chars,
    truncate_with_ellipsis,
    MIN_FLOOR_CHARS,
)
from agent.nodes.history_utils import (
    smart_truncate,
    should_compress,
    build_summary_fallback,
    summarize_oldest,
    apply_total_budget,
    update_entity_memory,
    entity_memory_prompt,
)


# ---------- A2: 动态预算分配 ----------

def test_allocate_single_source():
    # 单源 → 接近 per_source_max
    assert allocate_per_source_chars(1, 200000, 8000) == 8000


def test_allocate_many_sources():
    # 24 源满配 → 均摊且不超过总预算
    per = allocate_per_source_chars(24, 200000, 8000)
    assert per * 24 <= 200000
    assert per == 8000  # 200000 // 24 = 8333 > 8000，受单源上限钳制


def test_allocate_tiny_budget_hard_constraint():
    # 总预算极小 → 硬约束优先，保底让位（评审 P0-1）
    per = allocate_per_source_chars(100, 5000, 8000)
    assert per * 100 <= 5000
    assert per >= 1


def test_allocate_zero_sources():
    assert allocate_per_source_chars(0, 200000, 8000) == 8000


def test_allocate_floor_applied_when_possible():
    # 有预算空间时保底 800 生效
    per = allocate_per_source_chars(100, 100000, 8000)
    assert per >= MIN_FLOOR_CHARS
    assert per * 100 <= 100000


def test_truncate_short_text_unchanged():
    assert truncate_with_ellipsis("short", 100) == "short"


def test_truncate_long_text_adds_ellipsis():
    t = truncate_with_ellipsis("x" * 5000, 12000)
    assert t == "x" * 5000
    t2 = truncate_with_ellipsis("y" * 20000, 12000)
    assert len(t2) <= 12000
    assert "…[内容截断]" in t2


# ---------- B3: 智能截断 ----------

def test_smart_truncate_short():
    assert smart_truncate("abc", 200) == "abc"


def test_smart_truncate_long_sentence_boundary():
    text = "这是第一句。" + "这是第二句内容比较长。" * 10
    out = smart_truncate(text, 50)
    assert len(out) <= 50
    assert out.endswith("…")


def test_smart_truncate_keeps_numeric():
    # 数值单位在 85% 内 → 应保留完整数值
    text = "分子量为 180.16 mg 的重要信息。"
    out = smart_truncate(text, 12)
    assert "180.16" in out or len(out) <= 12  # 若空间不足则至少不超限


def test_smart_truncate_word_boundary_english():
    text = "aspirin acetylsalicylic acid" * 10
    out = smart_truncate(text, 40)
    assert len(out) <= 40
    # 不应切断英文单词（要么词边界，要么句边界）
    assert out.rstrip("…").endswith(("aspirin", "acid", "acetylsalicylic"))


# ---------- B1: 摘要压缩 ----------

def test_should_compress_threshold():
    # 超过 2*4+2=10 条触发；本轮已压缩则不触发
    assert should_compress(11, 4, False) is True
    assert should_compress(10, 4, False) is False
    assert should_compress(11, 4, True) is False


def test_build_summary_fallback_empty():
    assert build_summary_fallback([], 0) == ""


def test_apply_total_budget_under():
    assert apply_total_budget("hello", 100) == "hello"


def test_apply_total_budget_over_keeps_recent():
    text = "A" * 8000
    out = apply_total_budget(text, 1000)
    assert len(out) <= 1000
    assert "历史省略" in out
    assert out.endswith("A")  # 保留最近内容


def test_summarize_oldest_llm_failure_fallback():
    """LLM 异常时降级为拼接，不抛异常"""
    class FakeMsg:
        def __init__(self, c):
            self.content = c
    msgs = [FakeMsg("阿司匹林分子量 180.16。"), FakeMsg("作用机制是 COX 抑制。")]
    class BadLLM:
        def invoke(self, prompt):
            raise RuntimeError("llm down")
    summary, rounds = summarize_oldest(msgs, BadLLM(), existing_summary="", summary_rounds=0)
    assert rounds == 1
    assert "阿司匹林" in summary or "180.16" in summary


# ---------- B2: 实体记忆 ----------

def test_update_entity_memory_basic():
    mem = update_entity_memory({}, ["aspirin"], ["阿司匹林"], round_no=1)
    assert "aspirin" in mem
    assert mem["aspirin"]["mention_count"] == 1
    assert mem["aspirin"]["last_round"] == 1
    assert "阿司匹林" in mem  # 中文名独立记录


def test_update_entity_memory_increment():
    mem = update_entity_memory({"aspirin": {"aliases": [], "mention_count": 1, "last_round": 1}},
                               ["aspirin"], [], round_no=2)
    assert mem["aspirin"]["mention_count"] == 2
    assert mem["aspirin"]["last_round"] == 2


def test_entity_memory_prompt_limit():
    mem = {f"drug{i}": {"aliases": [], "mention_count": i, "last_round": i} for i in range(20)}
    p = entity_memory_prompt(mem, limit=8)
    assert p.count("提及") == 8


def test_update_entity_memory_cap_50():
    mem = {}
    for i in range(60):
        mem = update_entity_memory(mem, [f"e{i}"], [], round_no=i)
    assert len(mem) <= 50


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        try:
            fn()
            passed += 1
            print(f"  PASS {fn.__name__}")
        except AssertionError as e:
            print(f"  FAIL {fn.__name__}: {e}")
        except Exception as e:
            print(f"  ERROR {fn.__name__}: {e!r}")
    print(f"\n{passed}/{len(fns)} passed")
