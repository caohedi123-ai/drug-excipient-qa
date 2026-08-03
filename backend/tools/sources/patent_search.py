"""
专利搜索模块：PubChem 直连 API（不依赖 AnySearch）+ 专利到期时间估算。
支持根据 US 专利号序列估算申请年和 20 年到期日。
"""

import re
import httpx
import xml.etree.ElementTree as ET

# ── US 专利号 → 授权年（近似）映射 ──
# USPTO 专利号是连续的，不同号段对应不同授权年代
_US_PATENT_GRANT_YEAR = [
    (5000000, 1991), (5500000, 1995), (6000000, 1999),
    (6500000, 2001), (7000000, 2006), (7500000, 2009),
    (8000000, 2011), (8500000, 2013), (9000000, 2015),
    (9500000, 2016), (10000000, 2018), (10500000, 2020),
    (11000000, 2021), (11500000, 2023), (12000000, 2025),
]


def estimate_filing_year(patent_number: int) -> int:
    """根据 US 专利号序列估算申请年（授权年减 2 年 ≈ 申请年）。"""
    grant_year = 2010
    for threshold, year in reversed(_US_PATENT_GRANT_YEAR):
        if patent_number >= threshold:
            grant_year = year
            break
    return grant_year - 2  # 平均审查周期约 2 年


# 标准专利号格式：国家(2位大写)-主号(可带字母年号前缀)[-年份][-kind]
# 例：US-7084307-B2 / CN-1234567-A / WO-9815531-A1（2段+kind）
#     JP-2004-123456-A / WO-2004-123456-A1（3段：含年份段）
#     JP-H01102549-A（平成年号前缀格式，H=平成/S=昭和/R=令和，为合法 JP 专利）
_PATENT_ID_RE = re.compile(r"^([A-Z]{2})-([A-Z]?\d+)(?:-(\d+))?(?:-[A-Za-z0-9]+)?$")


def _clean_patent_ids(patents: list[str]) -> list[str]:
    """清洗 PubChem 返回的畸形号（无连字符的 'US09290504B2'、纯公开号 'US20140155385' 等杂质），
    只保留标准 '国家-数字[-年份][-kind]' 格式，避免脏数据计入计数。"""
    out = []
    for p in patents:
        p = p.strip()
        m = _PATENT_ID_RE.match(p)
        if m and len(m.group(2)) >= 3:  # 主号至少 3 位数字
            out.append(p)
    return out


def _base_patent_no(patent_id: str) -> str:
    """提取同族基号（国家-主号[-年份]），剥离 kind 后缀（B2/A1/B1/A 等分案/版本）。
    例：'US-1234567-B2' → 'US-1234567'；'CN-1234567-A' → 'CN-1234567'；
        'JP-2004-123456-A' → 'JP-2004-123456'（3段格式须保留年份段，避免同年专利被错误合并）。"""
    parts = patent_id.split("-")
    if len(parts) >= 3 and parts[2].isdigit():
        return f"{parts[0]}-{parts[1]}-{parts[2]}"
    if len(parts) >= 2:
        return f"{parts[0]}-{parts[1]}"
    return patent_id.strip().upper()


def dedup_patent_ids(patents: list[str]) -> list[str]:
    """按同族基号去重（合并同一专利的不同 kind 版本），返回去重后的专利号列表。"""
    seen: set[str] = set()
    out: list[str] = []
    for p in patents:
        base = _base_patent_no(p)
        if base in seen:
            continue
        seen.add(base)
        out.append(p)
    return out


async def fetch_pubchem_patents(query_or_cas: str) -> dict:
    """从 PubChem 获取专利 ID 列表，按国家分组。
    返回 {"total": N, "by_country": {US: [ids], CN: [...], ...}, "us_raw": [(int_num, id), ...]}"""
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            r = await client.get(
                f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{query_or_cas}/xrefs/PatentID/JSON"
            )
            if r.status_code != 200:
                return {"total": 0, "by_country": {}, "us_raw": []}
            data = r.json()
            patents = data.get("InformationList", {}).get("Information", [{}])[0].get("PatentID", [])
            # 清洗畸形号（无连字符/纯公开号杂质）→ 按 国家-号码 合并同一专利的 kind 版本（B2/A1/B1/A）
            patents = dedup_patent_ids(_clean_patent_ids(patents))
            by_country: dict[str, list] = {}
            for p in patents:
                code = p.split("-")[0] if "-" in p else "XX"
                by_country.setdefault(code, []).append(p)
            # 提取 US 专利号码并排序（过滤非标准 Utility 专利）
            us_raw = []
            skip_prefixes = {"RE", "D", "PP", "H", "SIR"}
            for p in by_country.get("US", []):
                parts = p.split("-")
                if len(parts) < 2:
                    continue
                code = parts[1].upper() if len(parts) > 1 else ""
                # 跳过非标准 Uitlity 专利（RE=重新公告 D=外观 PP=植物 H=法定发明登记）
                if code in skip_prefixes:
                    continue
                # RS (Reissue application) 也跳过
                if code.startswith("RE") or code.startswith("RS"):
                    continue
                num_str = parts[1] if len(parts) > 1 else ""
                digits = re.sub(r'[^0-9]', '', num_str)
                if digits and 7 <= len(digits) <= 8:  # 授权号长度 7-8 位（排除 9+ 位的申请公开号如 US-20260098098）
                    patent_num = int(digits)
                    if patent_num >= 7000000:  # 2006 年后授权的现代专利（授权—申请 2 年间隔）
                        us_raw.append((patent_num, p))
            us_raw.sort(key=lambda x: x[0])
            return {"total": len(patents), "by_country": by_country, "us_raw": us_raw}
    except Exception:
        return {"total": 0, "by_country": {}, "us_raw": []}


