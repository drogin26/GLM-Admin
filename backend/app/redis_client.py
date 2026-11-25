"""Redis-клиент (asyncio): кеш, лимиты, WebSocket-события виджета (итерация 6)."""

from __future__ import annotations

import redis.asyncio as aioredis
from redis.asyncio import Redis

from app.config import Settings


def make_redis(settings: Settings) -> Redis:
    return aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
        health_check_interval=30,
    )
