"""原辅料基本信息速查工具（迁移自 jiansuo3 检索内核，路线 B）。

设计目标（策略不能丢）：
  1. 关键词扩展：LLM 把中文名/商品名/CAS 解析为 englishName + casNumber + productType
  2. 实体解析 + CAS 验证：用 PubChem REST 二次验证 LLM 给的 CAS，不信任 LLM 的 CAS
  3. 多源并行：并行调用 16 个数据源工具的底层 _search_xxx 函数
     （espacenet/cnipa 已并入专利专项路径，避免重复输出）
  4. 三层降级：各源自身降级 + 末轮 AnySearch 兜底（复用现有 anysearch_engine）
  5. 置信度分级：按数据源类型映射置信度（API=100 / extract=80-90 / 搜索=60-70）
  6. 产品类型路由（确定性兜底）：辅料→启用 fda_iig、跳过 clinicaltrials；原料药→反之
  7. 错误隔离：崩溃/超时(60s)/异常/导入失败 全部内部捕获，不影响其他 30 个工具

本文件完全独立，仅 import 现有工具的【底层函数】（不修改任何现有模块代码），
注册采取条件导入，导入失败也不影响其他工具。
"""

import asyncio
import json
import re
from typing import Optional

import httpx
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from agent.state import SearchResult
from config import get_settings
from tools.engines import anysearch_engine

# —— 复用现有 12 个数据源工具的底层检索函数（仅 import，不修改）——
from tools.sources.pubchem import _search_pubchem
from tools.sources.wikipedia import _search_wikipedia
from tools.sources.ema import _search_ema
from tools.sources.fda_faers import _search_faers
from tools.sources.fda_unii import _search_fda_unii
from tools.sources.drugbank import _search_drugbank
from tools.sources.fda_drugs import _search_fda_drugs
from tools.sources.pubmed import _search_pubmed
from tools.sources.dailymed import _search_dailymed
from tools.sources.clinicaltrials import _search_clinicaltrials
from tools.sources.fda_iig import _search_fda_iig
from tools.sources.espacenet import _search_espacenet
# jiansuo3 原有但之前速查工具缺失的 5 个数据源
from tools.sources.cde import _search_cde
from tools.sources.pmda import _search_pmda
from tools.sources.chembl import _search_chembl
from tools.sources.cnipa import _search_cnipa
from tools.sources.patent_search import fetch_pubchem_patents, fetch_pubmed_patent_articles, build_patent_result

settings = get_settings()


# ═════════════════════════════════════════════════════════════════════════════
# Schema 定义（对齐 jiansuo3 src/lib/types.ts — 模块化结构化字段）
# ═════════════════════════════════════════════════════════════════════════════
RAW_DRUG_SCHEMA = {
    "产品基本信息": [
        ("drug_name_cn", "中文名"), ("drug_name_en", "英文名"), ("brand_name", "商品名"),
        ("cas_number", "CAS号"), ("molecular_formula", "分子式"), ("molecular_weight", "分子量"),
        ("structure_id", "PubChem CID"), ("iupac_name", "IUPAC名"), ("logp", "LogP"),
        ("mechanism_of_action", "作用机制"), ("molecular_targets", "分子靶点"), ("bioactivity", "生物活性"),
        ("admet", "ADMET"), ("indications", "适应症"), ("dosage_form", "剂型"),
        ("dosage", "用法用量"), ("adverse_events", "不良反应"), ("boxed_warning", "黑框警告"),
        ("originator_launch", "原研上市"), ("insurance_vbp", "医保/集采"), ("cn_registration", "国内注册状态"),
    ],
    "国内登记情况": [
        ("cde_api_filing", "API备案(CDE)"), ("cde_generics", "仿制药申报(CDE)"), ("rld_reference", "参比制剂"),
    ],
    "国际监管情况": [
        ("fda_approval", "FDA审批"), ("ema_approval", "EMA审批"),
        ("pmda_approval", "PMDA(日本)审批"), ("unii_code", "UNII编号"),
    ],
    "专利信息": [
        ("compound_patent", "化合物专利"), ("compound_patent_expiry", "化合物专利到期"),
        ("crystal_patent", "晶型专利"), ("crystal_patent_expiry", "晶型专利到期"),
        ("formulation_patent", "制剂/用途专利"), ("formulation_patent_expiry", "制剂/用途专利到期"),
        ("process_patent", "合成方法专利"), ("process_patent_expiry", "合成方法专利到期"),
        ("patent_summary", "专利概况"),
    ],
    "临床试验": [("clinical_trials", "相关临床试验")],
    "文献与研究": [("pubmed_papers", "PubMed文献")],
    "数据溯源": [("citations_info", "引用统计")],
}

EXCIPIENT_SCHEMA = {
    "产品基本信息": [
        ("excipient_name_cn", "中文名"), ("excipient_name_en", "英文名"),
        ("cas_number", "CAS号"), ("unii_code", "UNII编号"),
        ("chemical_type", "化学类别"), ("physicochemical", "理化性质"),
        ("route_dosage", "给药途径与剂型"), ("mde", "最大日摄入量"),
    ],
    "应用情况": [
        ("cde_filing", "CDE登记号"), ("pharmacopeia", "药典收载"), ("marketed_products", "已上市制剂"),
    ],
    "监管与上市": [
        ("fda_iig", "FDA IIG（非活性成分指南）"), ("ema_info", "EMA信息"),
    ],
    "专利信息": [("patent", "相关专利")],
    "文献与研究": [("pubmed_papers", "PubMed文献")],
    "数据溯源": [("citations_info", "引用统计")],
}

# 源 → 模块映射（每个源的结果归入哪些模块）
SOURCE_MODULES = {
    "pubchem": ["产品基本信息"], "drugbank": ["产品基本信息"],
    "wikipedia": ["产品基本信息"], "fda_unii": ["产品基本信息", "国际监管情况"],
    "chembl": ["产品基本信息"], "dailymed": ["产品基本信息"],
    "fda_drugs": ["产品基本信息", "国际监管情况"], "fda_faers": ["产品基本信息"],
    "drugscom": ["产品基本信息"], "ema": ["国际监管情况"],
    "pmda": ["国际监管情况"], "cde": ["国内登记情况"],
    "yaozhi": ["国内登记情况"], "fda_iig": ["监管与上市"],
    "clinicaltrials": ["临床试验"], "pubmed": ["文献与研究"],
    # 注意：espacenet/cnipa 已从 SOURCE_FUNCS 移除，改由专利专项路径 _search_patents_direct 统一调用，
    # 避免与 _search_pubchem_patents 的专利输出重复。
}

# ─────────────────────────────────────────────────────────────────────────────
# 内置搜索函数（必须在 SOURCE_FUNCS 之前定义）
# ─────────────────────────────────────────────────────────────────────────────
async def _search_drugscom(query: str) -> SearchResult:
    """Drugs.com 药品信息搜索——仅对原料药启用，提供适应症/不良反应/相互作用等信息。"""
    try:
        result = await asyncio.to_thread(
            anysearch_engine.anysearch_vertical,
            f"{query} site:drugs.com",
            domain="health",
            max_results=5,
        )
        if result.success and "No results" not in result.content:
            result.source_name = "Drugs.com"
            return result
    except Exception:
        pass
    return SearchResult.empty("Drugs.com", "搜索无结果")


async def _search_yaozhi(query: str) -> SearchResult:
    """国内登记结论式检索（原药智网 site 泛搜，输出为新闻流；改定向结论检索词）。
    目标：返回「是否批准/上市时间/受理号/参比制剂」等明确结论，而非新闻列表。
    jiansuo3 中原有 9 子工具（MCP），当前 MCP 客户端不可用，以 AnySearch 定向检索作为兜底。"""
    try:
        result = await asyncio.to_thread(
            anysearch_engine.anysearch_vertical,
            f"{query} 国家药监局 NMPA 批准上市 受理号 参比制剂 国内",
            domain="health",
            max_results=6,
        )
        if result.success and "No results" not in result.content:
            result.source_name = "国内登记检索"
            return result
    except Exception:
        pass
    return SearchResult.empty("国内登记检索", "未查到明确的国内登记信息")


# 数据源 → 置信度（P0.2 置信度修正：按真实权威度重定）
# 官方 API 直连=高（≥85）；网络检索兜底=低（40–60）；LLM 解析=中（70）。
# 该字典作为各源权威度参考；字段级置信度在 _extract_*_fields 中按此取值（chembl/entity_info 已接线）。
# 键名与 SOURCE_FUNCS 的源 key 保持一致（小写）。
CONFIDENCE = {
    "pubchem": 100,        # 官方 API（化学标识符一手）
    "fda_unii": 100,       # 官方 API
    "fda_iig": 100,        # 官方 API
    "fda_drugs": 100,      # 官方 API
    "dailymed": 95,        # 官方标签 API
    "fda_faers": 90,       # 官方不良反应 API
    "clinicaltrials": 90,  # 官方试验注册 API
    "pubmed": 85,          # 文献 API（权威）
    "rxnorm": 90,          # 官方术语 API
    "open_targets": 90,    # 官方靶点 API
    "drugcentral": 90,     # 官方药物 API
    "coconut": 85,         # 官方天然产物 API
    "wikipedia": 60,       # 通用百科（非专业权威）
    "drugbank": 50,        # 仅 Tavily 域名搜索（非官方 API）
    "ema": 55,             # 仅联网搜索
    "cde": 50,             # 仅联网搜索
    "pmda": 50,            # 仅联网搜索
    "chembl": 88,          # ChEMBL ID 权威；MCP 接入后提供靶点/机制/生物活性/ADMET 深度数据
    "espacenet": 45,       # 仅联网搜索
    "cnipa": 50,           # 仅联网搜索
    "drugscom": 50,        # 仅联网搜索
    "yaozhi": 50,          # 仅联网搜索
    "entity_info": 70,     # LLM 实体解析（非一手数据）
}

