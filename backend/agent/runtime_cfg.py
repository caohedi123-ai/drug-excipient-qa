"""请求级检索参数覆盖（ContextVar）。

多会话并发时每个请求（asyncio task 链）拥有独立 context，
set_runtime/reset_runtime 仅在当前请求范围内生效，不会串会话。
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

_runtime: ContextVar[dict[str, Any] | None] = ContextVar("retrieval_runtime", default=None)


def set_runtime(overrides: dict[str, Any] | None):
    """设置当前请求的覆盖参数，返回 token（用于 finally 中 reset）。"""
    return _runtime.set(overrides)


def reset_runtime(token) -> None:
    _runtime.reset(token)


def get_param(name: str, default: Any) -> Any:
    """优先读取请求级覆盖，否则回退默认值。"""
    ov = _runtime.get()
    if ov and name in ov:
        return ov[name]
    return default
