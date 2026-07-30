"""数据库连接管理 - PostgreSQL (async) + Redis"""

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import create_engine
from redis.asyncio import Redis as AsyncRedis
from config import get_settings

settings = get_settings()

# === PostgreSQL (async - 用于 FastAPI/LangGraph) ===
async_engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# === PostgreSQL (sync - 用于 LangGraph checkpoint) ===
sync_engine = create_engine(
    settings.database_url_sync,
    echo=False,
    pool_size=5,
    max_overflow=5,
    pool_pre_ping=True,
)

# === Redis (async) ===
redis_client: AsyncRedis = None  # type: ignore


async def get_db() -> AsyncSession:
    """FastAPI 依赖注入：获取异步数据库会话"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_redis():
    """初始化 Redis 连接"""
    global redis_client
    redis_client = AsyncRedis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
    )
    await redis_client.ping()
    return redis_client


async def close_redis():
    """关闭 Redis 连接"""
    global redis_client
    if redis_client:
        await redis_client.close()
        redis_client = None
