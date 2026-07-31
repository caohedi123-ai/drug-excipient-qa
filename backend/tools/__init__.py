"""工具注册表 - 全部数据源工具统一注册

实现 DESIGN.md 的 24+ 权威源方案（实际 30 个工具，含 AnySearch 泛搜兜底工具）。
三层兜底策略：
  1. 工具级：每个源 API 优先，失败自动降级 AnySearch/Tavily
  2. 轮次级：retrieve 节点内，本轮零有效结果时自动 AnySearch 泛搜保底
  3. 决策级：decide 判不足时由 plan 重选（含 anysearch_fallback_tool）
"""

# 药物基础信息组
from tools.sources.pubchem import pubchem_tool
from tools.sources.drugbank import drugbank_tool
from tools.sources.drugcentral import drugcentral_tool
from tools.sources.chembl import chembl_tool
from tools.sources.coconut import coconut_tool

# 辅料与制剂组
from tools.sources.fda_iig import fda_iig_tool
from tools.sources.fda_unii import fda_unii_tool
from tools.sources.fda_ndc import fda_ndc_tool
from tools.sources.dailymed import dailymed_tool
from tools.sources.fda_orange import fda_orange_tool

# 注册审批组
from tools.sources.fda_drugs import fda_drugs_tool
from tools.sources.ema import ema_tool
from tools.sources.cde import cde_tool
from tools.sources.pmda import pmda_tool

# 安全与相互作用组
from tools.sources.fda_faers import fda_faers_tool
from tools.sources.sider import sider_tool
from tools.sources.ddinter import ddinter_tool

# 靶点与基因组
from tools.sources.open_targets import open_targets_tool
from tools.sources.bindingdb import bindingdb_tool
from tools.sources.pharmgkb import pharmgkb_tool
from tools.sources.ttd import ttd_tool

# 分类标准与指南组
from tools.sources.rxnorm import rxnorm_tool
from tools.sources.who_atc import who_atc_tool
from tools.sources.ich import ich_tool

# 文献、专利与综合组
from tools.sources.pubmed import pubmed_tool
from tools.sources.espacenet import espacenet_tool
from tools.sources.cnipa import cnipa_tool
from tools.sources.wikipedia import wikipedia_tool
from tools.sources.clinicaltrials import clinicaltrials_tool

# 兜底工具（全链路最后兜底泛搜）
from tools.sources.anysearch_fallback import anysearch_fallback_tool


# 全部工具列表（30 个）
ALL_TOOLS = [
    # 药物基础信息
    pubchem_tool, drugbank_tool, drugcentral_tool, chembl_tool, coconut_tool,
    # 辅料与制剂
    fda_iig_tool, fda_unii_tool, fda_ndc_tool, dailymed_tool, fda_orange_tool,
    # 注册审批
    fda_drugs_tool, ema_tool, cde_tool, pmda_tool,
    # 安全与相互作用
    fda_faers_tool, sider_tool, ddinter_tool,
    # 靶点与基因
    open_targets_tool, bindingdb_tool, pharmgkb_tool, ttd_tool,
    # 分类标准与指南
    rxnorm_tool, who_atc_tool, ich_tool,
    # 文献、专利与综合
    pubmed_tool, espacenet_tool, cnipa_tool, wikipedia_tool, clinicaltrials_tool,
    # 兜底
    anysearch_fallback_tool,
]

# 原辅料基本信息速查（迁移 jiansuo3 检索内核，路线B）— 条件导入，导入失败不影响其他工具
try:
    from tools.sources.excipient_basic_info import excipient_basic_info_tool
except Exception:
    excipient_basic_info_tool = None
if excipient_basic_info_tool is not None:
    ALL_TOOLS.append(excipient_basic_info_tool)

# 兼容旧名（保留以免其它模块引用报错）
PHASE1_TOOLS = ALL_TOOLS

# 工具名称 → 工具对象的查找表
TOOLS_BY_NAME = {t.name: t for t in ALL_TOOLS}


def get_tool_node():
    """获取注册了所有工具的 ToolNode（延迟导入避免重型依赖初始化）"""
    from langgraph.prebuilt import ToolNode
    return ToolNode(ALL_TOOLS)


def get_tool_descriptions() -> str:
    """生成工具列表描述文本（供 LLM 的 system prompt 使用），动态覆盖全部工具"""
    lines = [
        "## 可用数据源工具",
        "（优先使用有 API 覆盖的专有源；若所选源均返回空或不足，务必加入 "
        "**anysearch_fallback_tool** 做全网泛搜兜底，确保最终有答案而非'未找到'）\n",
    ]
    for t in ALL_TOOLS:
        desc = (t.description or "").strip()
        lines.append(f"- **{t.name}**: {desc}")
    return "\n".join(lines)
