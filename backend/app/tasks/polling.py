"""Fallback-поллинг Telegram: Celery beat-задача.

Периодически опрашивает Telegram API для всех активных каналов,
чтобы найти сообщения, потерянные при сбое webhook.

Запускается celery beat каждые 30 секунд (настраивается в celery_app.conf).
Использует Redis для хранения offset каждого канала.
"""

from __future__ import annotations

import logging

from celery import Task

from app.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="polling.telegram_fallback",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def telegram_fallback_poll(self: Task) -> dict[str, int]:
    """Периодический опрос Telegram API (fallback для webhook)."""
    import asyncio
    import uuid as _uuid

    from sqlalchemy import select, text

    from app.db_sync import get_sync_session_factory
    from app.models import Channel, ChannelStatus
    from app.security import decrypt_credentials

    try:
        from app.config import get_settings
        from app.redis_client import make_redis

        settings = get_settings()
        redis = make_redis(settings)

        updated = 0
        with get_sync_session_factory()() as session:
            rows = session.execute(
                text("""
                    SELECT id, credentials_enc
                    FROM channels
                    WHERE type = 'tg'
                      AND status = 'active'
                """)
            ).fetchall()

        if not rows:
            return {"updated": 0, "channels": 0}

        # Асинхронная обработка каналов (HTTP-запросы к Telegram)
        async def _poll_all() -> int:
            from app.services.messaging.telegram import TelegramChannel

            total = 0
            for row in rows:
                ch_id, creds_enc = row
                try:
                    creds = decrypt_credentials(creds_enc, settings.fernet_key_list)
                    token = creds.get("token")
                    if not token:
                        continue

                    class _Channel:
                        id = ch_id
                        credentials_enc = creds_enc

                    channel_obj = _Channel()
                    tg_channel = TelegramChannel(None, redis, settings)  # type: ignore[arg-type]

                    # Fallback poll
                    updates = await tg_channel.fallback_poll(channel_obj)
                    if not updates:
                        continue

                    # Обрабатываем каждое обновление
                    for update in updates:
                        result = await tg_channel.process_incoming(update)
                        if result and result.get("should_respond"):
                            total += 1
                except Exception:
                    logger.exception("fallback_poll_channel_error", extra={"channel_id": str(ch_id)})
                    continue
            return total

        updated = asyncio.new_event_loop().run_until_complete(_poll_all())
        logger.info("telegram_fallback_done", extra={"updated": updated, "channels": len(rows)})
        return {"updated": updated, "channels": len(rows)}
    except Exception as exc:
        logger.exception("telegram_fallback_error")
        raise self.retry(exc=exc) from exc
