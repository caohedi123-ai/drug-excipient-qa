"""检索管线自测脚本（mock 搜索引擎，不依赖真实网络/API）

验证：
  1) 全部 30 个工具（含 anysearch_fallback）+ 注册成功
  2) 失败工具被正确标记为 success=False（修复原硬编码 bug）
  3) 轮次级 AnySearch 硬保底：专有源全失败时自动泛搜且成功
  4) 成功场景：专有源成功时 success=True 且保底不误触发
  5) prompts 工具描述包含兜底工具
"""

import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(__file__))

# ---------- 1) Mock 搜索引擎（避免真实联网） ----------
from agent.state import Citation, SearchResult


def fake_anysearch(query, domain="health", sub_domain=None, freshness="any",
                   content_types=None, max_results=10):
    c = Citation(id=1, source_name="AnySearch", source_url="https://example.com/r",
                 snippet=f"mock泛搜结果: {query}", retrieval_query=query,
                 retrieval_timestamp=Citation.make_timestamp())
    return SearchResult(source_name="AnySearch", content=f"AnySearch mock result for {query}",
                         citations=[c], success=True)


def fake_tavily(query, domains=None, max_results=5, search_depth="advanced"):
    c = Citation(id=1, source_name="Tavily", source_url="https://example.com/t",
                 snippet=f"mock: {query}", retrieval_query=query,
                 retrieval_timestamp=Citation.make_timestamp())
    return SearchResult(source_name="Tavily", content=f"Tavily mock for {query}",
                         citations=[c], success=True)


import tools.engines.anysearch_engine as ae
import tools.engines.tavily_engine as te

REAL_ANYSEARCH = ae.anysearch_vertical  # 保存真实引擎函数（供引擎健壮性用例使用）
ae.anysearch_vertical = fake_anysearch
te.tavily_domain_search = fake_tavily

# retrieve 节点用 `from ... import anysearch_vertical` 绑定引用，需直接 patch 其模块命名空间
import agent.nodes.retrieve as retrieve_mod
retrieve_mod.anysearch_vertical = fake_anysearch


# ---------- 2) 注册表断言 ----------
import tools
import json
from langchain_core.tools import tool

names = set(tools.TOOLS_BY_NAME.keys())
expected_names = {
    # 药物基础信息
    "pubchem_tool", "drugbank_tool", "drugcentral_tool", "chembl_tool", "coconut_tool",
    # 辅料与制剂
    "fda_iig_tool", "fda_unii_tool", "fda_ndc_tool", "dailymed_tool", "fda_orange_tool",
    # 注册审批
    "fda_drugs_tool", "ema_tool", "cde_tool", "pmda_tool",
    # 安全与相互作用
    "fda_faers_tool", "sider_tool", "ddinter_tool",
    # 靶点与基因
    "open_targets_tool", "bindingdb_tool", "pharmgkb_tool", "ttd_tool",
    # 分类标准与指南
    "rxnorm_tool", "who_atc_tool", "ich_tool",
    # 文献、专利与综合
    "pubmed_tool", "espacenet_tool", "cnipa_tool", "wikipedia_tool", "clinicaltrials_tool",
    # 兜底
    "anysearch_fallback_tool",
}
missing = expected_names - names
assert not missing, f"缺失工具: {missing}"
extra = names - expected_names
print(f"[OK] 注册工具数={len(names)} (期望 {len(expected_names)})")
assert "anysearch_fallback_tool" in names
print("[OK] anysearch_fallback_tool 已注册为兜底工具")
if extra:
    print(f"[提示] 额外注册工具: {extra}")

# 每个工具可调用性（兼容不同 LangChain 版本：func 或 ainvoke 存在即可）
for n, t in tools.TOOLS_BY_NAME.items():
    assert (getattr(t, "func", None) is not None) or hasattr(t, "ainvoke"), f"{n} 不可调用"
print("[OK] 全部 30 个工具函数均可被 retrieve 调用")