# 每个数据源对应的底层检索函数（key 即置信度/路由使用的源标识）—— jiansuo3 全 19 源
SOURCE_FUNCS = {
    "pubchem": _search_pubchem,
    "wikipedia": _search_wikipedia,
    "ema": _search_ema,
    "fda_faers": _search_faers,
    "fda_unii": _search_fda_unii,
    "drugbank": _search_drugbank,
    "fda_drugs": _search_fda_drugs,
    "pubmed": _search_pubmed,
    "dailymed": _search_dailymed,
    "fda_iig": _search_fda_iig,
    "clinicaltrials": _search_clinicaltrials,
    # jiansuo3 新增 5 源
    "cde": _search_cde,
    "pmda": _search_pmda,
    "chembl": _search_chembl,
    "drugscom": _search_drugscom,
    "yaozhi": _search_yaozhi,
    # 注意：espacenet/cnipa 已移至专利专项路径 _search_patents_direct（P0-1 B 整合），
    # 避免与 _search_pubchem_patents 的专利输出重复。
}

# 与产品类型绑定的专属源
EXCIPIENT_ONLY = {"fda_iig"}
API_ONLY = {"clinicaltrials", "drugscom"}

# 常见辅料关键词（中英文），用于路由的确定性兜底
EXCIPIENT_KEYWORDS = {
    "乳糖", "微晶纤维素", "硬脂酸镁", "淀粉", "蔗糖", "甘露醇", "滑石粉", "明胶",
    "羧甲基", "羟丙基", "交联", "聚乙烯", "聚维酮", "二氧化硅", "磷酸钙", "碳酸钙",
    "十二烷基硫酸钠", "司盘", "吐温", "巴西棕榈", "交联羧甲基", "甲基纤维素", "预胶化",
    "lactose", "microcrystalline cellulose", "magnesium stearate", "starch", "sucrose",
    "mannitol", "talc", "gelatin", "povidone", "crospovidone", "silicon dioxide",
    "croscarmellose", "hydroxypropyl", "cellulose", "calcium carbonate",
    "sodium starch glycolate", "colloidal silicon", "carboxymethyl",
}

TIMEOUT_PER_SOURCE = 25          # 单源超时
TIMEOUT_TOTAL = 60               # 整体超时（错误隔离硬上限）
# 已知慢源定制更短超时（大文件/低稳定性接口挂起是 60s 预算被拖垮的主因）
_SLOW_SOURCE_TIMEOUT = {
    "dailymed": 12,     # FDA 大标签 API 经常 30s+ 无响应，12s 截断不影响其他源
    "wikipedia": 15,    # 22s 才失败，15s 截断可明显收窄 gather 等待
    "chembl": 15,       # ChEMBL MCP 子进程通信较慢
}
CAS_RE = re.compile(r"^\d{1,7}-\d{2}-\d$")


# ─────────────────────────────────────────────────────────────────────────────
# 1) 关键词扩展（LLM）
# ─────────────────────────────────────────────────────────────────────────────
async def _expand_keywords(query: str) -> dict:
    """LLM 把输入（中文名/商品名/CAS）解析为 englishName + casNumber + productType。
    失败回退为原 query。借鉴 jiansuo3 expandKeywords。"""
    fallback = {
        "englishName": query,
        "casNumber": "",
        "productType": "未知",
        "synonyms": [query],
    }
    try:
        llm = ChatOpenAI(
            model=settings.deepseek_model,
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            temperature=0.2,
        )
        system = (
            "你是一位资深的医药信息检索专家，精通原辅料（药用辅料和原料药）的名称体系。\n"
            "用户会输入一个产品的名称（可能是中文名、英文名、商品名、CAS号等），"
            "你需要全面解析这个产品，为后续多数据源检索提供精准的搜索词。\n\n"
            "关键原则：\n"
            "1. 如果输入的是商品名/品牌名（如 circliq、Ludipress），必须找到其对应的通用名/INN 和活性成分\n"
            "2. 如果输入的是通用名（如乳糖/Lactose），提供最常见英文通用名\n"
            "3. 判断产品类型（必须明确，除非确实无法判断）：\n"
            "   - 药用辅料(excipient)：用于制剂成型、稳定、释药的惰性/功能性材料。"
            "如 乳糖 Lactose、微晶纤维素、硬脂酸镁、淀粉、蔗糖、甘露醇、滑石粉、明胶、PVP、"
            "交联羧甲基纤维素钠、羟丙甲纤维素 等 → 填 '药用辅料'\n"
            "   - 原料药/API(active ingredient)：有治疗活性的药物成分。"
            "如 阿司匹林 Aspirin、布洛芬、阿莫西林、Acalabrutinib、莫洛替尼 等 → 填 '原料药'\n"
            "   - 确实无法判断才填 '未知'\n\n"
            "示例：\n"
            "输入'乳糖' → {\"englishName\":\"Lactose\",\"casNumber\":\"63-42-3\",\"productType\":\"药用辅料\"}\n"
            "输入'阿司匹林' → {\"englishName\":\"Aspirin\",\"casNumber\":\"50-78-2\",\"productType\":\"原料药\"}\n\n"
            '请以 JSON 格式返回，必须使用以下英文字段名：\n'
            '{\n'
            '  "englishName": "最常用的英文通用名（必填，如 Acalabrutinib）",\n'
            '  "casNumber": "CAS号（如 1420477-60-6，不知道填空字符串）",\n'
            '  "productType": "原料药/药用辅料/未知",\n'
            '  "synonyms": ["同义词1", "商品名1"]\n'
            "}\n\n"
            "只返回 JSON，不要其他内容。如果不确定某个字段，填空字符串或空数组。"
        )
        # LLM 慢响应会挤占 60s 总预算，加 12s 硬超时，失败回退原文解析
        resp = await asyncio.wait_for(
            llm.ainvoke([
                SystemMessage(content=system),
                HumanMessage(content=f"产品名称：{query}"),
            ]),
            timeout=12,
        )
        content = resp.content if isinstance(resp.content, str) else str(resp.content)
        m = re.search(r"\{[\s\S]*\}", content)
        if not m:
            return fallback
        parsed = json.loads(m.group(0))
        return {
            "englishName": parsed.get("englishName") or query,
            "casNumber": parsed.get("casNumber") or "",
            "productType": parsed.get("productType") or "未知",
            "synonyms": parsed.get("synonyms") or [query],
        }
    except Exception:
        return fallback


def _classify_product_type(query: str, expanded: dict) -> str:
    """路由判定：优先用 LLM 明确结果；否则用辅料关键词表确定性兜底；仍未命中默认原料药。
    返回 '药用辅料' 或 '原料药'。保证稳定二选一（不再'都查'）。"""
    pt = (expanded.get("productType") or "").strip()
    if "辅料" in pt:
        return "药用辅料"
    if "原料药" in pt or pt.upper() == "API":
        return "原料药"
    text = " ".join([
        query,
        expanded.get("englishName", ""),
        " ".join(expanded.get("synonyms", []) or []),
    ]).lower()
    for kw in EXCIPIENT_KEYWORDS:
        if kw.lower() in text:
            return "药用辅料"
    return "原料药"  # 默认：药物查询大多为 API


# ─────────────────────────────────────────────────────────────────────────────
# 2) 实体解析 + CAS 验证（PubChem REST，无需 LLM）
# ─────────────────────────────────────────────────────────────────────────────
async def _pubchem_resolve(name: str) -> tuple[Optional[str], Optional[str]]:
    """用 PubChem 解析英文名与真实 CAS（借鉴 jiansuo3 resolveEntity/verifyCASNumber）。
    返回 (canonical_name, cas_or_none)。走已验证稳定的 synonyms 端点。"""
    if not name or len(name.strip()) < 2:
        return None, None
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # 一次请求同时拿 CID 与同义词（含 CAS），避免裸 /JSON 端点不稳定
            r = await client.get(
                f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{name}/synonyms/JSON"
            )
            if not r.ok:
                return None, None
            info = r.json().get("InformationList", {}).get("Information", [])
            if not info or not info[0]:
                return None, None
            cid = info[0].get("CID")
            syns = info[0].get("Synonym", [])
            cas = next((s for s in syns if CAS_RE.match(s)), None)
            canonical = None
            if cid:
                props = await client.get(
                    f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/property/Title,IUPACName/JSON"
                )
                if props.ok:
                    p = props.json().get("PropertyTable", {}).get("Properties", [{}])[0]
                    canonical = p.get("Title") or p.get("IUPACName")
            return canonical, cas
    except Exception:
        return None, None


async def _verify_cas(cas: str) -> bool:
    """验证 CAS 号是否在 PubChem 中存在（借鉴 jiansuo3 verifyCASNumber）。
    注意：PubChem PUG-REST 不支持 cas 输入命名空间，CAS 号须作为 name 查询。"""
    if not cas or len(cas) < 5 or not CAS_RE.match(cas):
        return False
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{cas}/JSON"
            )
            return r.status_code == 200 and bool(r.json().get("PC_Compounds"))
    except Exception:
        return False


# ═════════════════════════════════════════════════════════════════════════════
# 结构化字段提取器（从源文本确定性提取字段值）
# ═════════════════════════════════════════════════════════════════════════════

