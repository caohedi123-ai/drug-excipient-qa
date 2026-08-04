"""检索档位定义：flash（速度优先）→ pro（质量优先，默认）。

各档位映射影响任务时长的全部参数。balanced 与 config.py 默认值一致，作为回归基准。
"""

from __future__ import annotations

# 档位 -> 参数覆盖字典（键名与 config.py 字段一致）
TIERS: dict[str, dict[str, int]] = {
    "flash": {
        "max_retrieval_rounds": 1,
        "retrieval_max_chars_per_source": 2000,
        "retrieval_max_total_chars": 40000,
        "retrieval_max_store_chars": 4000,
        "history_inject_rounds": 0,
        "history_compress_rounds": 8,
        "history_max_total_chars": 1500,
        "history_smart_truncate_chars": 80,
    },
    "fast": {
        "max_retrieval_rounds": 2,
        "retrieval_max_chars_per_source": 4000,
        "retrieval_max_total_chars": 80000,
        "retrieval_max_store_chars": 6000,
        "history_inject_rounds": 1,
        "history_compress_rounds": 6,
        "history_max_total_chars": 3000,
        "history_smart_truncate_chars": 120,
    },
    "balanced": {
        "max_retrieval_rounds": 3,
        "retrieval_max_chars_per_source": 8000,
        "retrieval_max_total_chars": 200000,
        "retrieval_max_store_chars": 12000,
        "history_inject_rounds": 2,
        "history_compress_rounds": 4,
        "history_max_total_chars": 6000,
        "history_smart_truncate_chars": 200,
    },
    "quality": {
        "max_retrieval_rounds": 4,
        "retrieval_max_chars_per_source": 10000,
        "retrieval_max_total_chars": 300000,
        "retrieval_max_store_chars": 16000,
        "history_inject_rounds": 2,
        "history_compress_rounds": 3,
        "history_max_total_chars": 8000,
        "history_smart_truncate_chars": 260,
    },
    "pro": {
        "max_retrieval_rounds": 5,
        "retrieval_max_chars_per_source": 12000,
        "retrieval_max_total_chars": 400000,
        "retrieval_max_store_chars": 20000,
        "history_inject_rounds": 3,
        "history_compress_rounds": 3,
        "history_max_total_chars": 10000,
        "history_smart_truncate_chars": 320,
    },
}

DEFAULT_TIER = "pro"

TIER_ORDER = ["flash", "fast", "balanced", "quality", "pro", "custom"]

# 前端展示标签
TIER_LABELS: dict[str, str] = {
    "flash": "Flash · 极速",
    "fast": "Fast · 快速",
    "balanced": "Balanced · 均衡",
    "quality": "Quality · 高质量",
    "pro": "Pro · 深度检索",
    "custom": "自定义",
}


def resolve_tier(tier: str | None, custom: dict | None = None) -> dict[str, int]:
    """将档位解析为参数覆盖字典。

    - tier 为预设档位 → 返回预设映射
    - tier 为 custom → 使用传入的 custom 参数（仅取白名单内合法键）
    - 未知/空 → 默认 pro
    """
    if tier in TIERS:
        return dict(TIERS[tier])
    if tier == "custom":
        from settings_service import RETRIEVAL_KEYS

        overrides = {}
        for key in RETRIEVAL_KEYS:
            val = (custom or {}).get(key)
            if isinstance(val, int) and val > 0:
                overrides[key] = val
        if overrides:
            return overrides
        # 无自定义参数 → 回退默认
        return dict(TIERS[DEFAULT_TIER])
    return dict(TIERS[DEFAULT_TIER])
