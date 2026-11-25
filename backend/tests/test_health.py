"""Тесты healthcheck и жизненного цикла приложения."""

from __future__ import annotations

import httpx

from app.config import Settings
from app.main import create_app

pytestmark = pytest.mark.asyncio(loop_scope="session")  # общий session-loop с движками из conftest



async def test_healthz(client):
    response = await client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"]


async def test_readyz_ok(client):
    response = await client.get("/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"] == {"db": True, "redis": True}


async def test_readyz_degraded_on_redis_failure():
    settings = Settings(redis_url="redis://127.0.0.1:59999/9")  # порт закрыт
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            response = await c.get("/readyz")
    assert response.status_code == 503
    body = response.json()
    assert body["detail"]["checks"]["redis"] is False
    assert body["detail"]["checks"]["db"] is True


async def test_request_id_header(client):
    response = await client.get("/healthz", headers={"X-Request-Id": "my-rid-1"})
    assert response.headers.get("x-request-id") == "my-rid-1"


async def test_request_id_generated(client):
    response = await client.get("/healthz")
    assert len(response.headers.get("x-request-id", "")) == 16