def _extract_pubchem_fields(text: str, src_url: str) -> list:
    fields = []
    # 化合物名（可能在行内带 CID，也可能分两行）
    m = re.search(r"(?:化合物|Compound):\s*(.+)", text)
    if m:
        name_part = m.group(1).strip()
        # 去除行内的 CID 尾缀
        cid_inline = re.search(r"\bCID:\s*(\d+)", name_part)
        if cid_inline:
            fields.append({"key":"structure_id","label":"PubChem CID","value":cid_inline.group(1),
                           "source":"PubChem","sourceUrl":src_url,"confidence":100})
            name_part = re.sub(r"\s*\(?\s*CID:\s*\d+\s*\)?", "", name_part).strip()
        if name_part:
            fields.append({"key":"drug_name_en","label":"英文名","value":name_part,
                           "source":"PubChem","sourceUrl":src_url,"confidence":100})
    # CID 也可能在独立行
    m = re.search(r"^CID:\s*(\d+)", text, re.MULTILINE)
    if m:
        existing = any(f["key"]=="structure_id" for f in fields)
        if not existing:
            fields.append({"key":"structure_id","label":"PubChem CID","value":m.group(1),
                           "source":"PubChem","sourceUrl":src_url,"confidence":100})
    for pat_key in [("molecular_formula","分子式"),("molecular_weight","分子量"),
                    ("logp","LogP")]:
        m = re.search(rf"{pat_key[1]}:\s*(.+)", text)
        if m:
            fields.append({"key":pat_key[0],"label":pat_key[1],"value":m.group(1).strip(),
                           "source":"PubChem","sourceUrl":src_url,"confidence":100})
    m = re.search(r"IUPAC:\s*(.+)", text)
    if m:
        val = re.sub(r"\s+"," ", m.group(1).strip())
        fields.append({"key":"iupac_name","label":"IUPAC名","value":val,
                       "source":"PubChem","sourceUrl":src_url,"confidence":100})
    m = re.search(r"CAS[号]?[：:]\s*(.+)", text)
    if m and CAS_RE.match(m.group(1).strip()):
        fields.append({"key":"cas_number","label":"CAS号","value":m.group(1).strip(),
                       "source":"PubChem","sourceUrl":src_url,"confidence":100})
    return fields


def _extract_unii_fields(text: str, src_url: str) -> list:
    fields = []
    m = re.search(r"UNII:\s*(.+)", text)
    if m:
        fields.append({"key":"unii_code","label":"UNII编号","value":m.group(1).strip(),
                       "source":"FDA UNII","sourceUrl":src_url,"confidence":100})
    # UNII 源输出格式: "品牌名: XXX"（不是"商品名"）
    for pat in [r"品牌名:\s*(.+)", r"商品名:\s*(.+)", r"Brand.?Name:?\s*(.+)" ]:
        m = re.search(pat, text)
        if m:
            val = m.group(1).strip()
            if val and val.upper() != "N/A":
                fields.append({"key":"brand_name","label":"商品名","value":val,
                               "source":"FDA UNII","sourceUrl":src_url,"confidence":100})
            break
    return fields


def _extract_chembl_fields(text: str, src_url: str) -> list:
    fields = []
    # 鲁棒提取 ChEMBL ID（兼容 REST 格式 "(CHEMBL25)" 与 MCP 格式 "ChEMBL ID: CHEMBL25"）
    m = re.search(r"(CHEMBL[A-Za-z0-9-]+)", text, re.I)
    if m:
        chembl_id = m.group(1).strip()
        url = f"https://www.ebi.ac.uk/chembl/compound_report_card/{chembl_id}"
        fields.append({"key":"chembl_id","label":"ChEMBL ID","value":chembl_id,
                       "source":"ChEMBL","sourceUrl":url,"confidence":CONFIDENCE["chembl"]})
    # P0.4 ChEMBL MCP 深度字段（仅当 MCP 提供时存在对应行）
    pairs = [
        (r"规范名称[:：]\s*(.+)", "drug_name_en", "英文通用名"),
        (r"SMILES[:：]\s*(\S+)", "smiles", "SMILES"),
        (r"作用机制\(MOA\)[:：]\s*(.+)", "mechanism_of_action", "作用机制"),
        (r"分子靶点[:：]\s*(.+)", "molecular_targets", "分子靶点"),
        (r"生物活性[:：]\s*(.+)", "bioactivity", "生物活性"),
        (r"ADMET/理化性质[:：]\s*(.+)", "admet", "ADMET/理化性质"),
    ]
    for pat, key, label in pairs:
        mm = re.search(pat, text)
        if mm:
            val = mm.group(1).strip()
            if val:
                fields.append({"key":key,"label":label,"value":val[:500],
                               "source":"ChEMBL (MCP)","sourceUrl":src_url,"confidence":CONFIDENCE["chembl"]})
    return fields


def _clean_cn_fragment(frag: str) -> str:
    """清洗国内登记结论片段：去 Markdown/®/截断符，锚点截取核心结论，去冗余修饰与尾随从句。

    输入示例（AnySearch 截断的新闻标题）：
        "新一代高选择性BTK 抑制剂康可期®在中国获批上市用于既往至少接受 ..."
    输出：
        "康可期在中国获批上市"
    """
    if not frag:
        return ""
    frag = re.sub(r"^#{1,6}\s*", "", frag).strip()
    frag = frag.replace("**", "").replace("®", "").replace("™", "").strip()
    # 公告标题噪音：NMPA/药监局"…的通知（药…文号）"不是药物获批结论，整体丢弃
    # （特征：含"的通知/资料要求/审评审批中/数据保护"或"（药/（药[年] 文号"）
    if re.search(r"(?:的通知|资料要求|审评审批中|数据保护|\(药\d{4}|（药\d{4}|药监综函)", frag):
        return ""
    # 循环剥离尾随适应症/用途从句（"用于…"、"适用于…"、"治疗…"，含"用于治疗"嵌套）
    prev = None
    while prev != frag:
        prev = frag
        frag = re.sub(r"(?:用于|适用于|适应于|用于既往|针对|治疗)[^，,。；;!?]{0,}$", "", frag).strip()
    # 锚点截取：以结论词为锚，向前仅保留"日期 + 药名"（丢弃"新一代高选择性BTK 抑制剂"等修饰）
    anchor = re.search(r"(已在中国获得上市批准|在中国获批上市|在中国批准上市|附条件批准|批准上市|获批上市|获准上市|获批进口|取得药品注册证)", frag)
    if anchor:
        head = frag[: anchor.start()]
        keep = ""
        # 保留日期前缀（如"2023年3月"）
        date_m = re.search(r"\d{4}\s*年\s*\d{1,2}\s*月", head)
        if date_m:
            keep += date_m.group(0)
        head_plain = re.sub(r"\s+", "", head)
        # 纯中文候选若含虚词/公告性词（"发布前已经批准上市"→"发布前已经"），不视为药名
        _NON_NAME = ("的", "和", "与", "及", "或", "前", "后", "中", "已", "经", "发布",
                     "通知", "要求", "数据", "资料", "审评", "审批", "于", "在", "获",
                     "被", "相关", "有关", "该", "此", "其", "等", "为", "对", "向", "并", "将")
        if (re.fullmatch(r"[\u4e00-\u9fa5]{2,14}", head_plain)
                and not any(w in head_plain for w in _NON_NAME)):
            nm = head_plain  # 纯中文机构名/药名整体保留（如"国家药品监督管理局"）
        else:
            cn_blocks = re.findall(r"[\u4e00-\u9fa5]{2,6}", head)
            nm = cn_blocks[-1] if cn_blocks else ""
            # 从尾部剥离含虚词的块，保证 nm 是真实药名候选（而非公告状语）
            while len(cn_blocks) > 1 and any(w in nm for w in _NON_NAME):
                cn_blocks = cn_blocks[:-1]
                nm = cn_blocks[-1]
            # 剥离修饰前缀（"抑制剂"/"类药物"等常与药名连写），剥离后仍 ≥2 字才接受
            nm2 = re.sub(r"^(?:抑制剂|类药物|药物|片剂|胶囊|制剂|口服液|注射液|粉针)", "", nm)
            if len(nm2) >= 2:
                nm = nm2
        if nm:
            keep += nm
        frag = keep + frag[anchor.start():]
    else:
        # 无中文结论锚点：可能是英文片段（检索通路已限定中文关键词，此处防御性返回空）
        return ""
    # 截断国际监管噪音：锚点后若混入"美国: 标准获批 欧洲: 标准获批"等多国状态并列
    # 内容（AnySearch 常见句式），自第一个国际关键词处截断，只保留中国监管结论。
    for _noise in ("美国", "欧洲", "日本", "获FDA", "FDA", "Calquence", "EMA", "欧盟"):
        _pos = frag.find(_noise)
        if _pos > 0:
            frag = frag[:_pos]
            break
    # 清理残留符号与截断符
    frag = re.sub(r"^[、，,；;：:·\s]+", "", frag).strip()
    frag = re.sub(r"\.{2,}|…+", "", frag).strip()
    frag = re.sub(r"(?:用|以|等|后|中)$", "", frag).strip()  # 去单字残留（"上市用…"截断后）
    return frag[:120]


