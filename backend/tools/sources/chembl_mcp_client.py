"""ChEMBL MCP 客户端（P0.4 重点）。

将本地构建的 ChEMBL MCP Server（27 工具）作为子进程接入 Python 后端，
为 chembl_tool 提供结构/靶点/作用机制/生物活性/ADMET/溶解度/类药性等深度数据。

设计要点（呼应"大改带来问题"的风险管控）：
- 单例 + 懒连接：首次查询时才拉起 node 子进程，不阻塞导入。
- schema 驱动调用：依据 list_tools 的 inputSchema 自动装配参数，对工具重命名/参数变更鲁棒。
- 并行编排 + 单工具超时：深度工具并发调用，单工具超时由配置控制；任一失败仅跳过该段，不影响整体。
- 重连一次：连接级异常重置后重试一次。
- 降级：chembl.py 在 MCP 不可用/关闭时回退现有 REST，检索永不中断。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from config import get_settings

logger = logging.getLogger("chembl_mcp")

# 深度检索编排的工具（按 chembl_id 拉取）；search_compounds 用于定位化合物
_DEPTH_BY_ID = [
    "get_compound_info",
    "get_mechanism_of_action",
    "search_activities",
    "analyze_admet_properties",
    "get_external_references",
    "get_drug_info",
]
_DEPTH_NEED_SMILES = [
    "predict_solubility",
    "assess_drug_likeness",
    "calculate_descriptors",
]


def _content_text(result: Any) -> str:
    """从 CallToolResult 抽取文本。"""
    parts: list[str] = []
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


def _j(text: Optional[str]) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def _first(d: Any, *keys: str, default: str = "") -> str:
    if not isinstance(d, dict):
        return default
    for k in keys:
        v = d.get(k)
        if v is not None and v != "":
            return str(v)
    return default


def _parse_search_compounds(text: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """从 search_compounds / search_drugs / batch_compound_lookup 的 JSON 文本提取 (chembl_id, pref_name)。

    兼容多种返回结构：molecules / drugs / compounds 列表，或单条 compound / molecule 对象。
    """
    d = _j(text)
    if not isinstance(d, dict):
        return None, None
    mols = d.get("molecules") or d.get("drugs") or d.get("compounds") or []
    if not mols and isinstance(d.get("compound"), dict):
        mols = [d["compound"]]
    if not mols and isinstance(d.get("molecule"), dict):
        mols = [d["molecule"]]
    if not mols:
        return None, None
    m0 = mols[0] if isinstance(mols, list) else mols
    cid = _first(m0, "molecule_chembl_id", "chembl_id")
    name = _first(m0, "pref_name", "name")
    return (cid or None), (name or None)


def _parse_info_name(text: Optional[str]) -> str:
    """从 get_compound_info 的 JSON 提取 pref_name。"""
    d = _j(text)
    if isinstance(d, dict):
        return _first(d, "pref_name", "name", "chembl_id")
    return ""


def _parse_smiles(text: Optional[str]) -> Optional[str]:
    d = _j(text)
    if isinstance(d, dict):
        st = d.get("structures") or {}
        if isinstance(st, dict):
            s = st.get("canonical_smiles") or st.get("smiles")
            if s:
                return s
        s = _first(d, "canonical_smiles", "smiles", "structure", "inchi")
        if s:
            return s
    return None


def _summ_info(text: Optional[str]) -> str:
    d = _j(text)
    if not isinstance(d, dict):
        return (text or "").strip()[:300]
    name = _first(d, "pref_name", "name")
    atc = d.get("atc_classifications") or []
    phase = _first(d, "max_phase", "development_phase")
    bbw = d.get("black_box_warning")
    bits = []
    if name:
        bits.append(f"名称={name}")
    if atc:
        bits.append("ATC=" + ",".join(str(a) for a in atc[:6]))
    if phase:
        bits.append(f"最高研发阶段={phase}")
    if bbw:
        bits.append("黑框警告=有" if str(bbw) not in ("0", "False", "false") else "黑框警告=无")
    return "; ".join(bits)


def _summ_moa(text: Optional[str]) -> str:
    d = _j(text)
    if isinstance(d, dict):
        mechs = d.get("mechanisms") or []
        if isinstance(mechs, list) and mechs:
            descs = [_first(m, "mechanism_of_action", "mechanism", "description")
                     for m in mechs if isinstance(m, dict)]
            descs = [x for x in descs if x]
            if descs:
                return "; ".join(descs[:5])
        moa = _first(d, "mechanism_of_action", "mechanism", "description")
        if moa:
            return moa
    return ""  # 无机制数据时返回空，避免倾倒原始 JSON


def _summ_activities(text: Optional[str]) -> str:
    d = _j(text)
    if not isinstance(d, dict):
        return (text or "").strip()[:300]
    acts = d.get("activities") or d.get("results") or []
    if not isinstance(acts, list):
        return (text or "").strip()[:300]
    top = []
    for a in acts[:5]:
        if not isinstance(a, dict):
            continue
        tgt = _first(a, "target_pref_name", "target_chembl_id", "target_name")
        atype = _first(a, "activity_type", "standard_type")
        val = _first(a, "standard_value", "pchembl_value", "value")
        unit = _first(a, "standard_units", "units")
        s = f"{tgt}"
        if atype:
            s += f"({atype}"
            if val:
                s += f"={val}{unit or ''}"
            s += ")"
        top.append(s)
    return "; ".join(top) or (text or "").strip()[:300]


def _summ_admet(text: Optional[str]) -> str:
    d = _j(text)
    if isinstance(d, dict):
        # ADMET 常为嵌套字典，抽取前若干键值对
        flat = []
        def _walk(o, prefix=""):
            if isinstance(o, dict):
                for k, v in list(o.items())[:8]:
                    _walk(v, f"{prefix}{k}.")
            elif isinstance(o, list):
                for it in o[:3]:
                    _walk(it, prefix)
            else:
                if prefix:
                    flat.append(f"{prefix.rstrip('.')}={o}")
        _walk(d)
        if flat:
            return "; ".join(flat[:10])
    return (text or "").strip()[:300]


def _summ_xref(text: Optional[str]) -> str:
    d = _j(text)
    if isinstance(d, dict):
        refs = d.get("cross_references") or d.get("external_references") or d.get("refs") or []
        if isinstance(refs, list):
            names = []
            for r in refs[:8]:
                if isinstance(r, dict):
                    names.append(_first(r, "xref_name", "resource", "name", "xref_id"))
            if names:
                return ", ".join(n for n in names if n)
    return ""


def _summ_drug(text: Optional[str]) -> str:
    d = _j(text)
    if isinstance(d, dict):
        phase = _first(d, "development_phase", "max_phase", "phase")
        area = _first(d, "therapeutic_area", "indication")
        bits = []
        if phase:
            bits.append(f"研发阶段={phase}")
        if area:
            bits.append(f"治疗领域={area}")
        if bits:
            return "; ".join(bits)
    return ""


def _summ_simple(text: Optional[str]) -> str:
    d = _j(text)
    if isinstance(d, dict):
        flat = []
        for k, v in list(d.items())[:6]:
            if isinstance(v, (str, int, float, bool)):
                flat.append(f"{k}={v}")
        if flat:
            return "; ".join(flat)
    return (text or "").strip()[:300]


def _summ_sol(text: Optional[str]) -> str:
    d = _j(text)
    if not isinstance(d, dict):
        return (text or "").strip()[:300]
    sol = d.get("aqueous_solubility") or {}
    perm = d.get("permeability") or {}
    bits = []
    if isinstance(sol, dict):
        bits.append(f"水溶性={sol.get('predicted_class')}")
    if isinstance(perm, dict):
        bits.append(f"渗透性={perm.get('predicted_class')}; {perm.get('assessment', '')}".rstrip("; "))
    return "; ".join(b for b in bits if b) or (text or "").strip()[:300]


def _summ_dl(text: Optional[str]) -> str:
    d = _j(text)
    if not isinstance(d, dict):
        return (text or "").strip()[:300]
    lip = d.get("lipinski_rule_of_five") or {}
    veb = d.get("veber_rules") or {}
    bits = []
    if isinstance(lip, dict):
        bits.append(f"Lipinski={'通过' if lip.get('pass') else '未通过'}(违规{lip.get('violations')})")
    if isinstance(veb, dict):
        bits.append(f"Veber={'通过' if veb.get('pass') else '未通过'}")
    return "; ".join(bits) or (text or "").strip()[:300]


def _summ_desc(text: Optional[str]) -> str:
    d = _j(text)
    if not isinstance(d, dict):
        return (text or "").strip()[:300]
    bp = d.get("basic_properties") or {}
    lipo = d.get("lipophilicity") or {}
    hb = d.get("hydrogen_bonding") or {}
    psa = d.get("polar_surface_area") or {}
    dl = d.get("drug_likeness_metrics") or {}
    bits = []
    if bp.get("molecular_weight"):
        bits.append(f"MW={bp['molecular_weight']}")
    if lipo.get("alogp"):
        bits.append(f"logP={lipo['alogp']}")
    if psa.get("psa"):
        bits.append(f"PSA={psa['psa']}")
    if hb.get("hbd") is not None:
        bits.append(f"HBD={hb['hbd']},HBA={hb.get('hba')}")
    if dl.get("ro5_violations") is not None:
        bits.append(f"RO5违规={dl['ro5_violations']}")
    return "; ".join(bits) or (text or "").strip()[:300]


def _summ_targets(text: Optional[str]) -> str:
    d = _j(text)
    if isinstance(d, dict):
        acts = d.get("activities") or d.get("results") or []
        if isinstance(acts, list):
            names = []
            for a in acts[:6]:
                if isinstance(a, dict):
                    n = _first(a, "target_pref_name", "target_chembl_id", "target_name")
                    if n:
                        names.append(n)
            if names:
                return "; ".join(names)
    return ""


class ChemblMCPClient:
    _instance: Optional["ChemblMCPClient"] = None

    def __init__(self) -> None:
        self._session: Optional[ClientSession] = None
        self._ctx: Optional[Any] = None  # stdio_client 上下文，由生命周期 task 持有
        self._tools: dict[str, Any] = {}
        self._lock = asyncio.Lock()
        self._life: Optional[asyncio.Task] = None  # 生命周期后台任务
        self._ready = asyncio.Event()
        self._shutdown = asyncio.Event()
        self._init_error: Optional[Exception] = None
        s = get_settings()
        self.enabled: bool = bool(s.chembl_mcp_enabled)
        self.timeout: int = int(s.chembl_mcp_timeout) or 15

    @classmethod
    def instance(cls) -> "ChemblMCPClient":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _resolve_server_js(self) -> Path:
        p = Path(get_settings().chembl_mcp_server_js)
        if not p.is_absolute():
            backend_root = Path(__file__).resolve().parent.parent.parent
            p = backend_root / p
        return p

    async def _lifecycle(self, params: StdioServerParameters) -> None:
        """在专用后台 task 内持有 stdio_client 生命周期。

        anyio 要求 cancel scope 的 enter/exit 必须在同一 task，而速查工具/服务请求
        通过 asyncio.wait_for 等机制在别的 task 调用本客户端——若由调用方直接
        __aexit__ 会触发 "Attempted to exit cancel scope in a different task"。
        因此 enter/exit 全部放在本 task 内，close 仅通过 _shutdown 事件驱动。
        """
        ctx = stdio_client(params)
        session: Optional[ClientSession] = None
        try:
            read, write = await ctx.__aenter__()
            session = ClientSession(read, write)
            await session.__aenter__()
            await session.initialize()
            tools = await session.list_tools()
            self._session = session
            self._ctx = ctx
            self._tools = {t.name: t for t in tools.tools}
            logger.info(f"[chembl_mcp] 已连接，工具数={len(self._tools)}")
            self._ready.set()
        except Exception as e:  # noqa
            logger.warning(f"[chembl_mcp] 初始化失败: {e}")
            self._init_error = e
            self._ready.set()
            try:
                await ctx.__aexit__(None, None, None)
            except Exception:  # noqa
                pass
            return
        try:
            # 保持生命周期直到被请求关闭
            while not self._shutdown.is_set():
                await asyncio.sleep(0.25)
        finally:
            try:
                if session is not None:
                    await session.__aexit__(None, None, None)
            except Exception as e:  # noqa
                logger.warning(f"[chembl_mcp] 关闭 session 异常: {e}")
            self._session = None
            self._tools = {}
            try:
                # Windows 下 stdio_client 内部用 Job Object（KILL_ON_JOB_CLOSE），
                # __aexit__ 会 terminate() 子进程并 wait()，可可靠终止 node，避免进程泄漏。
                await ctx.__aexit__(None, None, None)
            except Exception as e:  # noqa
                logger.warning(f"[chembl_mcp] 关闭 stdio 上下文异常: {e}")
            self._ctx = None

    async def _ensure(self) -> None:
        async with self._lock:
            if self._session is not None:
                return
            server_js = self._resolve_server_js()
            if not server_js.exists():
                raise FileNotFoundError(f"ChEMBL MCP server 未找到: {server_js}")
            params = StdioServerParameters(command="node", args=[str(server_js)])
            self._ready = asyncio.Event()
            self._shutdown = asyncio.Event()
            self._init_error = None
            self._life = asyncio.create_task(self._lifecycle(params))
            try:
                await asyncio.wait_for(self._ready.wait(), timeout=30)
            except asyncio.TimeoutError:
                logger.warning("[chembl_mcp] 连接超时，终止生命周期任务")
                await self._reset()
                raise ConnectionError("ChEMBL MCP 连接超时（30s）")
            if self._init_error is not None:
                err = self._init_error
                await self._reset()
                raise err

    async def _reset(self) -> None:
        async with self._lock:
            life = self._life
            self._life = None
            if life is not None and not life.done():
                self._shutdown.set()
                try:
                    await asyncio.wait_for(life, timeout=15)
                except asyncio.TimeoutError:
                    logger.warning("[chembl_mcp] 生命周期任务未在 15s 内退出，强制取消")
                    life.cancel()
            self._ready = asyncio.Event()
            self._shutdown = asyncio.Event()
            self._init_error = None
            self._session = None
            self._tools = {}
            self._ctx = None

    async def _call(self, name: str, values: dict) -> Optional[str]:
        tool = self._tools.get(name)
        if not tool:
            return None
        props = (getattr(tool, "inputSchema", None) or {}).get("properties", {}) or {}
        args = {k: v for k, v in values.items() if k in props and v is not None}
        if not args:
            logger.warning(f"[chembl_mcp] 工具 {name} 无可装配参数（传入 {list(values)}），跳过")
            return None
        result = await asyncio.wait_for(
            self._session.call_tool(name, args), timeout=self.timeout
        )
        return _content_text(result)

    async def _safe_call(self, name: str, **values) -> Optional[str]:
        try:
            await self._ensure()
            return await self._call(name, values)
        except Exception as e:  # noqa
            logger.warning(f"[chembl_mcp] 调用 {name} 失败: {e}")
            return None

    async def search_full(self, query: str) -> str:
        """编排多个 MCP 工具，返回中文结构化摘要文本（供 _extract_chembl_fields 解析）。"""
        await self._ensure()
        # 1. 定位化合物（多级回退：search_compounds → search_drugs → 直查 ID → 批量查询）
        chembl_id, pref_name = None, None
        conn_failed = False
        for name, args in (
            ("search_compounds", {"query": query, "limit": 3}),
            ("search_drugs", {"query": query, "limit": 3}),
        ):
            txt = await self._safe_call(name, **args)
            if txt is None:
                conn_failed = True  # 调用失败（连接/服务端错误），后续重连一次
                continue
            chembl_id, pref_name = _parse_search_compounds(txt)
            if chembl_id:
                break
        if not chembl_id and re.fullmatch(r"CHEMBL\d+", query, re.IGNORECASE):
            # 查询本身就是 ChEMBL ID：直接拉取验证存在性
            ci = await self._safe_call("get_compound_info", chembl_id=query.upper())
            if ci:
                chembl_id, pref_name = query.upper(), _parse_info_name(ci)
        if not chembl_id:
            # 最后尝试批量 ID 查询（兼容 CAS/别名模糊命中）
            bc = await self._safe_call("batch_compound_lookup", chembl_ids=[query])
            chembl_id, pref_name = _parse_search_compounds(bc)
        if not chembl_id and conn_failed:
            # 连接级失败（非查询无果）：重连一次后重试
            await self._reset()
            txt = await self._safe_call("search_compounds", query=query, limit=3)
            if txt:
                chembl_id, pref_name = _parse_search_compounds(txt)
        if not chembl_id:
            # 无法定位化合物（连接失败或查询无果），交回 REST 兜底，避免返回空壳
            return ""

        smiles = None
        if chembl_id:
            smiles = _parse_smiles(await self._safe_call("get_compound_structure", chembl_id=chembl_id, format="smiles"))

        # 2. 并行深度检索
        tasks: dict[str, Any] = {}
        if chembl_id:
            for t in _DEPTH_BY_ID:
                if t == "search_activities":
                    tasks[t] = self._safe_call(t, molecule_chembl_id=chembl_id, limit=15)
                else:
                    tasks[t] = self._safe_call(t, chembl_id=chembl_id)
            if smiles:
                for t in _DEPTH_NEED_SMILES:
                    tasks[t] = self._safe_call(t, chembl_id=chembl_id, smiles=smiles)

        results: dict[str, Optional[str]] = {}
        if tasks:
            done = await asyncio.gather(*tasks.values(), return_exceptions=True)
            for k, r in zip(tasks.keys(), done):
                results[k] = r if not isinstance(r, Exception) else None

        # 3. 组装摘要
        lines = ["## ChEMBL 深度数据"]
        if chembl_id:
            lines.append(f"- ChEMBL ID: {chembl_id}")
        if pref_name:
            lines.append(f"- 规范名称: {pref_name}")
        if smiles:
            lines.append(f"- SMILES: {smiles}")
        moa = _summ_moa(results.get("get_mechanism_of_action"))
        if moa:
            lines.append(f"- 作用机制(MOA): {moa}")
        act = _summ_activities(results.get("search_activities"))
        if act:
            lines.append(f"- 生物活性: {act}")
        targets = _summ_targets(results.get("search_activities"))
        if targets:
            lines.append(f"- 分子靶点: {targets}")
        admet = _summ_admet(results.get("analyze_admet_properties"))
        if admet:
            lines.append(f"- ADMET/理化性质: {admet}")
        sol = _summ_sol(results.get("predict_solubility"))
        if sol:
            lines.append(f"- 溶解度: {sol}")
        dl = _summ_dl(results.get("assess_drug_likeness"))
        if dl:
            lines.append(f"- 类药性: {dl}")
        desc = _summ_desc(results.get("calculate_descriptors"))
        if desc:
            lines.append(f"- 分子描述符: {desc}")
        info = _summ_info(results.get("get_compound_info"))
        if info:
            lines.append(f"- 化合物信息: {info}")
        xref = _summ_xref(results.get("get_external_references"))
        if xref:
            lines.append(f"- 外部交叉引用: {xref}")
        drug = _summ_drug(results.get("get_drug_info"))
        if drug:
            lines.append(f"- 药物研发: {drug}")
        return "\n".join(lines)

    async def close(self) -> None:
        await self._reset()


async def close_client() -> None:
    if ChemblMCPClient._instance is not None:
        await ChemblMCPClient._instance.close()
        ChemblMCPClient._instance = None
