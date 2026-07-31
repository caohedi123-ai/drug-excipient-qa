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
                if digits and len(digits) >= 7:  # 至少 7 位
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
    """根据 PubChem 专利数据构建结构和文本表示。
    返回 {"fields": [...], "text_parts": [...], "content": "..."}"""
    by_country = patent_data.get("by_country", {})
    us_raw = patent_data.get("us_raw", [])
    total = patent_data.get("total", 0)

    parts = []
    fields = []

    us_filtered = len(us_raw)  # 过滤后（>=7M 现代专利）
    us_total = len(by_country.get("US", []))
    cn_count = len(by_country.get("CN", []))
    wo_count = len(by_country.get("WO", []))
    ep_count = len(by_country.get("EP", []))
    jp_count = len(by_country.get("JP", []))
    other = total - us_total - cn_count - wo_count - ep_count - jp_count

    if total == 0:
        parts.append("PubChem 未收录该化合物的专利信息。")
        content = "\n".join(parts)
        return {
            "fields": [{"key": "patent_summary", "label": "专利概况", "value": "PubChem 未收录", "source": "PubChem", "sourceUrl": "", "confidence": 50}],
            "text_parts": [f"### PubChem 专利\n\n{content}"],
            "content": content,
        }

    parts.append(f"## PubChem 专利数据（共 {total} 件）\n")

    # 专利统计
    stats_lines = []
    if us_filtered: stats_lines.append(f"**US 美国专利**: {us_filtered} 件（含核心化合物/晶型/制剂/用途专利）")
    if cn_count: stats_lines.append(f"**CN 中国专利**: {cn_count} 件")
    if wo_count: stats_lines.append(f"**WO/PCT 国际**: {wo_count} 件")
    if ep_count: stats_lines.append(f"**EP 欧洲专利**: {ep_count} 件")
    if jp_count: stats_lines.append(f"**JP 日本专利**: {jp_count} 件")
    if other > 0: stats_lines.append(f"**其他**: {other} 件")
    parts.extend(stats_lines)

    # 专利概况字段
    summary_val = f"共 {total} 件（US {us_filtered}/CN {cn_count}/WO {wo_count}/EP {ep_count}"
    if jp_count: summary_val += f"/JP {jp_count}"
    summary_val += "）"
    fields.append({
        "key": "patent_summary", "label": "专利概况", "value": summary_val,
        "source": "PubChem", "sourceUrl": f"https://pubchem.ncbi.nlm.nih.gov/compound/{query}", "confidence": 90
    })

    # US 专利分析与到期估算
    if us_raw:
        earliest = us_raw[0]
        latest = us_raw[-1]

        file_yr = estimate_filing_year(earliest[0])
        exp_yr = file_yr + 20

        parts.append(f"\n## 专利到期时间（估算）\n")
        parts.append(f"> 注：基于 US 专利号序列估算申请年，20 年保护期从申请日起算。")
        parts.append(f"> 实际到期以 FDA Orange Book 或各国专利局登记为准。Patent Term Adjustment (PTA) 可能延长 2-5 年。")

        # 化合物核心专利
        parts.append(f"\n- **化合物核心专利**: **{earliest[1]}**")
        parts.append(f"  - 估算申请年: **~{file_yr}** 年")
        parts.append(f"  - 估算到期日: **~{exp_yr}** 年（20 年保护期，可能有 PTA 延长）")

        fields.append({
            "key": "compound_patent", "label": "化合物核心专利",
            "value": earliest[1], "source": "PubChem", "confidence": 85
        })
        fields.append({
            "key": "compound_patent_expiry", "label": "化合物专利到期（估算）",
            "value": f"~{exp_yr}（申请 ~{file_yr} + 20 年，可能 PTA 延长至 ~{exp_yr+3}）",
            "source": "USPTO 估算", "confidence": 70
        })

        # 最新制剂/用途专利
        if len(us_raw) > 3:
            latest_file = estimate_filing_year(latest[0])
            latest_exp = latest_file + 20
            parts.append(f"\n- **最新 US 专利**: **{latest[1]}**")
            parts.append(f"  - 估算申请年: **~{latest_file}** 年")
            parts.append(f"  - 估算到期日: **~{latest_exp}** 年")
            fields.append({
                "key": "formulation_patent_expiry", "label": "最新制剂/用途专利到期（估算）",
                "value": f"~{latest_exp}（申请 ~{latest_file} + 20 年）",
                "source": "USPTO 估算", "confidence": 65
            })

        # 中间关键专利（晶型）
        if len(us_raw) > 2:
            mid_idx = max(1, len(us_raw) // 3)
            mid = us_raw[mid_idx]
            mid_file = estimate_filing_year(mid[0])
            mid_exp = mid_file + 20
            parts.append(f"\n- **晶型/中间专利**: **{mid[1]}**")
            parts.append(f"  - 估算到期日: **~{mid_exp}** 年")
            fields.append({
                "key": "crystal_patent_expiry", "label": "晶型专利到期（估算）",
                "value": f"~{mid_exp}（申请 ~{mid_file} + 20 年）",
                "source": "USPTO 估算", "confidence": 65
            })

        # US 专利清单
        parts.append(f"\n## US 专利清单（前 15/共 {us_filtered} 件）\n")
        parts.append("| # | 专利号 | 申请年(估算) | 到期年(估算) |")
        parts.append("|---|--------|-------------|-------------|")
        for i, (num, pid) in enumerate(us_raw[:15]):
            fy = estimate_filing_year(num)
            ey = fy + 20
            parts.append(f"| {i+1} | **{pid}** | ~{fy} | ~{ey} |")
        if len(us_raw) > 15:
            parts.append(f"| ... | 共 {us_filtered} 件 US 专利 | | |")

    # CN 专利
    if cn_count > 0:
        cn_list = by_country.get("CN", [])
        parts.append(f"\n## CN 中国专利（{cn_count} 件）\n")
        for pid in cn_list[:8]:
            parts.append(f"- {pid}")
        if cn_count > 8:
            parts.append(f"  ... 共 {cn_count} 件")

    # WO/PCT 专利
    if wo_count > 0 and wo_count <= 20:
        wo_list = by_country.get("WO", [])
        parts.append(f"\n## WO/PCT 国际专利（{wo_count} 件）\n")
        for pid in wo_list[:5]:
            parts.append(f"- {pid}")
        if wo_count > 5:
            parts.append(f"  ... 共 {wo_count} 件")

    # PubMed 补充
    if pubmed_text:
        parts.append(f"\n## PubMed 相关文献\n{pubmed_text}")

    content = "\n".join(parts)

    return {
        "fields": fields,
        "text_parts": [content],
        "content": content,
    }