def _extract_cn_registration_fields(text: str, src_url: str) -> list:
    """从国内登记检索文本中提取结论式字段（是否获批/上市时间/参比制剂/受理情况）。

    目标：把「结论」变成结构化字段，而非把整段新闻文本扔进 text_parts。
    检索词已定向（"中国 批准 上市 参比制剂 受理"），文本通常含明确结论。
    """
    if not text:
        return []
    fields = []
    text1 = re.sub(r"\s+", " ", text).strip()
    # 批准/上市结论（短句优先，如"康可期 2023年3月 NMPA 附条件批准上市"；
    # 只取从"批准/获批/上市"到最近断句的一段，避免吞入整段长句）
    # 遍历全部候选：优先取"足够具体"（≥8 字）且非公告标题的结论；
    # 公告标题（"…的通知（药…"）在 _clean_cn_fragment 中会被整体丢弃（返回空）
    reg_val = None
    for _pat in (r"[^。；;!?]{0,30}(?:附条件批准|批准上市|获批上市|已在中国获得上市批准|获批进口)[^。；;!?]{0,40}",
                 r"(?:附条件批准|批准上市|获批上市|获批进口|获准上市)[^。；;!?]{0,50}"):
        for _m in re.finditer(_pat, text1):
            _c = _clean_cn_fragment(_m.group(0).strip())
            if len(_c) >= 8:
                reg_val = _c
                break
            if not reg_val:
                reg_val = _c
        if reg_val:
            break
    if reg_val:
        fields.append({
            "key": "cn_registration", "label": "国内注册状态",
            "value": reg_val, "source": "国内登记检索", "sourceUrl": src_url, "confidence": 60,
        })
    # 参比制剂（CDE 参比制剂目录编号）
    m = re.search(r"参比制剂[：: ]?\s*([0-9]{2}-?\d{1,4}|第\s*[0-9]+\s*批|[A-Za-z0-9\-（）()]{3,40})", text)
    if m:
        fields.append({
            "key": "rld_reference", "label": "参比制剂",
            "value": m.group(1).strip()[:120], "source": "国内登记检索", "sourceUrl": src_url, "confidence": 60,
        })
    # 受理号（CDE 受理号格式如 CXHL2300123 / JXHS2101234）
    m = re.search(r"(?:受理号|受理)[：: ]?\s*((?:CX|JX|CY|JY)[A-Z]{1,3}\d{4,8})", text)
    if m:
        fields.append({
            "key": "cde_generics", "label": "仿制药申报(CDE)受理",
            "value": m.group(1).strip(), "source": "国内登记检索", "sourceUrl": src_url, "confidence": 60,
        })
    return fields


EXTRACTORS = {"pubchem":_extract_pubchem_fields,"fda_unii":_extract_unii_fields,"chembl":_extract_chembl_fields,
              "cde": _extract_cn_registration_fields, "yaozhi": _extract_cn_registration_fields}


# ═════════════════════════════════════════════════════════════════════════════
# Markdown 格式化工具（解决文本换行/渲染问题）
# ═════════════════════════════════════════════════════════════════════════════

def _fmt_markdown(text: str, source_name: str) -> str:
    """将各源原始文本转为 ReactMarkdown 可正确渲染的格式。
    - 双重换行 = 段落分隔
    - [N] 开头的行 = 有序列表项 + 加粗标题
    - 缩进的续行 = 软换行（两空格结尾）
    - key: value 行 = **key**: value
    """
    lines = text.split('\n')
    out = []
    in_list = False

    for i, raw in enumerate(lines):
        line = raw.rstrip()
        if not line.strip():
            in_list = False
            out.append('')
            continue

        # 编号项 [1] / [2] → markdown 有序列表
        m = re.match(r'^\[(\d+)\]\s+(.+)', line)
        if m:
            if not in_list:
                out.append('')  # 空行分隔上文
            rest = m.group(2).strip()
            # 标题部分加粗（取到第一个冒号或括号前的内容）
            title = rest.split('(')[0].strip()
            out.append(f'{m.group(1)}. **{title}**')
            in_list = True
            continue

        # 缩进续行（NCT:/PMID:/状态: 等详情）→ 软换行
        if in_list and (line.startswith('    ') or line.startswith('\t') or
                        re.match(r'^(NCT:|PMID:|阶段:|状态:|Phase|Status:)', line.strip())):
            stripped = line.strip()
            out.append(f'  {stripped}')
            continue

        # key: value 格式 → **key**: value
        m = re.match(r'^([A-Za-z\u4e00-\u9fff]+):\s*\b', line)
        if m and not in_list:
            out.append(f'- **{m.group(1)}**: {line[m.end():].strip()}')
            continue

        # 普通行
        in_list = False
        out.append(line)

    result = '\n'.join(out)
    # 清理多余空行
    result = re.sub(r'\n{3,}', '\n\n', result)
    return f"### {source_name}\n\n{result.strip()}"


# ═════════════════════════════════════════════════════════════════════════════
# 医学术语翻译表（英文→中文）
# ═════════════════════════════════════════════════════════════════════════════

BIO_GLOSSARY = [
    # 临床试验相关
    ("for the Treatment of", "用于治疗"),
    ("for the Prevention of", "用于预防"),
    ("A Study of", "研究："),
    ("Study to Evaluate", "评估研究："),
    ("A Phase", "一项第"),
    ("Phase 1", "I期"),
    ("Phase 2", "II期"),
    ("Phase 3", "III期"),
    ("Phase I", "I期"),
    ("Phase II", "II期"),
    ("Phase III", "III期"),
    ("PHASE1", "I期"),
    ("PHASE2", "II期"),
    ("PHASE3", "III期"),
    ("Multicenter", "多中心"),
    ("Randomized", "随机"),
    ("Double-Blind", "双盲"),
    ("Open-Label", "开放标签"),
    ("Placebo-Controlled", "安慰剂对照"),
    ("Single Arm", "单臂"),
    ("Efficacy and Safety", "疗效与安全性"),
    ("Safety and Efficacy", "安全性与疗效"),
    ("Safety and Tolerability", "安全性与耐受性"),
    ("Pharmacokinetics", "药代动力学"),
    ("Pharmacodynamics", "药效学"),
    ("Bioavailability", "生物利用度"),
    ("Dose Escalation", "剂量递增"),
    ("Dose Expansion", "剂量扩展"),
    ("First-in-Human", "首次人体"),
    ("Maximum Tolerated Dose", "最大耐受剂量"),
    ("Recommended Phase 2 Dose", "推荐II期剂量"),
    ("Overall Survival", "总生存期"),
    ("Progression-Free Survival", "无进展生存期"),
    ("Overall Response Rate", "总缓解率"),
    ("Complete Response", "完全缓解"),
    ("Partial Response", "部分缓解"),
    ("Stable Disease", "疾病稳定"),
    ("Adverse Event", "不良事件"),
    ("Serious Adverse Event", "严重不良事件"),
    ("Treatment-Emergent", "治疗期间出现的"),
    ("Dose-Limiting Toxicity", "剂量限制性毒性"),
    ("在新窗口打开", ""),
    ("在新窗口中打开", ""),

    # 疾病/适应症
    ("Chronic Lymphocytic Leukemia", "慢性淋巴细胞白血病"),
    ("Small Lymphocytic Lymphoma", "小淋巴细胞淋巴瘤"),
    ("Mantle Cell Lymphoma", "套细胞淋巴瘤"),
    ("Diffuse Large B-Cell Lymphoma", "弥漫大B细胞淋巴瘤"),
    ("Follicular Lymphoma", "滤泡性淋巴瘤"),
    ("Hodgkin Lymphoma", "霍奇金淋巴瘤"),
    ("Non-Hodgkin Lymphoma", "非霍奇金淋巴瘤"),
    ("Multiple Myeloma", "多发性骨髓瘤"),
    ("Acute Myeloid Leukemia", "急性髓系白血病"),
    ("Acute Lymphoblastic Leukemia", "急性淋巴细胞白血病"),
    ("Chronic Myeloid Leukemia", "慢性髓系白血病"),
    ("Myelodysplastic Syndrome", "骨髓增生异常综合征"),
    ("Myeloproliferative Neoplasm", "骨髓增殖性肿瘤"),
    ("Breast Cancer", "乳腺癌"),
    ("Lung Cancer", "肺癌"),
    ("Non-Small Cell Lung Cancer", "非小细胞肺癌"),
    ("Small Cell Lung Cancer", "小细胞肺癌"),
    ("Prostate Cancer", "前列腺癌"),
    ("Colorectal Cancer", "结直肠癌"),
    ("Pancreatic Cancer", "胰腺癌"),
    ("Ovarian Cancer", "卵巢癌"),
    ("Gastric Cancer", "胃癌"),
    ("Hepatocellular Carcinoma", "肝细胞癌"),
    ("Renal Cell Carcinoma", "肾细胞癌"),
    ("Melanoma", "黑色素瘤"),
    ("Glioblastoma", "胶质母细胞瘤"),
    ("Graft Versus Host Disease", "移植物抗宿主病"),
    ("Rheumatoid Arthritis", "类风湿关节炎"),
    ("Systemic Lupus Erythematosus", "系统性红斑狼疮"),
    ("Crohn's Disease", "克罗恩病"),
    ("Ulcerative Colitis", "溃疡性结肠炎"),
    ("Psoriasis", "银屑病"),
    ("Atopic Dermatitis", "特应性皮炎"),
    ("Alzheimer's Disease", "阿尔茨海默病"),
    ("Parkinson's Disease", "帕金森病"),
    ("Type 2 Diabetes", "2型糖尿病"),

    # 药物/作用机制
    ("Bruton's Tyrosine Kinase", "布鲁顿酪氨酸激酶"),
    ("BTK Inhibitor", "BTK抑制剂"),
    ("Tyrosine Kinase Inhibitor", "酪氨酸激酶抑制剂"),
    ("Monoclonal Antibody", "单克隆抗体"),
    ("Antibody-Drug Conjugate", "抗体偶联药物"),
    ("Immune Checkpoint Inhibitor", "免疫检查点抑制剂"),
    ("PD-1 Inhibitor", "PD-1抑制剂"),
    ("PD-L1 Inhibitor", "PD-L1抑制剂"),
    ("CAR-T Cell Therapy", "CAR-T细胞治疗"),
    ("Biosimilar", "生物类似药"),
    ("Small Molecule", "小分子"),
    ("Proteasome Inhibitor", "蛋白酶体抑制剂"),
    ("CDK4/6 Inhibitor", "CDK4/6抑制剂"),
    ("PARP Inhibitor", "PARP抑制剂"),
    ("EGFR Inhibitor", "EGFR抑制剂"),
    ("ALK Inhibitor", "ALK抑制剂"),
    ("MEK Inhibitor", "MEK抑制剂"),
    ("BRAF Inhibitor", "BRAF抑制剂"),
    ("JAK Inhibitor", "JAK抑制剂"),
    ("SGLT2 Inhibitor", "SGLT2抑制剂"),
    ("GLP-1 Receptor Agonist", "GLP-1受体激动剂"),

    # 监管/注册
    ("Approved", "已获批"),
    ("Orphan Drug", "孤儿药"),
    ("Breakthrough Therapy", "突破性疗法"),
    ("Fast Track", "快速通道"),
    ("Priority Review", "优先审评"),
    ("Accelerated Approval", "加速批准"),
    ("New Drug Application", "新药申请"),
    ("Investigational New Drug", "研究性新药"),
    ("Marketing Authorization", "上市许可"),
    ("Conditional Approval", "有条件批准"),
    ("in Combination with", "联合"),
    ("Monotherapy", "单药治疗"),
    ("Combination Therapy", "联合治疗"),
    ("First-Line", "一线"),
    ("Second-Line", "二线"),
    ("Third-Line", "三线"),
    ("Relapsed/Refractory", "复发/难治性"),
    ("Relapsed or Refractory", "复发或难治性"),
    ("Treatment-Naive", "初治"),
    ("Previously Treated", "既往接受过治疗的"),
    ("With or Without", "联合或不联合"),
    ("Following", "继"),

    # 常见英文缩写/短语
    ("vs.", "对比"),
    ("versus", "对比"),
    ("Compared to", "对比"),
    ("Comparator", "对照药"),
    ("Standard of Care", "标准治疗"),
    ("Best Supportive Care", "最佳支持治疗"),
    ("Progression-Free", "无进展"),
    ("Overall Response", "总缓解"),
    ("Duration of Response", "缓解持续时间"),
    ("Time to Progression", "进展时间"),
    ("Clinical Outcome", "临床结局"),
    ("Primary Endpoint", "主要终点"),
    ("Secondary Endpoint", "次要终点"),
    ("Inclusion Criteria", "纳入标准"),
    ("Exclusion Criteria", "排除标准"),
    ("Informed Consent", "知情同意"),
    ("Institutional Review Board", "机构审查委员会"),
    ("Ethics Committee", "伦理委员会"),
    ("Data Monitoring Committee", "数据监察委员会"),

    # PubMed 文献相关
    ("a new agent", "一种新药物"),
    ("a novel", "一种新型"),
    ("Review", "综述"),
    ("Systematic Review", "系统综述"),
    ("Meta-Analysis", "荟萃分析"),
    ("Case Report", "病例报告"),
    ("Clinical Trial", "临床试验"),
    ("Retrospective Study", "回顾性研究"),
    ("Prospective Study", "前瞻性研究"),
    ("Observational Study", "观察性研究"),
    ("Real-World Evidence", "真实世界证据"),
    ("Real-World Data", "真实世界数据"),
    ("Long-Term Follow-Up", "长期随访"),
    ("mechanism of action", "作用机制"),
    ("drug-drug interaction", "药物相互作用"),
    ("adverse drug reaction", "药物不良反应"),
    ("therapeutic drug monitoring", "治疗药物监测"),
    ("precision medicine", "精准医疗"),
    ("personalized medicine", "个体化医疗"),
    ("pharmacogenomics", "药物基因组学"),
    ("pharmacovigilance", "药物警戒"),

    # EMA/FDA/PMDA 监管
    ("European Medicines Agency", "欧洲药品管理局"),
    ("Food and Drug Administration", "美国食品药品监督管理局"),
    ("Pharmaceuticals and Medical Devices Agency", "日本药品医疗器械管理局"),
    ("Summary of Product Characteristics", "产品特性概要"),
    ("Risk Management Plan", "风险管理计划"),
    ("Periodic Safety Update Report", "定期安全性更新报告"),
    ("Post-Marketing Surveillance", "上市后监测"),
    ("withdrawn", "已撤回"),
    ("refused", "被拒绝"),
    ("suspended", "已暂停"),
    ("under review", "审评中"),
    ("positive opinion", "积极意见"),
    ("negative opinion", "否定意见"),
    ("Paediatric Investigation Plan", "儿童研究计划"),
    ("active substance", "活性成分"),
    ("excipient", "辅料"),
    ("INN", "国际非专利名称"),
    ("International Nonproprietary Name", "国际非专利名称"),
]


