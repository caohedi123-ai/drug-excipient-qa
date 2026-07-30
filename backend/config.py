"""全局配置管理，从 .env 加载所有环境变量"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # LLM
    deepseek_api_key: str
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"

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

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
