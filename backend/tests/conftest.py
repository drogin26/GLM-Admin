"""Фикстуры: реальный PostgreSQL (pgvector) и Redis из локальной тестовой среды.

Переменные окружения выставляются ДО импорта app.* — конфигурация их читает.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "postgresql://aiadmin:aiadmin@localhost:5433/aiadmin_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6380/1")
os.environ.setdefault("SECRET_KEY", "test-secret-not-for-prod")
os.environ.setdefault("FERNET_KEYS", "GWuGuHxNxdAET-uWqYpRBNvXElttYptJzHGoMCRaJhA=")
os.environ.setdefault("LOG_LEVEL", "WARNING")

import httpx  # noqa: E402
import pytest_asyncio  # noqa: E402
import sqlalchemy as sa  # noqa: E402
from redis.asyncio import Redis  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.config import Settings  # noqa: E402
from app.models import Base  # noqa: E402

TEST_DB_NAME = "aiadmin_test"


def _admin_url() -> str:
    # Подключение к служебной БД postgres для CREATE DATABASE
    base = Settings().async_db_url.rsplit("/", 1)[0]
    return f"{base}/postgres"


@pytest_asyncio.fixture(loop_scope="session")
async def engine():
    admin_engine = create_async_engine(_admin_url(), isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as conn:
        exists = await conn.scalar(
            sa.text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": TEST_DB_NAME}
        )
        if not exists:
            await conn.execute(sa.text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    await admin_engine.dispose()

    engine = create_async_engine(Settings().async_db_url, pool_pre_ping=True)
    async with engine.begin() as conn:
        # pgvector создаётся на каждую БД (миграция делает это для боевой)
        await conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def clean_db(engine):
    yield
    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(sa.text(f'TRUNCATE TABLE "{table.name}" CASCADE'))


@pytest_asyncio.fixture(loop_scope="session")
async def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture(loop_scope="session")
async def redis_client():
    redis = Redis.from_url(Settings().redis_url, decode_responses=True)
    await redis.flushdb()
    yield redis
    await redis.aclose()


@pytest_asyncio.fixture(loop_scope="session")
async def app_instance(session_factory, redis_client):
    from app.main import create_app

    app = create_app(Settings())
    # Тестовые зависимости — не создаём лишний движок
    app.state.session_factory = session_factory
    app.state.redis = redis_client
    async with app.router.lifespan_context(app):
        yield app


@pytest_asyncio.fixture(loop_scope="session")
async def client(app_instance):
    transport = httpx.ASGITransport(app=app_instance)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c