def _translate_bio_text(text: str) -> str:
    """将医学术语密集的英文文本翻译为中文（基于术语表替换）。"""
    result = text
    for en, cn in BIO_GLOSSARY:
        if en in result:
            result = result.replace(en, cn)
    return result.strip()


def _is_mostly_english(text: str) -> bool:
    """粗略判断文本是否以英文为主（字母中 ASCII 占比 > 50% 视为英文）。"""
    if not text:
        return False
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return False
    ascii_n = sum(1 for ch in letters if ord(ch) < 128)
    return ascii_n / len(letters) > 0.5


async def _translate_text_llm(text: str) -> str:
    """用 LLM 将英文医药文本翻译为中文；失败/超时返回空串（调用方降级术语表）。

    真实翻译替代原术语表替换，解决"中文翻译失效"（词表替换后文本仍为英文，前端按钮不出现）。
    """
    if not text or len(text.strip()) < 20:
        return ""
    try:
        llm = ChatOpenAI(
            model=settings.deepseek_model,
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            temperature=0.1,
        )
        system = (
            "你是资深医药翻译。把用户提供的英文医药文本翻译成准确、流畅的中文。\n"
            "要求：\n"
            "1. 专业缩写保留原文（如 BTK、FDA、EMA、CDE、NCT 编号、PMID、CAS 号）\n"
            "2. 药物名称保留英文（可在首次出现时附中文名）\n"
            "3. 保留原文结构（列表/要点），不增删信息\n"
            "4. 只输出译文本身，不要任何解释或前缀\n"
            "5. 若文本已是中文或过短，原样返回"
        )
        resp = await asyncio.wait_for(
            llm.ainvoke([SystemMessage(content=system),
                         HumanMessage(content=text[:3000])]),
            timeout=10,
        )
        out = (resp.content if isinstance(resp.content, str) else str(resp.content)).strip()
        if out and out != text:
            return out[:2500]
    except Exception:
        pass
    return ""


# ═════════════════════════════════════════════════════════════════════════════
# 专利模块：优先 AnySearch IP/专利垂直检索（第三方专利分析站明确结论），
# PubChem 专利统计 + 到期估算降级为兜底。
# ═════════════════════════════════════════════════════════════════════════════

_WORD_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
              "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
              "eleven": 11, "twelve": 12}


def _parse_count(tok: str) -> str:
    """支持数字与英文单词数字（如 nine -> 9）。"""
    t = (tok or "").strip().lower()
    if t.isdigit():
        return str(int(t))
    return str(_WORD_NUM.get(t, t or ""))


def _extract_patent_conclusions(text: str) -> dict:
    """从第三方专利分析站（PharmaCompass/DrugPatentWatch/GreyB 等）文本中提取明确专利结论。

    返回 {} 表示无可信结论。可提取：US 专利数、核心专利号、最早到期日、最早仿制药进入时间。
    文本应合并 content + 全部 citation snippets（AnySearch 每次命中的站点不固定）。
    """
    if not text:
        return {}
    concl = {}

    # ── US 专利数：支持数字与英文单词 ──
    m = re.search(r"(one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+US drug patents?", text, re.I)
    if not m:
        m = re.search(r"(one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+US patents?", text, re.I)
    if not m:
        m = re.search(r"there are (one|two|three|four|five|six|seven|eight|nine|ten|\d+) patents protecting", text, re.I)
    if m:
        concl["us_patent_count"] = _parse_count(m.group(1))

    # ── 核心专利号（Orange Book 列出）："US Patent Number : 9796721" ──
    nums = re.findall(r"US Patent Number\s*[：:]\s*(\d{5,8})", text)
    if not nums:
        nums = re.findall(r"\bUS[- ]?(\d{7,8})\b", text)
    if nums:
        seen, uniq = set(), []
        for n in nums:
            if n not in seen:
                seen.add(n)
                uniq.append(n)
        concl["us_patent_numbers"] = uniq[:5]

    # ── 最早专利到期日（多格式）："Patent Expiration Date : 2036-07-01" ──
    dates = []
    # 精确的 Orange Book 到期字段
    for dm in re.finditer(r"Patent Expiration Date\s*[：:]\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2}|[A-Z][a-z]+ \d{1,2},? \d{4})", text, re.I):
        dates.append(dm.group(1))
    if not dates:
        for dm in re.finditer(r"(?:patent expir\w+|expiry|expires)\s*(?:on|date)?\s*[：:]\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2}|[A-Z][a-z]+ \d{1,2},? \d{4})", text, re.I):
            dates.append(dm.group(1))
    # ISO 日期统一排序取最早
    if dates:
        iso = []
        for d in dates:
            dm2 = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", d)
            if dm2:
                iso.append((dm2.group(1), dm2.group(2), dm2.group(3), d))
        if iso:
            iso.sort()
            concl["expiry"] = iso[0][3]  # 最早到期日
            concl["expiry_list"] = [x[3] for x in iso[:3]]

    # ── 最早仿制药进入时间 ──
    gm = re.search(r"earliest\s+(?:date\s+for\s+)?generic\s+entry\s+(?:will\s+be\s+)?([A-Z][a-z]+ \d{1,2}(?:,? \d{4})?|\d{4}[-/]\d{1,2}[-/]\d{1,2})", text, re.I)
    if not gm:
        gm = re.search(r"(?:earliest|first)\s+generic\s+entry\s*(?:on|date)?\s*[：:]?\s*([A-Z][a-z]+ \d{1,2}(?:,? \d{4})?|\d{4}[-/]\d{1,2}[-/]\d{1,2})", text, re.I)
    if gm:
        concl["generic_entry"] = gm.group(1)

    # ── 均未到期标记 ──
    if re.search(r"none expired|none have expired|not yet expired|haven.t expired", text, re.I):
        concl["none_expired"] = True
    return concl