# ---------- 3) 工具描述包含兜底工具 ----------
from agent.prompts import get_tool_descriptions
desc_text = get_tool_descriptions()
assert "anysearch_fallback_tool" in desc_text, "prompts 工具描述未包含兜底工具"
print("[OK] prompts 工具描述包含 anysearch_fallback_tool（30个工具统一描述）")


# ---------- 4) 失败工具判定 + 轮次级兜底 ----------
@tool
def mock_fail_tool(query: str) -> str:
    """mock 失败工具"""
    return f"[MockFail] 未找到 '{query}' 的相关信息。"


tools.TOOLS_BY_NAME["mock_fail_tool"] = mock_fail_tool

from agent.nodes.retrieve import run_retrieve

base_state = {
    "user_query": "某冷门辅料 XYZ 的安全性",
    "round_count": 0,
    "citations": [],
    "retrieval_results": [],
    "search_history": [],
    "thinking_steps": [],
    "messages": [],
    "entities": [], "intent": "", "sub_questions": [], "keywords_en": [], "keywords_zh": [],
    "content_quality": 0.0, "missing_info": [], "is_sufficient": False,
    "next_action": "", "suggestions": [], "failure_reasons": [], "evaluation_details": {},
}

state = dict(base_state)
state["_plan"] = [{"tool": "mock_fail_tool", "query_en": "XYZ", "query_zh": "XYZ", "reason": "test"}]
out = asyncio.run(run_retrieve(state))
results = out["retrieval_results"]

fail = [r for r in results if r["source_name"] == "mock_fail_tool"]
assert fail and fail[0]["success"] is False, "失败工具应标记 success=False"
print("[OK] 失败工具 success=False 判定正确（修复硬编码 bug）")

fb = [r for r in results if r["source_name"] == "anysearch_fallback"]
assert fb and fb[0]["success"] is True, "轮次级兜底应触发且成功"
print("[OK] 轮次级 AnySearch 兜底触发且 success=True")
assert len(out["citations"]) > 0, "兜底应产生引用"
print(f"[OK] 兜底产生引用数={len(out['citations'])}")


# ---------- 5) 成功场景：专有源成功，保底不误触发 ----------
@tool
def mock_ok_tool(query: str) -> str:
    """mock 成功工具"""
    c = Citation(id=1, source_name="MockOK", source_url="https://x",
                 snippet="ok content", retrieval_query=query,
                 retrieval_timestamp=Citation.make_timestamp())
    return f"[MockOK] 找到内容\n\n__citations__: {json.dumps([c.to_dict()], ensure_ascii=False)}"


tools.TOOLS_BY_NAME["mock_ok_tool"] = mock_ok_tool
state2 = dict(base_state)
state2["_plan"] = [{"tool": "mock_ok_tool", "query_en": "A", "query_zh": "A", "reason": "t"}]
out2 = asyncio.run(run_retrieve(state2))
res2 = out2["retrieval_results"]
ok = [r for r in res2 if r["source_name"] == "mock_ok_tool"][0]
assert ok["success"] is True, "专有源成功应 success=True"
fb2 = [r for r in res2 if r["source_name"] == "anysearch_fallback"]
assert not fb2, "专有源成功时不应触发兜底"
print("[OK] 专有源成功场景 success=True 且保底未误触发")

# ---------- 6) AnySearch 引擎自身健壮性（修复 Citation 缺 id 真实 bug） ----------
import httpx as _httpx
_orig_post = _httpx.post
def _boom(*a, **k):
    raise _httpx.ConnectError("simulated network down")
_httpx.post = _boom
try:
    r = REAL_ANYSEARCH("test query", domain="health", max_results=5)
    assert r.success is False, "网络失败应 success=False"
    assert r.citations and r.citations[0].id == 1, "失败兜底 Citation 应有 id 且不崩"
finally:
    _httpx.post = _orig_post
print("[OK] AnySearch 引擎失败路径健壮（Citation 含 id，不再 TypeError）")

