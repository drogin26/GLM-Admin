"""Async-слой доступа к PostgreSQL для API (asyncpg).

Движок и фабрика сессий создаются в lifespan приложения и живут в
`app.state` — это упрощает тесты (каждое приложение со своими зависимостями).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings


def make_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.async_db_url,
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=10,
        max_overflow=20,
        connect_args={"server_settings": {"application_name": "aiadmin-api", "timezone": "UTC"}},
    )


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(request_state_session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    """Сессия на запрос; rollback при ошибке."""
    async with request_state_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