def _build_patent_conclusion(concl: dict, src_name: str, src_url: str) -> dict:
    """用第三方专利分析站结论组装精简专利模块（fields + 短文本）。"""
    fields = []
    parts = [f"### 专利结论（{src_name}）"]

    count_txt = f"{concl.get('us_patent_count', '?')} 件 US 药品专利"
    if concl.get("none_expired"):
        count_txt += "，均未到期"
    fields.append({
        "key": "patent_summary", "label": "核心专利概况", "value": count_txt,
        "source": src_name, "sourceUrl": src_url, "confidence": 60,
    })
    parts.append(f"- **核心专利概况**: {count_txt}")

    if concl.get("expiry"):
        expiry_val = concl["expiry"]
        if concl.get("expiry_list") and len(concl["expiry_list"]) > 1:
            expiry_val += f"（另有 {', '.join(concl['expiry_list'][1:])}）"
        fields.append({
            "key": "compound_patent_expiry", "label": "最早专利到期日", "value": expiry_val,
            "source": src_name, "sourceUrl": src_url, "confidence": 60,
        })
        parts.append(f"- **最早专利到期日**: {expiry_val}")

    if concl.get("generic_entry"):
        fields.append({
            "key": "generic_entry_date", "label": "最早仿制药进入", "value": concl["generic_entry"],
            "source": src_name, "sourceUrl": src_url, "confidence": 55,
        })
        parts.append(f"- **最早仿制药进入**: {concl['generic_entry']}")

    if concl.get("us_patent_numbers"):
        nums_txt = ", ".join(concl["us_patent_numbers"])
        fields.append({
            "key": "compound_patent", "label": "核心专利号(Orange Book)", "value": nums_txt,
            "source": src_name, "sourceUrl": src_url, "confidence": 60,
        })
        parts.append(f"- **核心专利号**: {nums_txt}")

    parts.append(f"> 来源：{src_name}（第三方专利分析站，仅供参考；最终以 FDA Orange Book / 各国专利局登记为准）")
    return {"fields": fields, "text_parts": parts, "content": "\n".join(parts)}


async def _search_patents_direct(query: str, cas_number: str = "", en_name: str = "") -> "SearchResult":
    """专利模块：优先 AnySearch IP/专利垂直检索，提取第三方专利分析站的明确专利结论；
    失败则降级到 PubChem 专利 ID + 到期估算 + PubMed 补充（精简输出，不再罗列大段清单）。"""
    import asyncio
    search_term = cas_number or query
    # 专利分析站均为英文内容，检索用英文名命中率最高（query 为中文名时）
    en_query = en_name or query

    # 并行：AnySearch IP/专利垂直结论（双检索词合并为 1 次 batch_search，覆盖到期日与仿制药时间两方向）
    #        + PubChem 专利 ID + PubMed 文献
    ip_task = asyncio.create_task(asyncio.to_thread(
        anysearch_engine.anysearch_batch,
        [
            {"query": f"{en_query} Orange Book patent expiration date",
             "domain": "ip", "sub_domain": "ip.global",
             "sub_domain_params": {"type": "GlobalPatent", "keyword": en_query}, "max_results": 4},
            {"query": f"{en_query} drug patents generic entry expiry",
             "domain": "ip", "sub_domain": "ip.global",
             "sub_domain_params": {"type": "GlobalPatent", "keyword": en_query}, "max_results": 4},
        ],
    ))
    pc_task = asyncio.create_task(fetch_pubchem_patents(search_term))
    pm_task = asyncio.create_task(fetch_pubmed_patent_articles(query))
    ip_batch, patent_data, pubmed_text = await asyncio.gather(
        asyncio.wait_for(ip_task, timeout=12),
        asyncio.wait_for(pc_task, timeout=15),
        asyncio.wait_for(pm_task, timeout=10),
        return_exceptions=True,
    )
    if isinstance(ip_batch, Exception):
        ip1 = ip2 = ip_batch
    else:
        ip1 = ip_batch[0] if len(ip_batch) > 0 else None
        ip2 = ip_batch[1] if len(ip_batch) > 1 else None
    # 合并两个检索词的结果（取结论更完整的一个）
    ip_res = None
    for cand in (ip1, ip2):
        if isinstance(cand, Exception) or not getattr(cand, "success", False):
            continue
        if ip_res is None or len(getattr(cand, "content", "") or "") > len(getattr(ip_res, "content", "") or ""):
            ip_res = cand

    if isinstance(patent_data, Exception):
        patent_data = {"total": 0, "by_country": {}, "us_raw": []}
    if isinstance(pubmed_text, Exception):
        pubmed_text = ""

    # 优先：AnySearch 第三方专利分析站明确结论
    if not isinstance(ip_res, Exception) and getattr(ip_res, "success", False):
        ip_txt = (getattr(ip_res, "content", "") or "").strip()
        # AnySearch 每次命中的站点不固定（PharmaCompass/DrugPatentWatch/GreyB...），
        # 将 citations 的 snippet 一并纳入提取，提升结论完整度
        snips = []
        for c in getattr(ip_res, "citations", []) or []:
            s = getattr(c, "snippet", "") or ""
            if s and s not in snips:
                snips.append(s)
        ip_txt_full = ip_txt + "\n" + "\n".join(snips)
        concl = _extract_patent_conclusions(ip_txt_full)
        if concl:
            src_url = ""
            for c in getattr(ip_res, "citations", []) or []:
                if getattr(c, "source_url", None):
                    src_url = c.source_url
                    break
            built = _build_patent_conclusion(concl, ip_res.source_name or "第三方专利分析站", src_url)
            sr = SearchResult(
                success=True,
                content=built["content"],
                source_name=ip_res.source_name or "第三方专利分析站",
                citations=getattr(ip_res, "citations", []) or [],
            )
            sr._patent_fields = built["fields"]
            sr._patent_text_parts = built["text_parts"]
            return sr

    # 降级：PubChem 统计 + 到期估算（精简，去 Espacenet/CNIPA 噪音与长清单）
    result_data = build_patent_result(patent_data, search_term, pubmed_text)
    content = result_data.get("content", "")
    # 诊断 AnySearch 失败原因：额度耗尽(402/429)/网络/无结果，诚实标注而非假装结论
    ip_fail_reason = ""
    for cand in (ip1, ip2):
        if isinstance(cand, Exception):
            ip_fail_reason = f"{type(cand).__name__}"
            continue
        if not getattr(cand, "success", False):
            msg = (getattr(cand, "content", "") or "")[:200]
            if any(k in msg for k in ("402", "429", "Payment", "quota", "Quota", "rate limit")):
                ip_fail_reason = "第三方专利检索配额/额度暂不可用"
            elif not ip_fail_reason:
                ip_fail_reason = "第三方专利检索无结果或网络异常"
    if ip_fail_reason:
        warn = f"> ⚠️ {ip_fail_reason}：以下为 PubChem 收录的专利信息（非正式权利主张清单），请以 FDA Orange Book / 各国专利局登记为准。"
        content = warn + "\n\n" + content
        fields = result_data.get("fields", []) or []
        if not any(f.get("key") == "patent_network_warn" for f in fields):
            fields.insert(0, {
                "key": "patent_network_warn", "label": "检索状态",
                "value": f"{ip_fail_reason}，以下为 PubChem 收录信息",
                "source": "AnySearch", "sourceUrl": "", "confidence": 100,
            })
            result_data["fields"] = fields
    sr = SearchResult(
        success=True,
        content=content,
        source_name="PubChem / PubMed",
        citations=[],
    )
    sr._patent_fields = result_data.get("fields", [])
    sr._patent_text_parts = result_data.get("text_parts", []) or []
    return sr

# ─────────────────────────────────────────────────────────────────────────────
# 3) 并行调用各源 + 模块聚合
# ─────────────────────────────────────────────────────────────────────────────
async def _call_source(name: str, fn, query: str, sem: asyncio.Semaphore) -> "SearchResult":
    """调用单个底层检索函数，带超时与单源错误隔离。
    同步函数用 asyncio.to_thread 抛到线程池避免阻塞事件循环。"""
    async with sem:
        try:
            if asyncio.iscoroutinefunction(fn):
                coro = fn(query)
            else:
                coro = asyncio.to_thread(fn, query)
            return await asyncio.wait_for(
                coro, timeout=_SLOW_SOURCE_TIMEOUT.get(name, TIMEOUT_PER_SOURCE))
        except Exception as e:
            return SearchResult.empty(name, f"源调用失败: {e}")


