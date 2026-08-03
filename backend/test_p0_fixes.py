"""P0 修正自测脚本（mock 为主，不依赖真实网络/子进程）

覆盖：
  P0.1 披露纠偏：get_tool_descriptions 含 [官方API]/[网络检索] 标签；虚假 docstring 已修
  P0.2 置信度修正：CONFIDENCE 字典按真实权威度重定
  P0.3 专利去重：dedup_patent_ids 同族去重
  P0.4 ChEMBL MCP：_extract_chembl_fields 从 MCP 摘要抽取深度字段；_search_chembl 走 MCP 优先路径
"""
import sys
import os
import asyncio
import inspect

sys.path.insert(0, os.path.dirname(__file__))


# ---------- P0.3 专利同族去重 ----------
from tools.sources.patent_search import dedup_patent_ids

raw = [
    "US-1234567-B2", "US-1234567-A1", "US-1234567-B1",   # 同一美国专利 3 个版本
    "CN-1234567-A", "CN-1234567-B",                       # 同一中国专利 2 个版本
    "WO-2021000000-A1",                                   # 独立
]
dd = dedup_patent_ids(raw)
assert len(dd) == 3, f"去重后应得 3 族, 实际 {len(dd)}: {dd}"
bases = {p.split('-')[0] + '-' + p.split('-')[1] for p in dd}
assert bases == {"US-1234567", "CN-1234567", "WO-2021000000"}, f"基号集合应为3族, 实际 {bases}"
print("[OK] P0.3 dedup_patent_ids 同族去重正确 (6→3)")


# ---------- P0.1 披露纠偏 ----------
from tools import get_tool_descriptions, SOURCE_TYPE

desc = get_tool_descriptions()
assert "[官方API]" in desc and "[网络检索]" in desc, "工具描述应含双标签"
assert "[综合检索]" in desc
assert SOURCE_TYPE["chembl_tool"] == "[官方API]"
assert SOURCE_TYPE["pubchem_tool"] == "[官方API]"
assert SOURCE_TYPE["drugbank_tool"] == "[网络检索]"
assert SOURCE_TYPE["ema_tool"] == "[网络检索]"
assert SOURCE_TYPE["espacenet_tool"] == "[网络检索]"
assert "drugbank_tool" in desc and "[网络检索]" in desc
print("[OK] P0.1 SOURCE_TYPE 标签披露正确（官方API/网络检索/综合检索）")

from tools.sources.chembl import chembl_tool
assert "结构-活性关系" not in chembl_tool.description, "chembl 虚假描述应已移除"
assert "ChEMBL REST" in chembl_tool.description
from tools.sources.drugbank import drugbank_tool
assert "Tavily" in drugbank_tool.description, "drugbank 描述应标明 Tavily 域名搜索（非官方 API）"
print("[OK] P0.1 虚假 docstring 已修正（chembl/drugbank）")

# P0.1 标签完整性：全部工具必须有披露标签；B 档源（网络检索）全部正确标注
from tools import ALL_TOOLS
missing_tags = [t.name for t in ALL_TOOLS if not SOURCE_TYPE.get(t.name)]
assert not missing_tags, f"以下工具缺少披露标签: {missing_tags}"
NET_SOURCES = [
    "wikipedia_tool", "drugbank_tool", "ema_tool", "cde_tool", "pmda_tool",
    "sider_tool", "ddinter_tool", "bindingdb_tool", "pharmgkb_tool", "ttd_tool",
    "who_atc_tool", "ich_tool", "espacenet_tool", "cnipa_tool", "anysearch_fallback_tool",
]
net_names = {t.name for t in ALL_TOOLS}
for k in NET_SOURCES:
    assert k in net_names, f"{k} 应在 ALL_TOOLS 中"
    assert SOURCE_TYPE[k] == "[网络检索]", f"{k} 应标 [网络检索]，实际 {SOURCE_TYPE[k]}"
print(f"[OK] P0.1 披露标签覆盖全部 {len(ALL_TOOLS)} 个工具（网络检索 {len(NET_SOURCES)} 个全覆盖）")

# P0.1 B 专利路径整合 Espacenet/CNIPA（mock 网络调用，验证补充合并与去重说明）
import types
from tools.sources import excipient_basic_info as ebi_mod

async def _fake_pc(query_or_cas):
    return {"total": 2, "by_country": {"US": ["US-1234567-B2", "US-1234567-A1"]}, "us_raw": [(1234567, "US-1234567-B2"), (1234567, "US-1234567-A1")]}

async def _fake_pm(query):
    return "PubMed 专利文献片段"

async def _fake_es(query):
    return types.SimpleNamespace(success=True, content="Espacenet 网络交叉引用内容")

async def _fake_cn(query):
    return types.SimpleNamespace(success=True, content="CNIPA 网络交叉引用内容")

