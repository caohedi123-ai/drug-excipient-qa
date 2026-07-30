"""集中 Prompt 管理器

工具描述统一委托 tools 模块动态生成（包含全部 30 个工具 + anysearch_fallback 兜底工具），
避免与 tools/__init__.py 的注册表不一致。
"""

from tools import get_tool_descriptions as _get_tool_descriptions


def get_tool_descriptions() -> str:
    """返回全部可用数据源工具描述（含 anysearch_fallback 兜底工具）"""
    return _get_tool_descriptions()