async def _build_modules(valid: list, product_type: str) -> dict:
    """将各源结果组织为 module→{fields, text} 结构（Markdown 格式化 + 中英双语）。

    中文翻译：英文为主文本用 LLM 实时翻译（并行），失败降级术语表替换；
    中文文本不调用 LLM（避免浪费与误译）。
    """
    schema = RAW_DRUG_SCHEMA if product_type == "原料药" else EXCIPIENT_SCHEMA
    modules = {}
    for mod_name in schema:
        modules[mod_name] = {"fields": [], "text_parts": [], "text_parts_cn": []}

    fk2mod = {}
    for mod_name, field_defs in schema.items():
        for fk, fl in field_defs:
            fk2mod[fk] = mod_name

    # 第一遍：收集需要 LLM 翻译的英文文本。
    # 仅处理用户反馈翻译失效的三个模块（国际监管/临床试验/文献）对应源，
    # 并行 3 路 + 整体 18s 硬超时，失败自动降级术语表，绝不让翻译拖垮主流程。
    _TR_MODULES = {"国际监管情况", "临床试验", "文献与研究"}
    llm_reqs = []
    for source_key, r in valid:
        txt = (getattr(r, "content", "") or "").strip()
        if not txt or not _is_mostly_english(txt):
            continue
        if not any(m in _TR_MODULES for m in SOURCE_MODULES.get(source_key, [])):
            continue
        if len(txt) < 50 or len(txt) > 2500:
            continue
        llm_reqs.append((source_key, txt))

    llm_results = {}
    if llm_reqs:
        _sem = asyncio.Semaphore(3)

        async def _tr(item):
            sk, t = item
            async with _sem:
                return sk, await _translate_text_llm(t)

        tasks = [asyncio.create_task(_tr(it)) for it in llm_reqs]
        done, pending = await asyncio.wait(tasks, timeout=10)
        for t in done:
            try:
                sk, out = t.result()
            except Exception:
                continue
            if out:
                llm_results[sk] = out
        for t in pending:
            t.cancel()

    for source_key, r in valid:
        txt = getattr(r, "content", "") or ""
        src_name = r.source_name or source_key
        # 国内登记源统一显示名（cde 复用 AnySearch 通道，原名无意义）
        if source_key in ("cde", "yaozhi"):
            src_name = "国内登记检索"
        src_url = ""
        for c in getattr(r, "citations", []) or []:
            if getattr(c, "source_url", None):
                src_url = c.source_url
                break

        # 字段提取
        if source_key in EXTRACTORS:
            for ef in EXTRACTORS[source_key](txt, src_url):
                target_mod = fk2mod.get(ef["key"], "产品基本信息")
                existing = {f["key"] for f in modules[target_mod]["fields"]}
                if ef["key"] not in existing:
                    modules[target_mod]["fields"].append(ef)

        # 文本归入模块（Markdown 格式化 + 中文翻译）
        txt_clean = txt.strip()
        if txt_clean:
            # 国内登记（cde/yaozhi）为结论式检索：只保留含结论关键词的行，
            # 纯新闻流（研发动态/招聘/股市等）直接丢弃，避免"垃圾全扔给用户"
            if source_key in ("cde", "yaozhi"):
                txt_clean = _filter_cn_conclusion(txt_clean)
                txt_clean = _compact_text(txt_clean, max_chars=400, max_lines=6)
                # 结论文本附加来源引用（原过滤会剥掉"[来源](url)"行，这里重新补上；
                # 无 URL 时也标注来源名，保证用户可溯源）
                if txt_clean:
                    if src_url:
                        txt_clean = f"{txt_clean}\n\n> 来源：[{src_name}]({src_url})"
                    else:
                        txt_clean = f"{txt_clean}\n\n> 来源：{src_name}（AnySearch 汇总）"
            snippet = _fmt_markdown(txt_clean, src_name)
            # 中文翻译：英文为主 → LLM 实时翻译；中文 → 术语表（通常无变化则不显示按钮）
            if _is_mostly_english(txt_clean):
                cn_txt = llm_results.get(source_key, "") or _translate_bio_text(txt_clean)
            else:
                cn_txt = _translate_bio_text(txt_clean)
            snippet_cn = ""
            if cn_txt and cn_txt != txt_clean:
                snippet_cn = _fmt_markdown(cn_txt, f"{src_name}（中文翻译）")

            for mod in SOURCE_MODULES.get(source_key, ["产品基本信息"]):
                if mod not in modules:
                    continue
                # 归一化去重：同一来源新闻的截断变体（含/不含空格）只保留一条
                norm_s = re.sub(r"\s+", "", snippet)
                if any(norm_s in re.sub(r"\s+", "", ex) or re.sub(r"\s+", "", ex) in norm_s
                       for ex in modules[mod]["text_parts"]):
                    continue
                modules[mod]["text_parts"].append(snippet)
                if snippet_cn:
                    modules[mod]["text_parts_cn"].append(snippet_cn)

    # 剔除空模块
    return {k: {"fields": v["fields"], "text_parts": v["text_parts"], "text_parts_cn": v.get("text_parts_cn", [])}
            for k, v in modules.items() if v["fields"] or v["text_parts"]}


def _merge_citations(results) -> list:
    """合并各源 citations，按 (title, url, source) 去重。"""
    seen = set()
    merged = []
    for name, r in results:
        for c in getattr(r, "citations", []) or []:
            d = c.to_dict() if hasattr(c, "to_dict") else dict(c)
            d.setdefault("source", r.source_name)
            key = (str(d.get("title","")).strip().lower(),
                   str(d.get("url","")).strip().lower(),
                   str(d.get("source","")).strip().lower())
            if key in seen: continue
            seen.add(key)
            d["source_name"] = r.source_name or name
            merged.append(d)
    return merged


# 国内登记强结论词（组合词，避免"进口/CDE/登记"等泛词误保留导航页）
_CN_CONCLUSION_KW = ("批准上市", "获批上市", "附条件批准", "获准上市", "获批进口",
                     "参比制剂", "受理号", "已在中国获得", "国家药监局", "NMPA",
                     "获国家药品监督管理局", "取得药品注册证", "获得上市批准")
# 导航/供需/索引页/新闻特征词，命中即整行丢弃（摩熵"产业供需"、医药魔方 ByDrug 等）
_CN_NOISE_KW = ("产业供需", "求购", "招聘", "已收录", "最新供需", "药品标准WS", "导航",
                "一站式", "药物情报", "收录", "资讯动态", "最新进展", "股市", "概念股",
                "大涨", "涨停", "融资", "管线进展", "股价", "医药魔方", "ByDrug", "NextPharma",
                "数据库", "登录", "药品详情", "研发管线", "临床进度", "新闻动态", "在研适应症",
                "药物靶点", "药物类型", "小分子化药", "新闻资讯", "行业资讯", "化学原料药",
                "研发", "临床", "靶点", "适应症", "别名", "登录", "更新时间",
                # NMPA 官网导航/页脚文本（AnySearch 常把整页菜单文本并入正文）
                "机构概况", "政务公开", "无障碍", "关怀版", "返回手机版", "领导信息",
                "内设机构", "直属单位", "政府信息公开专栏", "公告通告", "化妆品监管",
                "中国药监App", "地方药监", "英文版", "简体中文", "繁体中文",
                "中药品种保护", "政务服务事项", "互动交流",
                # 美国/FDA 相关内容不得混入"国内登记情况"
                "FDA", "获FDA", "美国FDA", "美国批准", "美国上市", "美国食品药品",
                "Calquence", "calquence", "美国食品药品监督管理局", "FDA批准", "获美国")
# 命中即整行丢弃的美国/英文内容模式（国内登记模块应只含中国监管信息）
_CN_US_PATTERNS = ("FDA", "获FDA", "Calquence", "美国FDA", "美国批准", "美国上市",
                   "美国食品药品", "FDA批准", "获美国")


def _filter_cn_conclusion(text: str) -> str:
    """国内登记结论过滤：只保留含强结论词的中文行，剔除导航/供需/股市/新闻索引及美国/FDA/英文噪音。"""
    if not text:
        return ""
    kept = []
    for ln in text.splitlines():
        if any(k in ln for k in _CN_NOISE_KW):
            continue
        # 英文为主的行（多为 FDA/US 新闻）直接丢弃
        letters = [ch for ch in ln if ch.isalpha()]
        if letters:
            ascii_n = sum(1 for ch in letters if ord(ch) < 128)
            if ascii_n / len(letters) > 0.6:
                continue
        if any(p in ln for p in _CN_US_PATTERNS):
            continue
        if any(k in ln for k in _CN_CONCLUSION_KW):
            kept.append(ln)
    if not kept:
        return ""
    return "\n".join(kept)


def _compact_text(text: str, max_chars: int = 350, max_lines: int = 8) -> str:
    """压缩长文本为要点式短文本：保留关键结论行，截断超长行，去重复空行。

    用于 text_parts 展示，避免"大段长文本罗列"。
    """
    if not text:
        return ""
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return ""
    # 保留含关键结论词的行优先，其余按原顺序补足
    key_terms = ("批准", "上市", "到期", "专利", "受理", "参比", "expir", "patent", "approved",
                 "generic", "Orange Book", "核心", "最早", "均未")
    scored = [(sum(t.lower() in ln.lower() for t in key_terms), i, ln) for i, ln in enumerate(lines)]
    scored.sort(key=lambda x: (-x[0], x[1]))
    out, total = [], 0
    for _, _, ln in scored:
        if len(out) >= max_lines:
            break
        if total + len(ln) > max_chars and out:
            break
        out.append(ln[:200])
        total += len(ln)
    result = "\n".join(out).strip()
    if len(result) > max_chars:
        result = result[:max_chars].rsplit("\n", 1)[0].rstrip() + "…"
    return result or lines[0][:max_chars] + "…"


def _build_content_text(modules: dict) -> str:
    """按模块拼接可读文本（供展示/LLM消费）。text_parts 统一压缩，避免大段长文本。"""
    parts = []
    for mod_name, mod_data in modules.items():
        lines = [f"【{mod_name}】"]
        for f in mod_data.get("fields", []):
            lines.append(f"  字段「{f['label']}」: {f['value']}  (来源: {f['source']}, 置信度: {f['confidence']})")
        if mod_data.get("text_parts"):
            compact = [_compact_text(p) for p in mod_data["text_parts"]]
            compact = [p for p in compact if p]
            if compact:
                lines.append("\n" + "\n\n".join(compact))
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


