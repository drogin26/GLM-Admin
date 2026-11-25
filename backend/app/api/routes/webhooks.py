"""Webhook-приёмники для каналов связи.

Telegram: POST /webhook/telegram
VK:       POST /webhook/vk/callback
    Принимает события от VK Callback API.
    Для первой настройки: возвращает confirmation_token.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Request

from app.config import get_settings
from app.services.messaging.telegram import TelegramChannel
from app.services.messaging.vk import VKChannel

logger = logging.getLogger(__name__)
router = APIRouter(tags=["webhooks"])


@router.post("/webhook/telegram")
async def telegram_webhook(
    request: Request,
    payload: dict[str, Any],
) -> dict[str, str]:
    """Принимаем webhook от Telegram и возвращаем 200 OK.

    Telegram ждёт ответ в течение 10 секунд, поэтому мы сразу возвращаем ok
    и обрабатываем в background.
    """
    app = request.app
    asyncio.create_task(_process_telegram_update(app, payload))  # type: ignore[arg-type]
    return {"status": "ok"}


@router.post("/webhook/vk")
async def vk_callback(
    request: Request,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Callback API от VK.

    При первой настройке возвращает confirmation_token.
    При получении сообщений — обрабатывает в background.
    """
    app = request.app
    event_type = payload.get("type")

    # Confirmation event — возвращаем token
    if event_type == "confirmation":
        vk_token = _get_vk_confirmation_token()
        return {"type": "confirmation", "vk_token": vk_token}

    # Обрабатываем сообщения
    if event_type in ("message_new", "message_reply"):
        asyncio.create_task(_process_vk_update(app, payload))  # type: ignore[arg-type]
        return {}

    return {"status": "skipped"}


def _get_vk_confirmation_token() -> str:
    """Возвращает токен подтверждения для VK Callback API.

    В продакшене хранится в credentials канала или .env.
    """
    return "vk_confirmation_token"


async def _process_telegram_update(app: Any, payload: dict[str, Any]) -> None:  # noqa: ANN401
    """Фоновая обработка входящего сообщения из Telegram."""
    from sqlalchemy import select

    from app.models import Channel, ChannelStatus
    from app.services.messaging.telegram import TelegramChannel

    sf = app.state.session_factory
    redis = app.state.redis
    settings = app.state.settings

    async with sf() as session:
        result = await session.execute(
            select(Channel)
            .where(Channel.type.value == "tg", Channel.status == ChannelStatus.ACTIVE)
            .limit(1)
        )
        channel_obj = result.scalar_one_or_none()
        if not channel_obj:
            logger.warning("tg_webhook_no_active_channel")
            return

        tg_channel = TelegramChannel(sf, redis, settings)
        processed = await tg_channel.process_incoming(payload)
        if not processed or not processed.get("should_respond"):
            return

        logger.info(
            "tg_webhook_processed",
            extra={
                "conversation_id": processed.get("conversation_id"),
                "business_id": str(processed["business"].id),
            },
        )


async def _process_vk_update(app: Any, payload: dict[str, Any]) -> None:  # noqa: ANN401
    """Фоновая обработка события VK Callback API."""
    from sqlalchemy import select

    from app.models import Channel, ChannelStatus
    from app.services.messaging.vk import VKChannel

    sf = app.state.session_factory
    redis = app.state.redis
    settings = app.state.settings

    async with sf() as session:
        result = await session.execute(
            select(Channel)
            .where(Channel.type.value == "vk", Channel.status == ChannelStatus.ACTIVE)
            .limit(1)
        )
        channel_obj = result.scalar_one_or_none()
        if not channel_obj:
            logger.warning("vk_callback_no_active_channel")
            return

        vk_channel = VKChannel(sf, redis, settings)
        processed = await vk_channel.process_incoming(payload)
        if not processed or not processed.get("should_respond"):
            return

        logger.info(
            "vk_callback_processed",
            extra={
                "conversation_id": processed.get("conversation_id"),
                "business_id": str(processed["business"].id),
            },
        )
