# -*- coding: utf-8 -*-
"""上下文预算分配工具。

用于检索结果注入 LLM 时的动态预算控制：
- 单源上限（per_source_max）与总预算（total_budget）双约束
- 源数少 → 单源可接近 per_source_max
- 源数多 → 均摊 total_budget，防止总注入越界
- 总预算是硬约束，保底是软约束（预算不足时保底让位）
"""

MIN_FLOOR_CHARS = 800  # 单源注入保底字符数


def allocate_per_source_chars(
    source_count: int, total_budget: int, per_source_max: int
) -> int:
    """按源数动态分配单源注入字符数。

    Args:
        source_count: 检索结果源数（已成功返回结果的源）
        total_budget: 单次注入 LLM 的总字符预算
        per_source_max: 单源注入字符上限

    Returns:
        分配给每个源的最大注入字符数（>= 1）
    """
    if source_count <= 0:
        return per_source_max
    share = total_budget // source_count
    if share < MIN_FLOOR_CHARS:
        # 总预算不足时硬约束优先，保底让位（避免极端多源时总注入越界）
        return max(share, 1)
    return min(per_source_max, share)


_ELLIPSIS = "\n…[内容截断]"


def truncate_with_ellipsis(text: str, max_chars: int) -> str:
    """按字符数截断（换行边界优先），超长追加省略号，总长度 <= max_chars。

    - 截断点向前找最近的换行符，避免切断段落
    - 省略号计入 max_chars，保证硬上限精确
    """
    if not text or len(text) <= max_chars:
        return text
    budget = max(max_chars - len(_ELLIPSIS), 1)
    cut = text[:budget]
    nl = cut.rfind("\n")
    if nl > budget // 2:
        cut = cut[:nl]
    return cut.rstrip() + _ELLIPSIS
