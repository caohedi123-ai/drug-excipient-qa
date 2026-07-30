"""输入清洗与转义工具 - 处理用户/LLM 构造的检索词边界

用于修复审查报告中"边界处理"角度发现的问题：
- 用户 query 超长 / 含控制字符 / 零宽字符 / emoji 未归一
- openFDA(Lucene) 短语查询未转义导致语法破坏或注入
"""

import re
import unicodedata

# 控制字符（保留 \t \n \r）
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ZERO_WIDTH = ("\u200b", "\u200c", "\u200d", "\ufeff")
# Lucene 短语需转义的特殊字符
_LUCENE_SPECIAL = re.compile(r'([\\"+\-!():^\[\]{}~*?|&/])')

MAX_QUERY_LEN = 512


def sanitize_query(q: str | None, max_len: int = MAX_QUERY_LEN) -> str:
    """NFKC 归一 + 去控制/零宽字符 + 折叠空白 + 长度上限"""
    if not q:
        return ""
    q = unicodedata.normalize("NFKC", str(q))
    for zw in _ZERO_WIDTH:
        q = q.replace(zw, " ")
    q = _CTRL.sub(" ", q)
    q = re.sub(r"\s+", " ", q).strip()
    return q[:max_len]


def escape_openfda_value(v: str) -> str:
    """转义 openFDA/Lucene 短语查询中的特殊字符，避免语法破坏或注入"""
    v = sanitize_query(v)
    return _LUCENE_SPECIAL.sub(r"\\\1", v)