# ---------- 7) 输入清洗与转义（边界处理） ----------
from tools.sanitize import sanitize_query, escape_openfda_value
assert sanitize_query("a\u200bx\tc") == "a x c", "零宽字符应被去除"
assert sanitize_query("\x01\x02bad") == "bad", "控制字符应被去除"
assert sanitize_query("y" * 1000, max_len=10) == "y" * 10, "超长应被截断"
assert escape_openfda_value('a"b:c') == 'a\\"b\\:c', "openFDA 短语应转义"
print("[OK] sanitize_query/escape_openfda_value 边界清洗正确")

# ---------- 8) plan 校验：去重 / 剔除非注册 / 上限 / 优先非失效源 ----------
from agent.nodes.plan import _validate_plan
v1 = _validate_plan(
    [{"tool": "pubchem_tool"}, {"tool": "pubchem_tool"}, {"tool": "not_a_tool"}, {"tool": "wikipedia_tool"}], [])
assert len(v1) == 2, "_validate_plan 应去重并剔除未注册工具"
assert all(p["tool"] in tools.TOOLS_BY_NAME for p in v1)
big = [{"tool": n} for n in list(tools.TOOLS_BY_NAME.keys()) * 2]
v2 = _validate_plan(big, [])
assert len(v2) <= 8, "_validate_plan 工具数应 ≤ 8"
mixed = [{"tool": "pubchem_tool"}, {"tool": "wikipedia_tool"}, {"tool": "drugbank_tool"}]
v3 = _validate_plan(mixed, ["pubchem_tool"])
assert all(p["tool"] in tools.TOOLS_BY_NAME for p in v3)
assert v3[0]["tool"] != "pubchem_tool", "失效源应被后置"
print("[OK] _validate_plan 去重/校验/上限/失效源后置正确")

# ---------- 9) decide：无法回答出口 + 强制兜底标志 ----------
from agent.nodes.decide import run_decide
sd_max = dict(base_state)
sd_max["round_count"] = 99
sd_max["retrieval_results"] = [{"source_name": "x", "success": False, "content": "未找到"}]
sd_max["evaluation_details"] = {"content_quality": 0.1, "is_sufficient": False, "confidence": "low", "missing_info": ["a"]}
od_max = run_decide(sd_max)
assert od_max["cannot_answer"] is True, "达上限且无证据应 cannot_answer"
assert od_max["next_action"] == "synthesize"

sd_low = dict(base_state)
sd_low["round_count"] = 1
sd_low["retrieval_results"] = [{"source_name": "x", "success": False, "content": "未找到"}]
sd_low["evaluation_details"] = {"content_quality": 0.2, "is_sufficient": False, "confidence": "low", "missing_info": ["a"]}
od_low = run_decide(sd_low)
assert od_low["force_fallback"] is True, "低质量/无证据应强制兜底"
assert od_low["next_action"] == "adjust_plan"
print("[OK] decide 无法回答出口 + 强制兜底标志正确")

# ---------- 10) retrieve：跳过未知工具 + failed_tools 累积 + 统计 ----------
su = dict(base_state)
su["_plan"] = [{"tool": "mock_fail_tool", "query_en": "Z"}, {"tool": "ghost_tool", "query_en": "Z"}]
su["failed_tools"] = []
ou = asyncio.run(run_retrieve(su))
assert any("跳过未注册工具" in t for t in ou["thinking_steps"]), "应记录跳过未注册工具"
assert "mock_fail_tool" in ou["failed_tools"], "failed_tools 应累积"
assert any("成功 /" in t and "异常" in t for t in ou["thinking_steps"]), "应记录本轮成败统计"
print("[OK] retrieve 跳过未知工具 / failed_tools 累积 / 成败统计正确")

# ---------- 11) adjust._finalize_plan：强制引入兜底 + 去重 ----------
from agent.nodes.adjust import _finalize_plan
fp = _finalize_plan([{"tool": "pubchem_tool"}], True, [])
assert any(p["tool"] == "anysearch_fallback_tool" for p in fp), "force_fallback 应注入 anysearch_fallback_tool"
fn = _finalize_plan([{"tool": "anysearch_fallback_tool"}], False, [])
assert len(fn) == 1, "_finalize_plan 已含兜底则不去重后重复"
print("[OK] _finalize_plan 强制兜底注入 + 去重正确")

print("\n=== 检索管线自测全部通过 ===")
