"""PostgreSQL AsyncSession"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

class Base(DeclarativeBase):
    """所有 ORM 实体共享同一个 metadata"""

# pool_pre_ping 在连接池取连接前 探测 PostgreSQL， 避免空闲连接失败。
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
# 一个请求一个 Session；提交后对象不失效，便于继续读取刚写入的字段。
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    # Depends(get_db) 进入这里，并在响应结束后回到 yield 后的逻辑
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()      # 正常路径提交事务
        except Exception:
            await session.rollback()    # 任意异常都回滚，防止半条工单入库
            raise

async def init_db() -> None:
    """学习环境快速建表，生产环境改为 Alembic migration。"""
    # run_async 把同步 metadata API 安全地桥接到异步连接。
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all())

