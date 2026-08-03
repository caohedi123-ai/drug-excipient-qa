"""AnySearch MCP 搜索引擎封装 - 官方 v3.0.1 协议完整实现（2026-08-03 重写）

⚠️ 调用链修复记录（此前 402「免费额度已用完」且后台无调用记录的根因）：
- 错误端点: https://api.anysearch.com/v1/search + x-api-key 头
  → 该端点是全局共享且早已耗尽的旧免费端点，与用户账户配额无关，任何 key 都返回 402。
- 官方正确协议（https://www.anysearch.com/docs + anysearch-skill v3.0.1，全部实测确认）:
  * 端点: https://api.anysearch.com/mcp（JSON-RPC 2.0）
  * 认证: Authorization: Bearer <API_KEY>（可匿名）
  * 头:   X-Anysearch-Client: skill/3.0.1
  * 工具: search / batch_search / get_sub_domains / extract
  * 垂直搜索（HARD GATE）: 必须先 get_sub_domains 取子域目录与必填参数，
    再 search 传 sub_domain="域.子域"（如 health.drug / ip.global / academic.biomedical）
    + sub_domain_params（JSON dict，必填参数不适用的传空字符串）
  * batch_search: 一次 HTTP 合并 1-5 条 query，可共享注入 domain/sub_domain/sdp/max_results
  * extract: URL → 页面正文 Markdown（截断 50K 字符）

设计要点：
- get_sub_domains: 垂直子域目录查询 + 进程内缓存（仅首次拉取，配额友好）
- sub_domain_params(sdp): 支持 dict，自动补必填参数（缺失补空串）
- 旧调用点兼容: sub_domain="patent" 等短名自动映射为官方 "ip.global" + 必填 sdp
- anysearch_vertical: 单 query（保持旧签名）
- anysearch_batch: 批量，1 次 HTTP ≤5 query，每条可独立垂直参数
- anysearch_extract: 页面正文深度抓取
- 免费额度 1000次/天（按 HTTP 请求计），batch 合并可大幅降低请求次数
"""

import asyncio
import re
import threading
import httpx
from agent.state import Citation, SearchResult
from config import get_settings

settings = get_settings()

# 官方 MCP 端点（JSON-RPC 2.0）
ANYSEARCH_MCP = "https://api.anysearch.com/mcp"
CLIENT_HEADER = "skill/3.0.1"
_BATCH_MAX = 5

# 垂直领域（官方 17 域）
VALID_DOMAINS = {
    "general", "resource", "social_media", "finance", "academic",
    "legal", "health", "business", "security", "ip", "code",
    "energy", "environment", "agriculture", "travel", "film", "gaming",
}

# ─────────────────────────────────────────────────────────────────────────────
# 垂直子域目录缓存（进程内，会话级）
#   _SUB_DOMAIN_CACHE[domain] = {
#       "sub_domain.xxx": {"desc": str, "params": {"name": {"required": bool, "desc": str}}},
#   }
# ─────────────────────────────────────────────────────────────────────────────
_SUB_DOMAIN_CACHE: dict[str, dict] = {}
_CACHE_LOCK = threading.Lock()

# 旧代码子域短名 → (官方域, 官方子域, 必填 sdp 默认值)
_SUB_DOMAIN_ALIASES = {
    "patent": ("ip", "ip.global", {"type": "GlobalPatent", "keyword": ""}),
    "drug": ("health", "health.drug", {"type": "name"}),
    "druglabel": ("health", "health.drug", {"type": "name"}),
    "stats": ("health", "health.stats", {}),
    "trial": ("health", "health.trial", {}),
    "biomedical": ("academic", "academic.biomedical", {}),
    "search": ("academic", "academic.search", {}),
    "citation": ("academic", "academic.citation", {}),
    "statute": ("legal", "legal.statute", {}),
    "case": ("legal", "legal.case", {}),
    "company": ("business", "business.company", {}),
    "global": ("ip", "ip.global", {"type": "GlobalPatent", "keyword": ""}),
}

# 首次 get_sub_domains 拉取覆盖的域（业务相关 + 泛用）
_PREFETCH_DOMAINS = ["health", "academic", "ip", "legal", "business"]


def _headers() -> dict:
    h = {
        "Content-Type": "application/json",
        "X-Anysearch-Client": CLIENT_HEADER,
    }
    key = (settings.anysearch_api_key or "").strip()
    if key:
        h["Authorization"] = f"Bearer {key}"
    return h


