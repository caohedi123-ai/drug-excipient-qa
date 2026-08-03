# -*- coding: utf-8 -*-
"""多轮对话历史注入工具。

解决尽调报告中多轮对话 4 项短板：
#1 会话摘要压缩（滚动压缩早期轮次，注入端节省 token）
#2 注入窗口可配置（history_inject_rounds）+ 会话级实体记忆（entity_memory）
#3 智能截断（smart_truncate，保留数值/实体、词边界不切断）
#7 历史总预算钳制（history_max_total_chars，优先保留最近内容）
"""

import re
from typing import Any, Dict, List, Optional, Tuple

# ---------- #3 智能截断 ----------

# 数值+单位模式，用于保护关键数值不被截断
_NUMERIC_UNIT_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:mg|g|mL|ml|L|μg|ug|%|kDa|℃|°C|K|Pa|h|min|mg/mL|mg/ml)\b"
)
# 句子边界（含中文标点、换行）
_SENTENCE_BOUNDARY_RE = re.compile(r"[。．.!?！？；;\n]")
# 英文词边界（字母数字与其它字符的交界）
_WORD_BOUNDARY_RE = re.compile(r"[a-zA-Z0-9][^a-zA-Z0-9]|[^a-zA-Z0-9][a-zA-Z0-9]")


def smart_truncate(text: str, max_chars: int = 200) -> str:
    """智能截断：优先句边界、不切断英文词、尽量保留数值单位，总长 <= max_chars。

    Args:
        text: 待截断文本
        max_chars: 最大字符数（省略号计入预算）

    Returns:
        截断后文本（<= max_chars 时原样返回）
    """
    if not text:
        return ""
    if len(text) <= max_chars:
        return text

    _ELLIPSIS = "…"
    budget = max(max_chars - len(_ELLIPSIS), 1)  # 省略号计入预算

    # 1) 尝试数值保护：若关键数值起始位置在前 85%，前移到该数值所在句子结束
    for m in _NUMERIC_UNIT_RE.finditer(text):
        if m.start() < budget * 0.85 and m.start() < budget:
            # 找数值之后最近的句边界
            after = text[m.end():]
            b = _SENTENCE_BOUNDARY_RE.search(after)
            if b:
                cut = m.end() + b.end()
                if cut <= budget and cut > budget * 0.5:
                    return text[:cut].rstrip() + _ELLIPSIS
            break

    # 2) 在 [budget-60, budget] 窗口内从后往前找句边界（回退量 <= 60）
    window_start = max(0, budget - 60)
    seg = text[window_start:budget]
    last_match = None
    for m in _SENTENCE_BOUNDARY_RE.finditer(seg):
        last_match = m
    if last_match:
        return text[: window_start + last_match.end()].rstrip() + _ELLIPSIS

    # 3) 词边界保护：在 budget 处向前找英文词边界
    near = text[budget - 12 : budget + 1]
    for m in _WORD_BOUNDARY_RE.finditer(near):
        cut = budget - 12 + m.start() + 1
        if cut < budget:
            return text[:cut].rstrip() + _ELLIPSIS

    # 4) 兜底：硬截断
    return text[:budget].rstrip() + _ELLIPSIS


# ---------- #1 会话摘要压缩 ----------

def should_compress(
    message_count: int, compress_rounds: int, compressed_this_round: bool
) -> bool:
    """是否触发摘要压缩。

    触发条件：消息条数超过 2*compress_rounds + 2 且本轮尚未压缩。
    """
    if compressed_this_round:
        return False
    return message_count > 2 * compress_rounds + 2


def build_summary_fallback(messages: List[Any], summary_rounds: int, max_chars: int = 1200) -> str:
    """LLM 摘要失败的降级：取最旧轮次截断拼接。"""
    if not messages:
        return ""
    parts = []
    for m in messages[: max(2, 2 * summary_rounds)]:
        content = getattr(m, "content", "") or (m.get("content", "") if isinstance(m, dict) else "")
        if content:
            parts.append(smart_truncate(str(content), 200))
    if not parts:
        return ""
    text = "；".join(parts)
    return text[:max_chars]