async def fetch_pubmed_patent_articles(query: str) -> str:
    """从 PubMed 检索专利/知识产权相关文献（提供到期时间等线索）。"""
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?"
                f"db=pubmed&retmode=json&retmax=5&sort=relevance&"
                f"term={query}+AND+(patent+OR+%22intellectual+property%22+OR+expiry+OR+%22Orange+Book%22)"
            )
            if r.status_code != 200:
                return ""
            ids = r.json().get("esearchresult", {}).get("idlist", [])
            if not ids:
                return ""
            r2 = await client.get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?"
                f"db=pubmed&id={','.join(ids[:3])}&rettype=abstract&retmode=xml"
            )
            if r2.status_code != 200:
                return ""
            root = ET.fromstring(r2.text)
            articles = []
            for art in root.findall(".//PubmedArticle")[:3]:
                title = art.findtext(".//ArticleTitle", "")[:200]
                pub_year = art.findtext(".//PubDate/Year", "")
                abstract = art.findtext(".//Abstract/AbstractText", "")[:400]
                articles.append(f"**[{pub_year}]** {title}\n> {abstract}")
            return "\n\n".join(articles)
    except Exception:
        return ""


def build_patent_result(patent_data: dict, query: str, pubmed_text: str):
    """根据 PubChem 专利数据构建结构和文本表示（精简版）。

    只保留对用户有用的信息：专利件数（一句话）、核心专利线索、到期时间估算；
    去掉口径说明、提及量分析、PubChem 专利交叉引用、US 专利大表格等噪音。
    到期信息未检索到时显式标注"暂未搜索到"，避免前端空显示。
    返回 {"fields": [...], "text_parts": [...], "content": "..."}"""
    by_country = patent_data.get("by_country", {})
    us_raw = patent_data.get("us_raw", [])
    total = patent_data.get("total", 0)

    parts = []
    fields = []

    us_total = len(by_country.get("US", []))
    cn_count = len(by_country.get("CN", []))
    wo_count = len(by_country.get("WO", []))

    if total == 0:
        content = "PubChem 未收录该化合物的专利信息。"
        return {
            "fields": [
                {"key": "compound_patent_expiry", "label": "专利到期时间", "value": "暂未搜索到",
                 "source": "PubChem", "sourceUrl": "", "confidence": 50},
            ],
            "text_parts": [content],
            "content": content,
        }

    # 专利件数（一句话概括，不做口径/提及量分析）
    stats = []
    if us_total:
        stats.append(f"US {us_total} 件")
    if cn_count:
        stats.append(f"CN {cn_count} 件")
    if wo_count:
        stats.append(f"WO {wo_count} 件")
    count_txt = f"共 {total} 件" + (f"（{'、'.join(stats)}）" if stats else "")
    parts.append(f"- **专利件数**: {count_txt}")

    # US 专利与到期估算（核心信息）
    if us_raw:
        earliest = us_raw[0]
        latest = us_raw[-1]

        file_yr = estimate_filing_year(earliest[0])
        exp_yr = file_yr + 20

        fields.append({
            "key": "compound_patent", "label": "核心专利线索（最早 US）",
            "value": earliest[1], "source": "PubChem", "confidence": 55,
        })
        fields.append({
            "key": "compound_patent_expiry", "label": "专利到期时间（估算）",
            "value": f"~{exp_yr} 年（申请 ~{file_yr} + 20 年，可能有 PTA 延长）",
            "source": "USPTO 估算", "confidence": 60,
        })
        parts.append(f"- **核心专利线索（最早 US）**: {earliest[1]}")
        parts.append(f"- **专利到期时间（估算）**: ~{exp_yr} 年")

        if len(us_raw) > 3:
            latest_file = estimate_filing_year(latest[0])
            latest_exp = latest_file + 20
            fields.append({
                "key": "latest_us_patent_expiry", "label": "最新 US 专利到期（估算）",
                "value": f"~{latest_exp} 年（申请 ~{latest_file} + 20 年）",
                "source": "USPTO 估算", "confidence": 55,
            })
            parts.append(f"- **最新 US 专利到期（估算）**: ~{latest_exp} 年")

        # US 专利号（紧凑列举，不再用大表格）
        us_list = ", ".join(pid for _, pid in us_raw[:10])
        if len(us_raw) > 10:
            us_list += f" 等 {len(us_raw)} 件"
        parts.append(f"- **US 专利号**: {us_list}")
    else:
        fields.append({
            "key": "compound_patent_expiry", "label": "专利到期时间", "value": "暂未搜索到",
            "source": "PubChem", "sourceUrl": "", "confidence": 50,
        })
        parts.append("- **专利到期时间**: 暂未搜索到（PubChem 未返回可分析的有效 US 专利）")

    # CN 专利（简短列举）
    if cn_count:
        cn_list = by_country.get("CN", [])
        cn_txt = ", ".join(cn_list[:10])
        if cn_count > 10:
            cn_txt += f" 等 {cn_count} 件"
        parts.append(f"- **CN 中国专利**: {cn_txt}")

    # WO/PCT（简短列举）
    if wo_count:
        wo_list = by_country.get("WO", [])
        wo_txt = ", ".join(wo_list[:6])
        if wo_count > 6:
            wo_txt += f" 等 {wo_count} 件"
        parts.append(f"- **WO/PCT 国际专利**: {wo_txt}")

    parts.append("> 到期时间为基于 US 专利号序列的启发式估算（非真实法律状态），最终以 FDA Orange Book 或各国专利局登记为准。")

    content = "\n".join(parts)

    return {
        "fields": fields,
        "text_parts": [content],
        "content": content,
    }
