"""用户配置覆盖服务：支持运行时修改 API key 与检索参数。

存储：backend/user_settings.json（与 .env 同目录），JSON 格式：
{
  "api_keys": {"deepseek_api_key": "...", "tavily_api_key": "...", "anysearch_api_key": "..."},
  "retrieval": {"max_retrieval_rounds": 5, ...}
}

- 默认值来自 .env / config.py，仅在用户显式配置后覆盖。
- 启动时 load_overrides() 将已保存配置写入 settings 单例（模块级引用即时生效）。
- 掩码仅用于展示层，传输与落盘为明文（本地单机部署场景）。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from config import get_settings

logger = logging.getLogger(__name__)

# 与 config.py 中字段保持一致的白名单
API_KEY_KEYS = ("deepseek_api_key", "tavily_api_key", "anysearch_api_key")
RETRIEVAL_KEYS = (
    "max_retrieval_rounds",
    "retrieval_max_chars_per_source",
    "retrieval_max_total_chars",
    "retrieval_max_store_chars",
    "history_inject_rounds",
    "history_compress_rounds",
    "history_max_total_chars",
    "history_smart_truncate_chars",
)

BASE_DIR = Path(__file__).resolve().parent
USER_SETTINGS_FILE = BASE_DIR / "user_settings.json"


def _read_file() -> dict[str, Any]:
    if not USER_SETTINGS_FILE.exists():
        return {}
    try:
        data = json.loads(USER_SETTINGS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取 user_settings.json 失败: %s", exc)
        return {}


def _write_file(data: dict[str, Any]) -> None:
    USER_SETTINGS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def mask(value: str | None) -> str:
    """掩码：sk-xxxx****abcd；空或过短则全掩码/空串。"""
    if not value:
        return ""
    if len(value) < 8:
        return "*" * len(value)
    return f"{value[:4]}****{value[-4:]}"


def load_overrides() -> None:
    """启动时加载已保存的用户配置，覆盖 settings 单例（幂等，可重复调用）。"""
    data = _read_file()
    settings = get_settings()
    api_keys = data.get("api_keys") or {}
    for key in API_KEY_KEYS:
        val = api_keys.get(key)
        if isinstance(val, str) and val.strip():
            setattr(settings, key, val.strip())
            logger.info("用户配置覆盖 %s 已生效", key)
    retrieval = data.get("retrieval") or {}
    for key in RETRIEVAL_KEYS:
        val = retrieval.get(key)
        if val is not None:
            setattr(settings, key, val)


def get_masked_api_keys() -> dict[str, dict[str, Any]]:
    settings = get_settings()
    result = {}
    for key in API_KEY_KEYS:
        val = getattr(settings, key, "") or ""
        result[key] = {"masked": mask(val), "configured": bool(val)}
    return result


def get_retrieval_params() -> dict[str, Any]:
    settings = get_settings()
    return {key: getattr(settings, key) for key in RETRIEVAL_KEYS}


def save_api_keys(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """保存 API key。payload[key] 为空串/缺失 = 不改动。"""
    data = _read_file()
    api_keys = data.setdefault("api_keys", {})
    settings = get_settings()
    for key in API_KEY_KEYS:
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            val = val.strip()
            setattr(settings, key, val)
            api_keys[key] = val
    _write_file(data)
    return get_masked_api_keys()


def save_retrieval_params(payload: dict[str, Any]) -> dict[str, Any]:
    """保存检索自定义参数。payload[key] 缺失 = 不改动。"""
    data = _read_file()
    retrieval = data.setdefault("retrieval", {})
    settings = get_settings()
    for key in RETRIEVAL_KEYS:
        val = payload.get(key)
        if isinstance(val, int) and val > 0:
            setattr(settings, key, val)
            retrieval[key] = val
    _write_file(data)
    return get_retrieval_params()
