"""原辅料基本信息速查工具（迁移自 jiansuo3 检索内核，路线 B）。

设计目标（策略不能丢）：
  1. 关键词扩展：LLM 把中文名/商品名/CAS 解析为 englishName + casNumber + productType
  2. 实体解析 + CAS 验证：用 PubChem REST 二次验证 LLM 给的 CAS，不信任 LLM 的 CAS
  3. 多源并行：并行调用 12 个现有数据源工具的底层 _search_xxx 函数
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

settings = get_settings()

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
}

# 每个数据源对应的底层检索函数（key 即置信度/路由使用的源标识）
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
}

# 与产品类型绑定的专属源
EXCIPIENT_ONLY = "fda_iig"
API_ONLY = "clinicaltrials"

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


# ─────────────────────────────────────────────────────────────────────────────
# 3) 并行调用各源 + 聚合
# ─────────────────────────────────────────────────────────────────────────────
async def _call_source(name: str, fn, query: str, sem: asyncio.Semaphore) -> "SearchResult":
    """调用单个底层检索函数，带超时与单源错误隔离。"""
    async with sem:
        try:
            return await asyncio.wait_for(fn(query), timeout=TIMEOUT_PER_SOURCE)
        except Exception as e:
            return SearchResult.empty(name, f"源调用失败: {e}")


def _merge_citations(results) -> list:
    """合并各源 citations，按 (title, url, source) 去重，返回统一列表；用源名溯源。
    results: list of (name, SearchResult)。"""
    seen = set()
    merged = []
    for name, r in results:
        for c in getattr(r, "citations", []) or []:
            d = c.to_dict() if hasattr(c, "to_dict") else dict(c)
            d.setdefault("source", r.source_name)  # 引用溯源到具体数据源
            key = (
                str(d.get("title", "")).strip().lower(),
                str(d.get("url", "")).strip().lower(),
                str(d.get("source", "")).strip().lower(),
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(d)
    return merged


def _build_content(results) -> str:
    """按置信度从高到低拼接各源内容。results: list of (name, SearchResult)。"""
    ranked = sorted(results, key=lambda x: CONFIDENCE.get(x[0], 50), reverse=True)
    parts = []
    for name, r in ranked:
        if not getattr(r, "content", "").strip():
            continue
        conf = CONFIDENCE.get(name, 50)
        parts.append(f"【{r.source_name}（置信度 {conf}）】\n{r.content.strip()}")
    return "\n\n".join(parts)


async def _aggregate(primary: str, product_type: str, entity_summary: str = "") -> str:
    """并行检索多源 → 聚合 → 返回统一格式字符串（[源名]内容\\n\\n__citations__:JSON）。"""
    # —— 产品类型路由（确定性二选一）——
    sources = [k for k in SOURCE_FUNCS if k not in (EXCIPIENT_ONLY, API_ONLY)]  # 排除专属源，路由时再按类型添加
    if product_type == "药用辅料":
        sources.append(EXCIPIENT_ONLY)          # 辅料加 IIG，跳过 clinicaltrials
    else:
        sources.append(API_ONLY)                # 原料药（含默认）加 clinicaltrials，跳过 IIG

    sem = asyncio.Semaphore(8)
    tasks = [_call_source(name, SOURCE_FUNCS[name], primary, sem) for name in sources]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    valid = []
    for name, r in zip(sources, results):
        if isinstance(r, Exception):
            continue
        if getattr(r, "success", False) and getattr(r, "content", "").strip():
            valid.append((name, r))

    # 全失败 → AnySearch 兜底（复用现有引擎，三层降级末层）
    if not valid:
        try:
            fb = await asyncio.to_thread(
                anysearch_engine.anysearch_vertical, primary, domain="health", max_results=8
            )
            if "No results" not in fb.content:
                content = f"【anysearch_fallback（置信度 60）】\n{fb.content.strip()}"
                citations = [c.to_dict() for c in fb.citations]
                return f"[原辅料基本信息速查] {content}\n\n__citations__: {json.dumps(citations, ensure_ascii=False)}"
        except Exception:
            pass
        return (
            f"[原辅料基本信息速查] 未检索到「{primary}」的相关信息。"
            "（已并行检索 PubChem/Wikipedia/EMA/FAERS/UNII/DrugBank/FDA/DailyMed/PubMed/"
            "ClinicalTrials/IIG/Espacenet 共 12 个数据源并启用 AnySearch 兜底，均无结果）\n\n"
            "__citations__: []"
        )

    content = _build_content(valid)
    if entity_summary:
        content = f"{entity_summary}\n\n{content}"
    citations = _merge_citations(valid)
    return f"[原辅料基本信息速查] {content}\n\n__citations__: {json.dumps(citations, ensure_ascii=False)}"


# ─────────────────────────────────────────────────────────────────────────────
# 对外工具入口
# ─────────────────────────────────────────────────────────────────────────────
@tool
async def excipient_basic_info_tool(query: str) -> str:
    """原辅料基本信息速查工具：当用户询问某个【药用辅料 / 原料药 / 药品】的一站式基本信息时优先使用。
    自动并行检索 PubChem、DrugBank、FDA（openFDA / IIG / DailyMed）、EMA、Wikipedia、PubMed、
    ClinicalTrials.gov、FDA FAERS、FDA UNII、Espacenet 等 12 个数据源，并按置信度聚合去重。
    覆盖字段：分子式/分子量/CAS/UNII/化学结构、功能分类（辅料）/FDA IIG 最大用量、作用机制/分子靶点、
    适应症/FDA 适应症/黑框警告、Top 不良反应、临床试验、专利等。
    输入可以是中文名、英文名、商品名或 CAS 号；工具会自动完成实体解析与 CAS 校验。"""
    try:
        async def _run():
            expanded = await _expand_keywords(query)
            product_type = _classify_product_type(query, expanded)  # 确定性路由兜底
            primary = expanded["englishName"] or query
            cas = expanded.get("casNumber", "")

            # 不信任 LLM 的 CAS：用 PubChem 二次验证/纠正（仅用于实体解析章节展示，
            # 不拼回检索查询，避免 "Name CAS" 组合干扰 FDA IIG 等数据源的精确匹配）
            canonical_name, resolved_cas = await _pubchem_resolve(primary)
            if canonical_name:
                primary = canonical_name
            if cas and await _verify_cas(cas):
                final_cas = cas                      # LLM 给的 CAS 通过验证
            elif resolved_cas:
                final_cas = resolved_cas             # 用 PubChem 解析出的真实 CAS
            else:
                final_cas = ""
            search_term = primary                    # 始终用规范英文名检索各源（CAS 仅展示/验证）

            # 实体解析与 CAS 验证章节（策略2：在输出中可见，便于核对，不信任 LLM 的 CAS）
            entity_lines = [
                "【实体解析与CAS验证】",
                f"查询词: {query}",
                f"规范英文名: {primary}",
                f"产品类型(路由): {product_type}",
            ]
            if final_cas:
                if cas and final_cas == cas:
                    entity_lines.append(f"CAS号: {final_cas}（LLM给出，已通过PubChem验证）")
                else:
                    entity_lines.append(f"CAS号: {final_cas}（由PubChem解析确认）")
            else:
                entity_lines.append("CAS号: 未能从PubChem解析/验证")
            entity_summary = "\n".join(entity_lines)

            return await _aggregate(search_term, product_type, entity_summary)

        return await asyncio.wait_for(_run(), timeout=TIMEOUT_TOTAL)
    except Exception as e:
        # 错误隔离：任何异常都返回友好占位，不向上抛出，不影响其他工具
        return (
            f"[原辅料基本信息速查] 查询「{query}」时发生异常：{e}。"
            "（该子模块已隔离，不影响其他数据源与整体应答）\n\n__citations__: []"
        )
