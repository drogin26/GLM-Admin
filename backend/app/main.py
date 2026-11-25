"""Точка входа FastAPI-приложения."""

from __future__ import annotations

import asyncio
import signal
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import logging
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import cabinet, health, webhooks, widget
from app.config import Settings, get_settings
from app.db import make_engine, make_session_factory
from app.log import new_request_id, request_id_var, setup_logging
from app.redis_client import make_redis


class RequestContextMiddleware:
    """Простой ASGI-middleware: request_id в контексте логов, access-log с длительностью."""

    def __init__(self, app: FastAPI) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: object, send: object) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)  # type: ignore[call-arg]
            return

        import logging as _logging

        from starlette.datastructures import MutableHeaders

        headers = dict(scope.get("headers") or [])
        raw_rid = headers.get(b"x-request-id")
        rid = (raw_rid or new_request_id().encode()).decode("ascii", errors="replace")[:64]
        token = request_id_var.set(rid)
        started = time.monotonic()
        status_holder = {"status": 0}

        async def send_wrapper(message: dict) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                MutableHeaders(scope=message).append("x-request-id", rid)
            if callable(send):
                await send(message)  # type: ignore[call-arg]

        try:
            await self.app(scope, receive, send_wrapper)  # type: ignore[call-arg]
        finally:
            duration_ms = round((time.monotonic() - started) * 1000)
            _logging.getLogger("aiadmin.http").info(
                "http_request",
                extra={
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "status": status_holder["status"],
                    "duration_ms": duration_ms,
                },
            )
            request_id_var.reset(token)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    engine = make_engine(settings)
    app.state.session_factory = make_session_factory(engine)
    app.state.redis = make_redis(settings)

    # Регистрируем graceful shutdown
    _register_shutdown_handlers(app)

    if settings.app_env == "prod":
        # Fail fast: если зависимости недоступны — контейнер перезапустится (restart policy).
        async with app.state.session_factory() as session:
            await session.execute(sa.text("SELECT 1"))
        await app.state.redis.ping()

    logger = logging.getLogger("aiadmin.lifespan")
    logger.info("application_started", extra={"version": settings.app_version, "env": settings.app_env})

    yield

    logger.info("application_shutting_down")
    await app.state.redis.aclose()
    await engine.dispose()
    logger.info("application_stopped")


def _register_shutdown_handlers(app: FastAPI) -> None:
    """Регистрируем обработчики SIGTERM/SIGINT для graceful shutdown."""
    loop = asyncio.get_event_loop()

    def _handle_signal(sig: signal.Signals) -> None:
        logger = logging.getLogger("aiadmin.shutdown")
        logger.info("shutdown_signal_received", extra={"signal": sig.name})

        # Отменяем все background tasks
        for task in asyncio.all_tasks(loop):
            task.cancel()

        # Останавливаем сервер
        shutdown_event: Any = getattr(app, "_shutdown_event", None)
        if shutdown_event and callable(shutdown_event):
            shutdown_event()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _handle_signal, sig)
        except (NotImplementedError, RuntimeError):
            # Windows не поддерживает add_signal_handler
            pass


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level, settings.log_json)

    app = FastAPI(
        title="AI-Администратор",
        description="Автоответчик на сообщения: Telegram, ВКонтакте, чат-виджет",
        version=settings.app_version,
        lifespan=lifespan,
    )
    app.state.settings = settings

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.add_middleware(RequestContextMiddleware)

    app.include_router(health.router)
    app.include_router(webhooks.router)
    app.include_router(widget.router)
    app.include_router(cabinet.router, prefix="/api")
    return app


app = create_app()