async def _aggregate(primary: str, product_type: str, entity_info: dict) -> str:
    """并行检索 → 构建模块化字段 → 专利兜底 → 返回 JSON 标记格式（供 main.py 解析）。"""
    excluded = EXCIPIENT_ONLY | API_ONLY
    sources = [k for k in SOURCE_FUNCS if k not in excluded]
    if product_type == "药用辅料":
        sources.extend(sorted(EXCIPIENT_ONLY))
    else:
        sources.extend(sorted(API_ONLY))

    # ── 专利模块：在源检索之前启动后台任务（与源检索并行重叠，
    # 专利各子调用已有独立超时，不会因外部挂起拖垮 60s 整体预算）──
    pat_task = None
    try:
        pat_cas = entity_info.get("cas_number", "")
        pat_en = entity_info.get("drug_name_en") or entity_info.get("english_name") or ""
        pat_task = asyncio.create_task(_search_patents_direct(primary, pat_cas, en_name=pat_en))
    except Exception:
        pat_task = None

    sem = asyncio.Semaphore(8)
    tasks = [_call_source(name, SOURCE_FUNCS[name], primary, sem) for name in sources]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    valid = [(n, r) for n, r in zip(sources, results)
             if not isinstance(r, Exception) and getattr(r, "success", False)
             and getattr(r, "content", "").strip()]

    # 全失败兜底
    if not valid:
        try:
            fb = await asyncio.to_thread(anysearch_engine.anysearch_vertical, primary, domain="health", max_results=8)
            if "No results" not in getattr(fb, "content", ""):
                fb_c = [c.to_dict() if hasattr(c, "to_dict") else dict(c) for c in getattr(fb, "citations", [])]
                return (f"__MODULES_JSON__: {json.dumps({'产品基本信息':{'fields':[],'text_parts':[fb.content]}}, ensure_ascii=False)}\n"
                        f"__CITATIONS__: {json.dumps(fb_c, ensure_ascii=False)}\n"
                        f"__ENTITY__: {json.dumps(entity_info, ensure_ascii=False)}")
        except Exception:
            pass
        return (f"__MODULES_JSON__: {{}}\n"
                f"__CITATIONS__: []\n"
                f"__ENTITY__: {json.dumps(entity_info, ensure_ascii=False)}")

    # 注入实体解析基础字段到模块
    modules = await _build_modules(valid, product_type)

    # 国内登记情况：由提取字段生成一句"观点式"结论置于文本首行（用户要求"有观点"）。
    # 注：cn_registration（国内注册状态）schema 归属"产品基本信息"模块，此处跨模块取用。
    _cn_mod = modules.get("国内登记情况")
    _cn_src = modules.get("产品基本信息", {})
    _cn_field = next((f for f in _cn_src.get("fields", [])
                      if f.get("key") == "cn_registration" and f.get("value")), None)
    if _cn_mod:
        # 观点式结论：优先用提取的国内注册状态；无明确字段但有正文时给兜底说明
        _concl = None
        if _cn_field:
            _concl = f"**结论**：{_cn_field['value']}"
        elif any(p.strip() for p in _cn_mod.get("text_parts", [])):
            _concl = "**结论**：国内登记检索暂未返回明确的获批上市结论，以下为检索到的相关登记/受理信息。"
        if _concl:
            for f in _cn_mod.get("fields", []):
                if f.get("key") in ("rld_reference", "cde_generics") and f.get("value"):
                    _concl += f"；{f['label']}：{f['value']}"
            if not any(_concl in p for p in _cn_mod["text_parts"]):
                _cn_mod["text_parts"].insert(0, _concl)

    bi = modules.get("产品基本信息", {"fields": [], "text_parts": [], "text_parts_cn": []})
    existing_keys = {f["key"] for f in bi["fields"]}
    for k, lbl, src in [("drug_name_cn", "中文名", "LLM实体解析"),
                         ("drug_name_en", "英文名", "LLM实体解析"),
                         ("cas_number", "CAS号", "PubChem验证"),
                         ("product_type", "产品类型", "LLM实体解析")]:
        v = entity_info.get(k)
        if v and k not in existing_keys:
            bi["fields"].insert(0, {"key": k, "label": lbl, "value": v, "source": src, "sourceUrl": "", "confidence": CONFIDENCE["entity_info"]})
            existing_keys.add(k)
    modules["产品基本信息"] = bi

    # ── 专利模块：优先 AnySearch IP/专利垂直结论；失败降级 PubChem 统计 ──
    try:
        pat = await pat_task if pat_task else None
        if getattr(pat, "success", False) and getattr(pat, "content", "").strip():
            txt = pat.content.strip()
            # 结论路径：使用精简 text_parts（短列表），不再整块大段 Markdown，也不重复加源标题
            text_parts = getattr(pat, "_patent_text_parts", None)
            if text_parts:
                parts = list(text_parts)
            else:
                parts = [_compact_text(_fmt_markdown(txt, pat.source_name or "PubChem / PubMed"))]
            modules["专利信息"] = {"fields": list(getattr(pat, "_patent_fields", [])),
                                    "text_parts": parts,
                                    "text_parts_cn": []}
            # 到期字段未检索到时填"暂未搜索到"，前端不再空显示"—"
            _patent_mod = modules["专利信息"]
            _have_keys = {f["key"] for f in _patent_mod["fields"]}
            for _fk, _fl in (("compound_patent_expiry", "专利到期时间"),
                             ("crystal_patent_expiry", "晶型专利到期"),
                             ("formulation_patent_expiry", "制剂/用途专利到期"),
                             ("process_patent_expiry", "合成方法专利到期")):
                if _fk not in _have_keys:
                    _patent_mod["fields"].append({
                        "key": _fk, "label": _fl, "value": "暂未搜索到",
                        "source": pat.source_name or "专利检索", "sourceUrl": "", "confidence": 50,
                    })
                    _have_keys.add(_fk)
            # 中文翻译：专利文本保留术语表替换（模块构建阶段的 LLM 翻译已覆盖用户反馈的三个模块）
            cn_txt = _translate_bio_text(txt)
            if cn_txt and cn_txt != txt and len(cn_txt) <= 600:
                _patent_mod["text_parts_cn"].append(_fmt_markdown(cn_txt, f"{pat.source_name or '专利检索'}（中文翻译）"))
            valid.append(("_pubchem_patents", pat))
    except Exception:
        pass

    # 国内登记情况：cde/yaozhi 均无结论时，显式标注"未查到"而非缺失模块/导航页
    if product_type != "药用辅料" and "国内登记情况" not in modules:
        modules["国内登记情况"] = {
            "fields": [{
                "key": "cn_registration", "label": "国内注册状态",
                "value": "未查到明确的国内登记/批准结论",
                "source": "CDE/药智网检索", "sourceUrl": "", "confidence": 30,
            }],
            "text_parts": ["未检索到明确的国内登记、批准上市或参比制剂结论（可能是早期申报/未公开，或网络源未覆盖）。"],
            "text_parts_cn": [],
        }

    # 剔除空模块
    modules = {k: v for k, v in modules.items() if v["fields"] or v["text_parts"]}

    citations = _merge_citations(valid)
    content_text = _build_content_text(modules)

    return (f"[原辅料基本信息速查]\n{content_text}\n\n"
            f"__MODULES_JSON__: {json.dumps(modules, ensure_ascii=False)}\n"
            f"__CITATIONS__: {json.dumps(citations, ensure_ascii=False)}\n"
            f"__ENTITY__: {json.dumps(entity_info, ensure_ascii=False)}")


# ─────────────────────────────────────────────────────────────────────────────
# 对外工具入口
# ─────────────────────────────────────────────────────────────────────────────
@tool
async def excipient_basic_info_tool(query: str) -> str:
    """原辅料基本信息综合速查工具：当用户询问某个【药用辅料 / 原料药 / 药品】的一站式基础信息时优先使用。
    并行检索 PubChem、FDA（openFDA / IIG / DailyMed / FAERS / UNII）、ClinicalTrials.gov、PubMed、
    Open Targets、ChEMBL、RxNorm 等官方 API，以及 DrugBank/EMA/PMDA/CDE 等网络检索兜底源；
    专利信息经 PubChem 专利直连 + Espacenet/CNIPA 网络交叉引用专项路径提供；
    各源数据成色不同（官方 API 一手可信，网络检索仅供参考），结果已做来源标注，请结合溯源判断；
    覆盖字段：分子式/分子量/CAS/UNII/化学结构、功能分类（辅料）/FDA IIG 最大用量、作用机制/分子靶点、
    适应症/FDA 适应症/黑框警告、Top 不良反应、临床试验、专利（美国/中国）、中日审评信息、化合物生物活性等。
    输入可以是中文名、英文名、商品名或 CAS 号；工具会自动完成实体解析与 CAS 校验。"""
    try:
        async def _run():
            expanded = await _expand_keywords(query)
            product_type = _classify_product_type(query, expanded)
            primary = expanded["englishName"] or query
            cas = expanded.get("casNumber", "")

            # PubChem 名称解析 与 CAS 校验互相独立，并行执行（省 ~5s）
            if cas:
                (_cname, _rcas), _cas_ok = await asyncio.gather(
                    _pubchem_resolve(primary), _verify_cas(cas), return_exceptions=True)
                canonical_name = _cname if not isinstance(_cname, Exception) else None
                resolved_cas = _rcas if not isinstance(_rcas, Exception) else None
                cas_ok = bool(_cas_ok) and not isinstance(_cas_ok, Exception)
            else:
                canonical_name, resolved_cas = await _pubchem_resolve(primary)
                cas_ok = False
            if canonical_name:
                primary = canonical_name
            if cas and cas_ok:
                final_cas = cas
            elif resolved_cas:
                final_cas = resolved_cas
            else:
                final_cas = ""
            search_term = primary

            # 构建 entity_info dict（供 main.py 解析后传给前端 entity 卡片）
            entity_info = {
                "drug_name_cn": query,
                "drug_name_en": primary,
                "cas_number": final_cas or "",
                "product_type": product_type,
            }

            return await _aggregate(search_term, product_type, entity_info)

        return await asyncio.wait_for(_run(), timeout=TIMEOUT_TOTAL)
    except Exception as e:
        # 错误隔离：任何异常都返回友好占位，不向上抛出，不影响其他工具
        import logging, traceback
        logger = logging.getLogger(__name__)
        logger.error(f"[excipient_basic_info] 查询「{query}」异常: {e}\n{traceback.format_exc()}")
        return (
            f"[原辅料基本信息速查] 查询「{query}」时发生异常：{e}。"
            "（该子模块已隔离，不影响其他数据源与整体应答）\n\n__CITATIONS__: []"
        )
