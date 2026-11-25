"""Middleware: rate limiting для webhook-эндпоинтов.

Ограничивает частоту запросов к webhook-маршрутам (Telegram/VK),
чтобы защитить от DDoS и спама.

Используется Redis для хранения состояния (count + window).
"""

from __future__ import annotations

import time
import typing as t
from collections import defaultdict

import logging

logger = logging.getLogger(__name__)


class RateLimiter:
    """Simple sliding-window rate limiter на Redis."""

    def __init__(self, redis_client: t.Any, default_limit: int = 60, window_seconds: int = 60) -> None:  # noqa: ANN401
        self._redis = redis_client
        self.default_limit = default_limit
        self.window = window_seconds

    async def is_allowed(self, key: str, limit: int | None = None, window: int | None = None) -> bool:
        """Проверить, не превышен ли лимит для ключа.

        Returns:
            True если запрос разрешён, False если превышен лимит.
        """
        if self._redis is None:
            return True  # Redis недоступен — пропускаем (fail-open)

        limit = limit or self.default_limit
        window = window or self.window
        now = time.time()
        window_key = f"ratelimit:{key}:{int(now // window)}"

        try:
            pipe = self._redis.pipeline()
            pipe.incr(window_key)
            pipe.expire(window_key, window + 1)
            results = await pipe.execute()

            current_count = results[0]
            if current_count > limit:
                logger.warning("rate_limit_exceeded", extra={"key": key, "count": current_count, "limit": limit})
                return False
            return True
        except Exception:
            # При ошибке Redis — пропускаем (fail-open)
            logger.warning("rate_limit_redis_error", extra={"key": key})
            return True


def get_rate_limiter(redis_client: t.Any) -> RateLimiter:  # noqa: ANN401
    return RateLimiter(redis_client)


__all__ = ["RateLimiter", "get_rate_limiter"]
