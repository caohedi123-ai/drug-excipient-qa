"""全局配置管理，从 .env 加载所有环境变量"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # LLM
    deepseek_api_key: str
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-v4-flash"

    # Tavily (精搜)
    tavily_api_key: str

    # AnySearch (泛搜)
    anysearch_api_key: str

    # Exa (深研 Phase 2)
    exa_api_key: str = ""

    # PostgreSQL
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/pharma_kb"
    database_url_sync: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/pharma_kb"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Server
    host: str = "0.0.0.0"
    port: int = 18082
    debug: bool = False

    # Agent
    max_retrieval_rounds: int = 3

    # 检索结果上下文预算（动态分配双约束）
    retrieval_max_chars_per_source: int = 8000      # 单源注入 LLM 上限（字符）
    retrieval_max_total_chars: int = 200000         # 单次评估/合成注入总预算（字符）
    retrieval_max_store_chars: int = 12000          # 状态层单源存储上限（字符）

    # 多轮对话历史注入（尽调报告 3.2 短板修复）
    history_inject_rounds: int = 2                  # understand/evaluate 注入最近轮数
    history_compress_rounds: int = 4                # 超过 2*N+2 条消息触发摘要压缩
    history_max_total_chars: int = 6000             # 历史注入（含摘要）总字符预算
    history_smart_truncate_chars: int = 200         # 历史单条消息注入截断字符数

    # ChEMBL MCP（P0.4 重点）：默认关闭，调试/灰度时开启；任何失败自动降级现有 REST
    chembl_mcp_enabled: bool = False
    chembl_mcp_timeout: int = 15          # 单工具调用超时（秒）
    chembl_mcp_server_js: str = "mcp/ChEMBL-MCP-Server/build/index.js"  # 相对 backend 根目录

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
