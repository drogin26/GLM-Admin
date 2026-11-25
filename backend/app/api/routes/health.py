"""Healthcheck: /healthz — liveness, /readyz — готовность зависимостей."""

from __future__ import annotations

import asyncio
import time
import typing as t

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, Request

from app.config import Settings

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz(request: Request) -> dict[str, str]:
    """Liveness: процесс жив. Зависимости не проверяем — чтобы оркестратор
    не перезапускал контейнер из-за чужого сбоя."""
    settings: Settings = request.app.state.settings
    return {"status": "ok", "version": settings.app_version}


async def _check_db(session_factory: t.Any) -> bool:
    try:
        async with session_factory() as session:
            await session.execute(sa.text("SELECT 1"))
        return True
    except Exception:
        return False


async def _check_redis(redis: t.Any) -> bool:
    try:
        await redis.ping()
        return True
    except Exception:
        return False


@router.get("/readyz")
async def readyz(request: Request) -> dict[str, t.Any]:
    started = time.monotonic()
    db_ok, redis_ok = await asyncio.gather(
        _check_db(request.app.state.session_factory),
        _check_redis(request.app.state.redis),
    )
    checks = {"db": db_ok, "redis": redis_ok}
    payload: dict[str, t.Any] = {
        "status": "ok" if all(checks.values()) else "degraded",
        "checks": checks,
        "elapsed_ms": round((time.monotonic() - started) * 1000),
    }
    if not all(checks.values()):
        raise HTTPException(status_code=503, detail=payload)
    return payload