def summarize_oldest(
    messages: List[Any],
    llm: Any,
    existing_summary: str = "",
    summary_rounds: int = 0,
) -> Tuple[str, int]:
    """用 LLM 对最早轮次生成/滚动摘要，返回 (new_summary, new_rounds)。

    LLM 失败时降级为字符串拼接，不影响主流程。
    """
    if not messages:
        return existing_summary, summary_rounds

    oldest = messages[:2]  # 最早 1 轮（user + assistant）
    oldest_text = "\n".join(
        str(getattr(m, "content", "") or (m.get("content", "") if isinstance(m, dict) else ""))
        for m in oldest
        if m
    )
    if not oldest_text and not existing_summary:
        return existing_summary, summary_rounds

    prompt = (
        "你是会话摘要助手。请把【已有摘要】与【新增对话】合并成一段新的会话摘要。\n"
        "要求：1) 保留所有药物/辅料实体名（中英文）、剂量数值、结论与关键引用；"
        "2) 简明扼要，不超过 500 字；3) 只输出摘要正文，不要任何解释。\n"
        f"【已有摘要】\n{existing_summary or '（无）'}\n\n"
        f"【新增对话】\n{smart_truncate(oldest_text, 1500)}"
    )
    try:
        resp = llm.invoke(prompt)
        new_summary = getattr(resp, "content", None) or str(resp)
        new_summary = new_summary.strip()
        if not new_summary or "只输出摘要正文" in new_summary:
            raise ValueError("empty summary")
    except Exception:
        new_summary = build_summary_fallback(messages, summary_rounds + 1)
        if existing_summary:
            new_summary = existing_summary + "\n" + new_summary

    # 新摘要 = 已有摘要 + 新内容（滚动合并），限制长度
    if existing_summary and new_summary.startswith(existing_summary):
        combined = new_summary
    else:
        combined = (existing_summary + "\n" + new_summary).strip()
    if len(combined) > 3000:
        combined = combined[-3000:]
    return combined, summary_rounds + 1


# ---------- #7 历史总预算钳制 ----------

_HIST_ELLIPSIS = "\n…[历史省略]\n"


def apply_total_budget(text: str, total_budget: int, keep_head_ratio: float = 0.2) -> str:
    """对历史注入文本做总字符预算钳制。

    优先保留最近内容：超限时先裁尾部（旧内容），再裁头部（摘要）保底 20%。
    省略标记计入预算，保证总长 <= total_budget。
    """
    if not text or len(text) <= total_budget:
        return text
    budget = max(total_budget - len(_HIST_ELLIPSIS), 1)
    keep_head = int(budget * keep_head_ratio)
    tail = text[- (budget - keep_head):]
    return text[:keep_head] + _HIST_ELLIPSIS + tail


# ---------- #2 实体记忆 ----------

def update_entity_memory(
    entity_memory: Dict[str, Dict[str, Any]],
    entities_en: Optional[List[str]],
    entities_zh: Optional[List[str]],
    round_no: int,
) -> Dict[str, Dict[str, Any]]:
    """更新会话级实体记忆。

    以英文名为 key，合并中英文别名；中英同名或 LLM 别名不可用时按原名保存。
    """
    mem = dict(entity_memory) if entity_memory else {}
    en_list = [e for e in (entities_en or []) if e]
    zh_list = [z for z in (entities_zh or []) if z]

    # 先按英文实体记录
    for name in en_list:
        key = name.lower().strip()
        if not key:
            continue
        entry = mem.get(key, {"aliases": [], "mention_count": 0, "last_round": 0})
        entry["mention_count"] = entry.get("mention_count", 0) + 1
        entry["last_round"] = round_no
        # 中英配对：首个中文名作为英文实体别名（仅当没有同名英文时）
        if zh_list and name.lower() in [z.lower() for z in zh_list]:
            pass  # 中文名即自身别名，不重复添加
        mem[key] = entry

    # 纯中文实体（无对应英文）单独记录
    zh_keys = {k for k in mem}
    for z in zh_list:
        zk = z.lower().strip()
        if not zk:
            continue
        # 若已有英文 key 以该中文为别名，跳过；否则新建
        matched = any(zk in entry.get("aliases", []) for entry in mem.values())
        if matched or zk in zh_keys:
            continue
        entry = mem.get(zk, {"aliases": [], "mention_count": 0, "last_round": 0})
        entry["mention_count"] = entry.get("mention_count", 0) + 1
        entry["last_round"] = round_no
        mem[zk] = entry

    # 限制内存上限：最多保留 50 个实体，超出时淘汰最久未提及的
    if len(mem) > 50:
        sorted_keys = sorted(mem, key=lambda k: (mem[k].get("last_round", 0), mem[k].get("mention_count", 0)))
        for k in sorted_keys[: len(mem) - 50]:
            del mem[k]
    return mem


def entity_memory_prompt(entity_memory: Dict[str, Dict[str, Any]], limit: int = 8) -> str:
    """生成注入历史时附加的会话实体清单文本。"""
    if not entity_memory:
        return ""
    items = sorted(
        entity_memory.items(),
        key=lambda kv: (kv[1].get("mention_count", 0), kv[1].get("last_round", 0)),
        reverse=True,
    )[:limit]
    lines = []
    for key, entry in items:
        aliases = entry.get("aliases", [])
        alias_txt = ("/" + "/".join(aliases)) if aliases else ""
        lines.append(f"{key}{alias_txt}(提及{entry.get('mention_count', 0)}次)")
    return "本会话此前讨论过的实体：" + "、".join(lines) + "。"
