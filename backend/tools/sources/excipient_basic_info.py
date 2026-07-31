"""原辅料基本信息速查工具（迁移自 jiansuo3 检索内核，路线 B）。

设计目标（策略不能丢）：
  1. 关键词扩展：LLM 把中文名/商品名/CAS 解析为 englishName + casNumber + productType
  2. 实体解析 + CAS 验证：用 PubChem REST 二次验证 LLM 给的 CAS，不信任 LLM 的 CAS
  3. 多源并行：并行调用 19 个数据源工具的底层 _search_xxx 函数
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
    "espacenet": ["专利信息"], "cnipa": ["专利信息"],
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
    """药智网药品注册/上市/集采/销售信息搜索。jiansuo3 中原有 9 子工具（MCP），
    当前 MCP 客户端不可用，以 site:yaozh.com 搜索作为兜底。"""
    try:
        result = await asyncio.to_thread(
            anysearch_engine.anysearch_vertical,
            f"{query} site:yaozh.com",
            domain="health",
            max_results=8,
        )
        if result.success and "No results" not in result.content:
            result.source_name = "药智网"
            return result
    except Exception:
        pass
    return SearchResult.empty("药智网", "搜索无结果（如启用了药智MCP客户端将自动升级为9子工具检索）")


# 数据源 → 置信度（API 直连=高；搜索兜底=低；与 jiansuo3 三级置信度一致）
# 键名与 SOURCE_FUNCS 的源 key 保持一致（小写）
CONFIDENCE = {
    "pubchem": 100,
    "fda_unii": 100,
    "fda_iig": 100,
    "fda_drugs": 100,
    "ema": 95,
    "dailymed": 90,
    "fda_faers": 90,
    "drugbank": 85,
    "wikipedia": 80,
    "clinicaltrials": 80,
    "pubmed": 75,
    "espacenet": 65,
    "cde":       80,
    "pmda":      80,
    "chembl":    95,
    "cnipa":     70,
    "drugscom":  80,
    "yaozhi":    70,
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
    "espacenet": _search_espacenet,
    "fda_iig": _search_fda_iig,
    "clinicaltrials": _search_clinicaltrials,
    # jiansuo3 新增 5 源
    "cde": _search_cde,
    "pmda": _search_pmda,
    "chembl": _search_chembl,
    "cnipa": _search_cnipa,
    "drugscom": _search_drugscom,
    "yaozhi": _search_yaozhi,
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

TIMEOUT_PER_SOURCE = 30          # 单源超时
TIMEOUT_TOTAL = 60               # 整体超时（错误隔离硬上限）
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
        resp = await llm.ainvoke([
            SystemMessage(content=system),
            HumanMessage(content=f"产品名称：{query}"),
        ])
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
    m = re.search(r"ChEMBL ID:\s*(.+)", text)
    if m:
        fields.append({"key":"chembl_id","label":"ChEMBL ID","value":m.group(1).strip(),
                       "source":"ChEMBL","sourceUrl":src_url,"confidence":95})
    return fields


EXTRACTORS = {"pubchem":_extract_pubchem_fields,"fda_unii":_extract_unii_fields,"chembl":_extract_chembl_fields}


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



# ═════════════════════════════════════════════════════════════════════════════
# PubChem 直连专利搜索（不依赖 AnySearch）+ 专利到期时间估算
# ═════════════════════════════════════════════════════════════════════════════

async def _search_patents_direct(query: str, cas_number: str = "") -> "SearchResult":
    """专利模块：PubChem 专利 ID + 到期日估算 + PubMed 补充文献。"""
    import asyncio
    search_term = cas_number or query

    # 并行：PubChem 专利 ID + PubMed 文献
    pc_task = asyncio.create_task(fetch_pubchem_patents(search_term))
    pm_task = asyncio.create_task(fetch_pubmed_patent_articles(query))
    patent_data, pubmed_text = await asyncio.gather(pc_task, pm_task, return_exceptions=True)

    if isinstance(patent_data, Exception):
        patent_data = {"total": 0, "by_country": {}, "us_raw": []}
    if isinstance(pubmed_text, Exception):
        pubmed_text = ""

    result_data = build_patent_result(patent_data, search_term, pubmed_text)
    content = result_data.get("content", "")

    sr = SearchResult(
        success=True,
        content=content,
        source_name="PubChem / PubMed",
        citations=[],
    )

    # 把结构化字段挂到 SearchResult 上供 _build_modules 使用
    sr._patent_fields = result_data.get("fields", [])
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
            return await asyncio.wait_for(coro, timeout=TIMEOUT_PER_SOURCE)
        except Exception as e:
            return SearchResult.empty(name, f"源调用失败: {e}")


def _build_modules(valid: list, product_type: str) -> dict:
    """将各源结果组织为 module→{fields, text} 结构（Markdown 格式化 + 中英双语）。"""
    schema = RAW_DRUG_SCHEMA if product_type == "原料药" else EXCIPIENT_SCHEMA
    modules = {}
    for mod_name in schema:
        modules[mod_name] = {"fields": [], "text_parts": [], "text_parts_cn": []}

    fk2mod = {}
    for mod_name, field_defs in schema.items():
        for fk, fl in field_defs:
            fk2mod[fk] = mod_name

    for source_key, r in valid:
        txt = getattr(r, "content", "") or ""
        src_name = r.source_name or source_key
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
            snippet = _fmt_markdown(txt_clean, src_name)
            snippet_cn = _translate_bio_text(txt_clean)
            if snippet_cn and snippet_cn != txt_clean:
                snippet_cn = _fmt_markdown(snippet_cn, f"{src_name}（中文翻译）")
            else:
                snippet_cn = ""

            for mod in SOURCE_MODULES.get(source_key, ["产品基本信息"]):
                if mod in modules:
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


def _build_content_text(modules: dict) -> str:
    """按模块拼接可读文本（供展示/LLM消费）。"""
    parts = []
    for mod_name, mod_data in modules.items():
        lines = [f"【{mod_name}】"]
        for f in mod_data.get("fields", []):
            lines.append(f"  字段「{f['label']}」: {f['value']}  (来源: {f['source']}, 置信度: {f['confidence']})")
        if mod_data.get("text_parts"):
            lines.append("\n" + "\n\n".join(mod_data["text_parts"]))
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
    modules = _build_modules(valid, product_type)
    bi = modules.get("产品基本信息", {"fields": [], "text_parts": [], "text_parts_cn": []})
    existing_keys = {f["key"] for f in bi["fields"]}
    for k, lbl, src in [("drug_name_cn", "中文名", "LLM实体解析"),
                         ("drug_name_en", "英文名", "LLM实体解析"),
                         ("cas_number", "CAS号", "PubChem验证"),
                         ("product_type", "产品类型", "LLM实体解析")]:
        v = entity_info.get(k)
        if v and k not in existing_keys:
            bi["fields"].insert(0, {"key": k, "label": lbl, "value": v, "source": src, "sourceUrl": "", "confidence": 85})
            existing_keys.add(k)
    modules["产品基本信息"] = bi

    # ── 专利模块：PubChem 直连 API + 到期估算（替代 AnySearch）──
    try:
        pat_cas = entity_info.get("cas_number", "")
        pat = await _search_patents_direct(primary, pat_cas)
        if getattr(pat, "success", False) and getattr(pat, "content", "").strip():
            txt = pat.content.strip()
            markdown_txt = _fmt_markdown(txt, "PubChem / PubMed")
            modules["专利信息"] = {"fields": getattr(pat, "_patent_fields", []),
                                    "text_parts": [markdown_txt],
                                    "text_parts_cn": []}
            cn_txt = _translate_bio_text(txt)
            if cn_txt and cn_txt != txt:
                modules["专利信息"]["text_parts_cn"].append(_fmt_markdown(cn_txt, "PubChem / PubMed（中文翻译）"))
            valid.append(("_pubchem_patents", pat))
    except Exception:
        pass

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
    """原辅料基本信息速查工具：当用户询问某个【药用辅料 / 原料药 / 药品】的一站式基本信息时优先使用。
    自动并行检索 PubChem、DrugBank、FDA（openFDA / IIG / DailyMed / FAERS / UNII）、EMA、Wikipedia、
    PubMed、ClinicalTrials.gov、Espacenet/CNIPA、PMDA、CDE、Drugs.com、ChEMBL、药智网等 19 个数据源，
    并按置信度聚合去重。
    覆盖字段：分子式/分子量/CAS/UNII/化学结构、功能分类（辅料）/FDA IIG 最大用量、作用机制/分子靶点、
    适应症/FDA 适应症/黑框警告、Top 不良反应、临床试验、专利（美国/中国）、中日审评信息、化合物生物活性等。
    输入可以是中文名、英文名、商品名或 CAS 号；工具会自动完成实体解析与 CAS 校验。"""
    try:
        async def _run():
            expanded = await _expand_keywords(query)
            product_type = _classify_product_type(query, expanded)
            primary = expanded["englishName"] or query
            cas = expanded.get("casNumber", "")

            canonical_name, resolved_cas = await _pubchem_resolve(primary)
            if canonical_name:
                primary = canonical_name
            if cas and await _verify_cas(cas):
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