def _rpc_call(name: str, arguments: dict, timeout: float = 60.0) -> dict:
    """调用 AnySearch MCP 工具，返回 result dict；失败抛异常。"""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }
    resp = httpx.post(ANYSEARCH_MCP, json=payload, headers=_headers(),
                      timeout=timeout, trust_env=False)
    if resp.status_code != 200:
        raise RuntimeError(f"AnySearch HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"AnySearch RPC error: {data['error']}")
    result = data.get("result", {})
    if result.get("isError"):
        texts = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
        raise RuntimeError(" | ".join(texts) or "AnySearch RPC isError")
    return result


def _result_text(result: dict) -> str:
    parts = []
    for c in result.get("content", []):
        if c.get("type") == "text":
            parts.append(c.get("text", ""))
    return "\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# get_sub_domains：垂直子域目录（HARD GATE 前置步骤，进程内缓存）
# 返回格式（实测）：
#   ## health Domain Capabilities (3 available)
#   ### health.drug
#   Drug labeling info...
#   **Parameters:**
#   - `type` (required): name/ndc/upc ...
# ─────────────────────────────────────────────────────────────────────────────

_RE_DOMAIN_HEAD = re.compile(r"^##\s+(\w+)\s+Domain Capabilities", re.I)
_RE_SUBDOMAIN_HEAD = re.compile(r"^###\s+([\w.]+)\s*$")
_RE_PARAM_LINE = re.compile(r"^[-*]\s*`([\w_]+)`\s*(?:\((required)\))?\s*:?\s*(.*)$")


def _parse_subdomain_catalog(text: str) -> dict[str, dict]:
    """解析 get_sub_domains 返回 → {domain: {sub_domain: {"desc", "params": {...}}}}"""
    catalog: dict[str, dict] = {}
    cur_domain, cur_sub, cur_params = None, None, {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        m = _RE_DOMAIN_HEAD.match(line)
        if m:
            cur_domain = m.group(1)
            catalog.setdefault(cur_domain, {})
            cur_sub, cur_params = None, {}
            continue
        if cur_domain is None:
            continue
        m = _RE_SUBDOMAIN_HEAD.match(line)
        if m:
            cur_sub = m.group(1)
            cur_params = {}
            catalog[cur_domain][cur_sub] = {"desc": "", "params": cur_params}
            continue
        m = _RE_PARAM_LINE.match(line)
        if m and cur_sub is not None:
            pname, required, desc = m.group(1), m.group(2), m.group(3) or ""
            cur_params[pname] = {"required": bool(required), "desc": desc.strip()}
            continue
        if cur_sub is not None and not line.startswith("**") and line and cur_sub in catalog[cur_domain]:
            if not catalog[cur_domain][cur_sub]["desc"]:
                catalog[cur_domain][cur_sub]["desc"] = line
    return catalog


def get_sub_domains(domains: list[str] | None = None) -> dict[str, dict]:
    """查询垂直子域目录（进程内缓存，配额友好）。

    Args:
        domains: 需要查询的域列表；默认拉取业务相关域。每请求最多 5 个域，自动分批。
    Returns:
        {domain: {sub_domain: {"desc": str, "params": {name: {"required": bool, "desc": str}}}}}
    """
    to_fetch = [d for d in (domains or _PREFETCH_DOMAINS) if d in VALID_DOMAINS and d not in _SUB_DOMAIN_CACHE]
    for i in range(0, len(to_fetch), _BATCH_MAX):
        chunk = to_fetch[i:i + _BATCH_MAX]
        try:
            result = _rpc_call("get_sub_domains", {"domains": chunk}, timeout=60.0)
            parsed = _parse_subdomain_catalog(_result_text(result))
            with _CACHE_LOCK:
                for d, subs in parsed.items():
                    _SUB_DOMAIN_CACHE.setdefault(d, {}).update(subs)
        except Exception as e:
            print(f"[AnySearch] get_sub_domains({chunk}) failed: {e}")
    with _CACHE_LOCK:
        return {d: dict(v) for d, v in _SUB_DOMAIN_CACHE.items()}


def _ensure_subdomains(domain: str) -> dict:
    """确保指定域已拉取子域目录，返回该域目录（可能为空 dict）。"""
    if domain in VALID_DOMAINS and domain not in _SUB_DOMAIN_CACHE:
        get_sub_domains([domain])
    return dict(_SUB_DOMAIN_CACHE.get(domain, {}))


def _resolve_sub_domain(domain: str | None, sub_domain: str | None) -> tuple[str | None, str | None, dict]:
    """把旧代码 sub_domain 短名解析为官方 (domain, sub_domain, default_sdp)。

    规则：
    - sub_domain 为空 → (domain, None, {})，走服务端自动路由
    - sub_domain 含 '.' → 已是官方格式，直接使用
    - 否则查别名表；命中则补全官方域与必填 sdp 默认值
    """
    if not sub_domain:
        return domain, None, {}
    if "." in sub_domain:
        return domain, sub_domain, {}
    alias = _SUB_DOMAIN_ALIASES.get(sub_domain)
    if alias:
        ad, asub, sdp = alias
        return ad, asub, dict(sdp)
    # 未知短名：作为官方子域透传（服务端自行处理）
    return domain, sub_domain, {}


def _build_sdp(sub_domain: str | None, sdp: dict | None) -> dict | None:
    """构造 sub_domain_params：dict 透传；必填参数缺失时补空字符串（官方要求）。"""
    if not sub_domain:
        return None
    sdp = dict(sdp or {})
    domain = next((d for d, subs in _SUB_DOMAIN_CACHE.items() if sub_domain in subs), None)
    if domain:
        for pname, meta in _SUB_DOMAIN_CACHE[domain][sub_domain].get("params", {}).items():
            if meta.get("required") and pname not in sdp:
                sdp[pname] = ""
    return sdp or None


def _fill_sdp_defaults(sdp: dict | None, defaults: dict) -> dict | None:
    """用子域别名默认值填充 sdp（显式传入优先）。"""
    sdp = dict(sdp or {})
    for k, v in defaults.items():
        if k not in sdp:
            sdp[k] = v
    return sdp or None


# ─────────────────────────────────────────────────────────────────────────────
# markdown 响应解析（service 端协议格式，已实测确认）
#   search : "## Search Results (N results, Xms)" 后跟 "### N. Title" / "- **URL**: ..." / 摘要
#   batch  : "## Query N: <q>" 分段，每段同 search
# ─────────────────────────────────────────────────────────────────────────────

_RE_RESULT_HEAD = re.compile(r"^###\s*\d+[.)]?\s*(.*)$")
_RE_URL_LINE = re.compile(r"^[-*]\s*\*\*URL\*\*:\s*(\S+)", re.I)
_RE_IMG = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_RE_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_RE_BLOB = re.compile(r"blob:[^\s)\]]*")
_RE_NAV_NOISE = re.compile(
    r"(Jump to content|Skip navigation|Search|Main Menu|Navigation menu|"
    r"Cookie|Privacy policy|About Wikipedia|Disclaimers|Contact Wikipedia)", re.I)

# 专利条目（ip.global / GlobalPatent 返回）单行格式：
#   - Title: <专利名> URL: <patsnap 链接> Assignee: <申请人> Inventor: <发明人> Authority: ...
# 与普通搜索条目 "- **URL**: ..." 不同，需专门提取。
_RE_PATENT_TITLE_LINE = re.compile(r"^[-*]\s*Title\s*[:：]\s*(.+)$", re.I)
_RE_INLINE_URL = re.compile(r"\bURL\s*[:：]\s*(https?://[^\s]+)", re.I)
_RE_PATENT_META = re.compile(
    r"\b(Assignee|Assignees|Applicant|Applicants|Inventor|Inventors|Authority|Publication Date|"
    r"Publication|Application Date|Application No|Abstract)\s*[:：]\s*([^|]{1,400}?)"
    r"(?=\s+(?:Assignee|Assignees|Applicant|Applicants|Inventor|Inventors|Authority|Publication Date|"
    r"Publication|Application Date|Application No|Abstract|IPC)\s*[:：]|\s*$)", re.I)


def _clean_abstract(text: str, max_len: int = 500) -> str:
    """清洗摘要：去图片 markdown / blob 链接 / 导航噪音 / 冗余空白。"""
    if not text:
        return ""
    t = _RE_IMG.sub(" ", text)
    t = _RE_LINK.sub(r"\1", t)
    t = _RE_BLOB.sub(" ", t)
    t = _RE_NAV_NOISE.sub(" ", t)
    t = t.replace("#", " ").replace("*", " ").replace("|", " ").replace("---", " ")
    t = re.sub(r"\s+", " ", t).strip()
    return t[:max_len]


# 专利结构化数据段（=== Bibliographic Data === / --- Legal Status ===）中
# 紧跟其后的顶层字段名，用于界定 abstracts.text 摘要正文的边界。
_RE_BIBLIO_FIELD_BOUNDARY = re.compile(
    r"\b(application_reference|invention_title|classification_data|parties|"
    r"publication_reference|priority_claims|pct_or_regional|dates_of_public_availability|"
    r"exdt|error_code|status|patent_id|pn|legal_status|extension_data)\s*[:：]", re.I)


def _extract_patent_text(block: str, patent: dict) -> None:
    """从专利结构化数据段提取关键字段（摘要正文 / 公开号 / 申请人 / 发明人）。"""
    if not block:
        return
    # 摘要正文：abstracts 下的 text: 字段（截止到下一个顶层字段）
    m = re.search(r"\btext\s*[:：]\s*(.+?)(?=" + _RE_BIBLIO_FIELD_BOUNDARY.pattern + r"|\s*$)",
                  block, re.S | re.I)
    if m:
        patent.setdefault("abstract_text", _clean_abstract(m.group(1), 900))
    m = re.search(r"\bpn\s*[:：]\s*([A-Z0-9/]+)", block, re.I)
    if m:
        patent.setdefault("pn", m.group(1))
    m = re.search(r"\bassignees?\s*:\s*[\s\S]*?\bname\s*[:：]\s*([A-Z][A-Z0-9 .,&'()\-]{2,120}?)(?=\s+sequence)",
                  block, re.I)
    if m:
        patent.setdefault("assignee", m.group(1).strip())
    m = re.search(r"\binventors?\s*:\s*[\s\S]*?\bname\s*[:：]\s*([A-Z][A-Z0-9 .,&'()\-]{2,120}?)(?=\s+sequence)",
                  block, re.I)
    if m:
        patent.setdefault("inventor", m.group(1).strip())


def _build_patent_snippet(patent: dict, abstract_max: int) -> str:
    """由专利字段组装结构化摘要：摘要正文 + 公开号 + 申请人 + 发明人。"""
    parts = []
    ab = patent.get("abstract_text") or patent.get("abstract") or ""
    if ab:
        parts.append(ab)
    pub = patent.get("pn") or patent.get("publication") or ""
    if pub:
        parts.append(f"公开号: {pub}")
    assignee = (patent.get("assignee") or patent.get("applicants")
                or patent.get("applicant") or "")
    if assignee:
        parts.append(f"申请人: {assignee}")
    inventor = patent.get("inventor") or patent.get("inventors") or ""
    if inventor:
        parts.append(f"发明人: {inventor}")
    if patent.get("pub_date"):
        parts.append(f"公开日: {patent['pub_date']}")
    s = " | ".join(parts)
    return _clean_abstract(s, abstract_max) if s else ""


_RE_META_NAMES = ("assignee", "assignees", "applicant", "applicants",
                  "inventor", "inventors")


def _clean_meta_name(value: str) -> str:
    """清理专利元数据中的 YAML 结构噪音：
    '- address: Toronto,CA data_format: original lang: EN name: APOTEX INC. sequence: 1'
    → 'APOTEX INC.'"""
    v = value.strip()
    m = re.search(r"\bname\s*[:：]\s*([^|,]{2,120}?)(?=\s+sequence|\s*$)", v, re.I)
    if m:
        return m.group(1).strip()
    return v


def _fill_patent_keyword(real_sub: str | None, sdp: dict | None, query: str) -> dict | None:
    """ip.global 专利检索：GlobalPatent 的 keyword 为空时自动用 query 填充，
    避免旧调用点（sub_domain='patent' 别名）因空关键词导致检索质量差。"""
    if real_sub == "ip.global" and sdp:
        kw = sdp.get("keyword")
        if not kw:
            sdp = dict(sdp)
            sdp["keyword"] = query
    return sdp


def _parse_search_markdown(text: str, query: str, max_results: int = 10,
                           abstract_max: int = 500) -> tuple[list, list[str]]:
    """解析 search 返回的 markdown → (citations, content_parts)"""
    citations: list[Citation] = []
    content_parts: list[str] = []
    lines = (text or "").splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        m = _RE_RESULT_HEAD.match(line)
        if not m:
            i += 1
            continue
        title = m.group(1).strip()
        url, abstract = "", []
        patent: dict = {}
        i += 1
        while i < len(lines):
            l = lines[i].strip()
            if _RE_RESULT_HEAD.match(l):
                break
            if l.startswith("===") or (l.startswith("---") and re.search(
                    r"(Bibliographic Data|Legal Status|data:)", l, re.I)):
                # 专利结构化数据段：提取关键字段后跳到下一条目
                _extract_patent_text("\n".join(lines[i:]), patent)
                j = i + 1
                while j < len(lines) and not _RE_RESULT_HEAD.match(lines[j].strip()):
                    j += 1
                i = j
                break
            um = _RE_URL_LINE.match(l)
            if um:
                url = um.group(1)
            elif l and not l.startswith("## "):
                if _RE_PATENT_TITLE_LINE.match(l):
                    # 专利单行：- Title: <名> URL: <链接> Assignee: <申请人> ...
                    um2 = _RE_INLINE_URL.search(l)
                    if um2 and not url:
                        url = um2.group(1)
                    for fm in _RE_PATENT_META.finditer(l):
                        key = fm.group(1).lower().replace(" ", "_")
                        val = fm.group(2).strip()
                        if key in _RE_META_NAMES:
                            val = _clean_meta_name(val)
                        patent.setdefault(key, val)
                else:
                    abstract.append(l)
            i += 1
        if patent:
            snippet = _build_patent_snippet(patent, abstract_max)
        else:
            snippet = _clean_abstract(" ".join(abstract), abstract_max)
        if not url and not snippet:
            continue
        if len(citations) >= max_results:
            break
        citations.append(Citation(
            id=len(citations) + 1,
            source_name="AnySearch",
            source_url=url,
            snippet=snippet or title,
            retrieval_query=query,
            retrieval_timestamp=Citation.make_timestamp(),
        ))
        content_parts.append(f"### {title}\n{snippet}\n[来源]({url})" if url else f"### {title}\n{snippet}")
    return citations, content_parts


def _parse_batch_markdown(text: str, queries: list[dict],
                          abstract_max: int = 500) -> list[tuple[list, list[str]]]:
    """解析 batch 返回：按 '## Query N:' 分段，返回与 queries 等长的 (citations, parts)。

    服务端分段格式（实测）："## Query N: <q>" 后紧跟该条目的结果 markdown。
    re.split 带捕获组时返回 [pre, q1, body1, q2, body2, ..., post]，
    故 body 索引为 idx*2+1（此前 idx+1 会导致第 2 条起全部错位/取空）。
    若响应无 "## Query" 分段，则整段按单条 search 格式解析。
    """
    text = text or ""
    segs = re.split(r"^## Query\s*\d+\s*:\s*(.*)$", text, flags=re.M)
    bodies = segs[1:]
    out: list[tuple[list, list[str]]] = []
    if not bodies:
        for q in queries:
            cits, parts = _parse_search_markdown(text, q.get("query", ""),
                                                 q.get("max_results", 10), abstract_max)
            out.append((cits, parts))
        return out
    for idx, q in enumerate(queries):
        body = bodies[idx * 2 + 1] if idx * 2 + 1 < len(bodies) else ""
        cits, parts = _parse_search_markdown(body, q.get("query", ""),
                                             q.get("max_results", 10), abstract_max)
        out.append((cits, parts))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 对外 API
# ─────────────────────────────────────────────────────────────────────────────

def anysearch_vertical(
    query: str,
    domain: str = "health",
    sub_domain: str | None = None,
    sub_domain_params: dict | None = None,
    freshness: str = "any",
    content_types: list[str] | None = None,
    max_results: int = 10,
    abstract_max: int = 500,
) -> SearchResult:
    """AnySearch 垂直领域搜索（官方 MCP /mcp 协议）。

    Args:
        query: 检索关键词
        domain: 垂直领域 health/academic/ip/legal 等 17 域；传 None 走通用泛搜
        sub_domain: 官方子域（"域.子域"，如 health.drug / ip.global）；短名自动映射
        sub_domain_params: 子域必填参数 dict（如 {"type": "name"}），缺必填自动补空串
        freshness: 时效 "any"/"past_day"/"past_week"/"past_month"/"past_year"
        content_types: 内容类型过滤
        max_results: 最大返回数（上限 10）
        abstract_max: 摘要清洗后的最大长度
    """
    try:
        real_domain, real_sub, default_sdp = _resolve_sub_domain(domain, sub_domain)
        if real_sub:
            _ensure_subdomains(real_domain or "")
        sdp = _fill_sdp_defaults(sub_domain_params, default_sdp)
        sdp = _fill_patent_keyword(real_sub, sdp, query)
        sdp = _build_sdp(real_sub, sdp)

        arguments: dict = {"query": query, "max_results": min(int(max_results), 10)}
        if real_domain and real_domain in VALID_DOMAINS:
            arguments["domain"] = real_domain
        if real_sub:
            arguments["sub_domain"] = real_sub
        if sdp:
            arguments["sub_domain_params"] = sdp
        if freshness != "any":
            arguments["freshness"] = freshness
        if content_types:
            arguments["content_types"] = content_types

        result = _rpc_call("search", arguments)
        text = _result_text(result)
        citations, content_parts = _parse_search_markdown(
            text, query, max_results, abstract_max)
        if not content_parts and "No results" in text:
            return SearchResult(
                source_name="AnySearch", content="No results found.",
                citations=[], success=False,
            )
        return SearchResult(
            source_name="AnySearch",
            content="\n\n".join(content_parts) if content_parts else "No results found.",
            citations=citations or [],
            success=bool(content_parts),
        )
    except Exception as e:
        return SearchResult(
            source_name="AnySearch",
            content=f"AnySearch({domain or 'general'}) error: {e}",
            citations=[
                Citation(id=1, source_name="AnySearch", source_url="",
                         snippet=str(e), retrieval_query="", retrieval_timestamp=Citation.make_timestamp())
            ],
            success=False,
        )


def anysearch_batch(queries: list[dict], abstract_max: int = 500) -> list[SearchResult]:
    """批量搜索：一次 HTTP 请求合并 ≤5 个 query，返回等长 SearchResult 列表。

    Args:
        queries: 每条支持：
            {"query": str, "domain": str|None, "sub_domain": str|None,
             "sub_domain_params": dict|None, "max_results": int, "freshness": str}
        也可省略 domain/sub_domain 走通用泛搜。
        abstract_max: 摘要清洗后的最大长度
    """
    if not queries:
        return []
    out: list[SearchResult] = []
    for start in range(0, len(queries), _BATCH_MAX):
        chunk = queries[start:start + _BATCH_MAX]
        try:
            args_queries = []
            for q in chunk:
                dom = q.get("domain")
                real_domain, real_sub, default_sdp = _resolve_sub_domain(dom, q.get("sub_domain"))
                if real_sub:
                    _ensure_subdomains(real_domain or "")
                sdp = _fill_sdp_defaults(q.get("sub_domain_params"), default_sdp)
                sdp = _fill_patent_keyword(real_sub, sdp, q.get("query", ""))
                sdp = _build_sdp(real_sub, sdp)
                item: dict = {"query": q.get("query", ""),
                              "max_results": min(int(q.get("max_results", 10)), 10)}
                if real_domain and real_domain in VALID_DOMAINS:
                    item["domain"] = real_domain
                if real_sub:
                    item["sub_domain"] = real_sub
                if sdp:
                    item["sub_domain_params"] = sdp
                if q.get("freshness") and q.get("freshness") != "any":
                    item["freshness"] = q["freshness"]
                args_queries.append(item)
            result = _rpc_call("batch_search", {"queries": args_queries}, timeout=60.0)
            text = _result_text(result)
            parsed = _parse_batch_markdown(text, chunk, abstract_max)
            for (cits, parts) in parsed:
                if parts:
                    out.append(SearchResult(
                        source_name="AnySearch", content="\n\n".join(parts),
                        citations=cits or [], success=True,
                    ))
                else:
                    out.append(SearchResult(
                        source_name="AnySearch", content="No results found.",
                        citations=[], success=False,
                    ))
        except Exception as e:
            for q in chunk:
                out.append(SearchResult(
                    source_name="AnySearch",
                    content=f"AnySearch(batch) error: {e}",
                    citations=[], success=False,
                ))
    return out


async def anysearch_search(query: str, domain: str = "health") -> str:
    """简易异步包装：供 fallback_chain 使用，返回纯文本"""
    result = await asyncio.to_thread(anysearch_vertical, query, domain=domain, max_results=5)
    return result.content if result else ""


def anysearch_extract(url: str) -> str:
    """extract 页面正文深度抓取：URL → 页面正文 Markdown（截断 50K 字符）"""
    try:
        result = _rpc_call("extract", {"url": url}, timeout=60.0)
        return _result_text(result)[:50000]
    except Exception as e:
        return f"extract error: {e}"
