from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from ..config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def init_engine(database_url: str | None = None, *, null_pool: bool | None = None) -> AsyncEngine:
    global _engine, _sessionmaker
    settings = get_settings()
    url = database_url or settings.database_url
    if null_pool is None:
        null_pool = settings.db_null_pool
    if null_pool:  # tests and serverless: no connections kept across event loops / invocations
        _engine = create_async_engine(url, poolclass=NullPool)
    else:
        _engine = create_async_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=5)
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        init_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency."""
    async with get_sessionmaker()() as session:
        yield session