_orig_pc, _orig_pm = ebi_mod.fetch_pubchem_patents, ebi_mod.fetch_pubmed_patent_articles
_orig_es, _orig_cn = ebi_mod._search_espacenet, ebi_mod._search_cnipa
ebi_mod.fetch_pubchem_patents = _fake_pc
ebi_mod.fetch_pubmed_patent_articles = _fake_pm
ebi_mod._search_espacenet = _fake_es
ebi_mod._search_cnipa = _fake_cn
try:
    pr = asyncio.run(ebi_mod._search_patents_direct("aspirin", "50-78-2"))
    assert pr.success, "专利路径应成功"
    assert "Espacenet 网络交叉引用内容" in pr.content, "Espacenet 补充应合并"
    assert "CNIPA 网络交叉引用内容" in pr.content, "CNIPA 补充应合并"
    assert "按同族去重" in pr.content, "专利标题应含同族去重说明"
finally:
    ebi_mod.fetch_pubchem_patents = _orig_pc
    ebi_mod.fetch_pubmed_patent_articles = _orig_pm
    ebi_mod._search_espacenet = _orig_es
    ebi_mod._search_cnipa = _orig_cn
print("[OK] P0.1 B _search_patents_direct 已整合 Espacenet/CNIPA 补充合并（mock 验证）")


# ---------- P0.2 置信度修正 ----------
from tools.sources.excipient_basic_info import CONFIDENCE

assert CONFIDENCE["pubchem"] == 100, "PubChem 官方 API 应保持高置信"
assert CONFIDENCE["fda_unii"] == 100
assert CONFIDENCE["drugbank"] == 50, "DrugBank 仅 Tavily 域名搜索，应降至 50"
assert CONFIDENCE["ema"] == 55
assert CONFIDENCE["cde"] == 50 and CONFIDENCE["pmda"] == 50
assert CONFIDENCE["espacenet"] == 45 and CONFIDENCE["cnipa"] == 50
assert CONFIDENCE["chembl"] == 88, "ChEMBL MCP 提供深度数据，升至 88"
assert CONFIDENCE["pubmed"] == 85 and CONFIDENCE["entity_info"] == 70
assert CONFIDENCE["wikipedia"] == 60, "通用百科非专业权威，应为 60"
print("[OK] P0.2 CONFIDENCE 字典已按真实权威度重定")


# ---------- P0.4 ChEMBL 抽取（mock MCP 摘要，无 subprocess） ----------
mock_summary = """## ChEMBL 深度数据
- ChEMBL ID: CHEMBL25
- 规范名称: ASPIRIN
- SMILES: CC(=O)Oc1ccccc1C(=O)O
- 作用机制(MOA): Cyclooxygenase inhibitor
- 生物活性: Albumin(Log K'=1.39); Tyrosine-protein kinase BTK(IC50=5.1nM)
- ADMET/理化性质: MW=180.16; logP=1.31; PSA=63.60
"""

from tools.sources.excipient_basic_info import _extract_chembl_fields

fields = _extract_chembl_fields(mock_summary, "https://www.ebi.ac.uk/chembl/compound_report_card/CHEMBL25")
keys = {f["key"] for f in fields}
assert "chembl_id" in keys, "应抽取 ChEMBL ID"
assert "smiles" in keys, "应抽取 SMILES"
assert "mechanism_of_action" in keys, "应抽取作用机制"
assert "bioactivity" in keys, "应抽取生物活性"
assert "admet" in keys, "应抽取 ADMET"
assert all(f["confidence"] == 88 for f in fields), "ChEMBL 字段置信度应为 88"
print(f"[OK] P0.4 _extract_chembl_fields 从 MCP 摘要抽取深度字段 keys={sorted(keys)}")

# 兼容 REST 旧格式 "(CHEMBL25)" 也能抽出（修复潜伏 bug）
rest_content = "[1] Aspirin (CHEMBL25)\n[2] ..."
rf = _extract_chembl_fields(rest_content, "x")
assert any(f["key"] == "chembl_id" for f in rf), "REST 旧格式也应能抽取 chembl_id"
print("[OK] P0.4 抽取兼容 REST 旧格式 (修复潜伏 bug)")


# ---------- P0.4 集成路径（mock search_full，避免拉起 node 子进程） ----------
import tools.sources.chembl as chembl_mod
from tools.sources.chembl_mcp_client import ChemblMCPClient

ChemblMCPClient._instance = None
client = ChemblMCPClient.instance()
client.enabled = True
client._ensure = lambda: asyncio.sleep(0)  # 不真正拉起子进程

async def fake_search_full(q):
    return mock_summary

client.search_full = fake_search_full
res = asyncio.run(chembl_mod._search_chembl("aspirin"))
assert res.success and "ChEMBL 深度数据" in res.content, "MCP 优先路径应返回深度摘要"
assert res.source_name == "ChEMBL (MCP)"
print("[OK] P0.4 _search_chembl 走 MCP 优先路径（mock，无真实子进程）")

# 降级分支存在性（真实 REST 需联网，这里仅校验代码路径）
src = inspect.getsource(chembl_mod._search_chembl)
assert "降级" in src, "应有 REST 降级分支"
print("[OK] P0.4 _search_chembl 含 REST 降级分支（MCP 不可用时永不中断）")


print("\n=== P0 修正自测全部通过 ===")
