"""Telegram-канал: webhook, send, fallback-поллинг.

Использует Bot API (long polling / webhook через FastAPI-маршруты).
Токены хранятся в channels.credentials_enc.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import typing as t
import uuid

from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import Channel, ChannelStatus, Conversation, ConversationStatus, Message, MessageDirection, MessageSender
from app.services.messaging import MessagingChannel

if t.TYPE_CHECKING:
    from app.models.business import Business

logger = logging.getLogger(__name__)

# Задержки для graceful degradation
POLL_INTERVAL_SEC = 1
MAX_RETRIES = 3
RETRY_BACKOFF_SEC = 2


class TelegramChannel(MessagingChannel):
    """Реализация Telegram-канала через Bot API."""

    type = "tg"

    def __init__(self, session_factory: Any, redis_client: Any, settings: Any) -> None:  # noqa: ANN401
        super().__init__(session_factory, redis_client, settings)

    async def _bot_token(self, channel: Channel) -> str:
        """Расшифровать токен из credentials. Поднимет CredentialsDecryptionError при сбое."""
        from app.config import get_settings
        from app.security import decrypt_credentials

        settings = get_settings()
        if channel.credentials_enc is None:
            raise ValueError("Credentials канала Telegram отсутствуют")
        creds = decrypt_credentials(channel.credentials_enc, settings.fernet_key_list)
        token = creds.get("token")
        if not token:
            raise ValueError("Поле 'token' отсутствует в credentials канала Telegram")
        return token

    async def _request(self, token: str, method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:  # noqa: ANN401
        url = f"https://api.telegram.org/bot{token}/{method}"
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload or {})
            resp.raise_for_status()
            data = resp.json()
        if not data.get("ok"):
            logger.warning("telegram_api_error", extra={"method": method, "error": data.get("description")})
            raise TelegramAPIError(data.get("description", "Unknown API error"), method)
        return data.get("result", {})  # type: ignore[return-value]

    async def send(self, channel: Channel, conversation: Conversation, text: str) -> dict[str, Any]:
        """Отправить ответ через Telegram API."""
        token = await self._bot_token(channel)
        # Определяем chat_id: для Telegram берём external_chat_id
        chat_id = conversation.external_chat_id
        try:
            result = await self._request(token, "sendMessage", {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            })
            return {
                "message_id": result.get("message_id"),
                "sent_at": dt.datetime.now(dt.UTC).isoformat(),
            }
        except TelegramAPIError as exc:
            # Логируем ошибку канала
            async with self._session_factory() as session:
                ch = await session.get(Channel, channel.id)
                if ch:
                    ch.last_error = str(exc)
                    ch.last_error_at = dt.datetime.now(dt.UTC)
                    ch.status = ChannelStatus.ERROR
                    await session.commit()
            logger.error("telegram_send_failed", extra={"channel_id": str(channel.id), "error": exc})
            raise

    async def process_incoming(self, payload: dict[str, Any]) -> dict[str, Any] | None:  # type: ignore[override]
        """Обработать входящее обновление Telegram.

        Поддерживает: обычные сообщения с text, replies (reply_to_message).
        Возвращает None если не наше обновление.
        """
        # Telegram шлёт {ok: true, result: [...]} при long-polling
        if "ok" in payload and "result" in payload:
            for update in payload["result"]:
                processed = await self._process_single_update(update)
                if processed:
                    return processed
            return None
        # Прямой update (из webhook)
        if "message" in payload or "channel_post" in payload:
            return await self._process_single_update(payload)
        return None

    async def _process_single_update(self, update: dict[str, Any]) -> dict[str, Any] | None:
        """Обработать одно обновление."""
        message = update.get("message") or update.get("channel_post")
        if not message:
            return None

        # Игнорируем.non-text сообщения и service messages (new_chat_members и т.д.)
        if not isinstance(message, dict):
            return None

        # Прямые сообщения в чат
        text = message.get("text", "").strip()
        if not text:
            return None

        # Пропускаем команды бота
        if text.startswith("/"):
            return None

        # Telegram unique update_id для дедупа
        update_id = str(message.get("update_id") or update.get("update_id") or id(message))
        telegram_chat_id = str(message.get("chat", {}).get("id", ""))
        telegram_message_id = message.get("message_id")
        from_user = message.get("from", {}) or {}
        from_username = from_user.get("username")

        if not telegram_chat_id:
            return None

        # Определяем business через channel.external_id (token -> business)
        async with self._session_factory() as session:
            channel = await session.execute(
                select(Channel)
                .where(Channel.type == Channel.TELEGRAM, Channel.status == ChannelStatus.ACTIVE)
                .options(selectinload(Channel.business))
                .limit(1)
            )
            channel_obj = channel.scalar_one_or_none()
            if not channel_obj:
                logger.warning("no_active_telegram_channel")
                return None

            business = channel_obj.business

            # Ищем или создаём conversation
            conversation = await session.execute(
                select(Conversation)
                .where(
                    Conversation.channel_id == channel_obj.id,
                    Conversation.external_chat_id == telegram_chat_id,
                )
            )
            conversation_obj = conversation.scalar_one_or_none()

            if not conversation_obj:
                conversation_obj = Conversation(
                    business_id=business.id,
                    channel_id=channel_obj.id,
                    external_chat_id=telegram_chat_id,
                    client_name=from_username,
                    status=ConversationStatus.NEW,
                )
                session.add(conversation_obj)
                await session.flush()

            # Проверка дубликата
            existing = await session.execute(
                select(Message).where(
                    Message.conversation_id == conversation_obj.id,
                    Message.external_id == str(telegram_message_id),
                )
            )
            if existing.scalar_one_or_none():
                return None

            # Сохраняем входящее сообщение
            incoming = Message(
                conversation_id=conversation_obj.id,
                direction=MessageDirection.IN,
                sender=MessageSender.CLIENT,
                text=text,
                external_id=str(telegram_message_id),
            )
            session.add(incoming)

            # Обновляем conversation
            conversation_obj.last_msg_at = dt.datetime.now(dt.UTC)
            conversation_obj.status = ConversationStatus.BOT
            if from_username:
                conversation_obj.client_name = from_username

            await session.commit()

        logger.info(
            "telegram_incoming",
            extra={
                "conversation_id": str(conversation_obj.id),
                "business_id": str(business.id),
                "chat_id": telegram_chat_id,
                "text_preview": text[:80],
            },
        )

        # Возвращаем данные для обработки LLM-слоем (итерация 3)
        return {
            "conversation_id": str(conversation_obj.id),
            "business": business,
            "conversation": conversation_obj,
            "channel": channel_obj,
            "incoming_text": text,
            "incoming_external_id": str(telegram_message_id),
            "client_name": conversation_obj.client_name,
            "should_respond": True,
        }

    async def verify_webhook(self, payload: bytes, headers: dict[str, Any]) -> bool:  # noqa: ARG002
        """Telegram webhook не использует подпись — доверяем HTTPS от api.telegram.org.

        В продакшене рекомендуется проверять IP-адреса Telegram через
        https://api.telegram.org/bot<TOKEN>/getWebhookInfo
        """
        return True

    async def fallback_poll(self, channel: Channel) -> list[dict[str, Any]]:
        """Long polling: получаем непройдённые сообщения.

        Используется Celery beat для периодического опроса,
        если webhook был потерян.
        """
        token = await self._bot_token(channel)
        offset = 0

        # Загружаем последний processed update_id из Redis
        redis_key = f"tg:offset:{channel.id}"
        try:
            stored = await self._redis.get(redis_key)
            if stored:
                offset = int(stored)
        except (ValueError, TypeError):
            pass

        updates: list[dict[str, Any]] = []
        for attempt in range(MAX_RETRIES):
            try:
                result = await self._request(token, "getUpdates", {
                    "offset": offset,
                    "timeout": POLL_INTERVAL_SEC,
                    "allowed_updates": ["message"],
                })
                if result:
                    updates.extend(result)
                    # Обновляем offset на последнее сообщение + 1
                    last = result[-1]
                    offset = last.get("update_id", offset) + 1
                break
            except TelegramAPIError:
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_BACKOFF_SEC * (2 ** attempt))
                else:
                    logger.error("fallback_poll_failed", extra={"channel_id": str(channel.id)})
                    raise

        # Сохраняем offset
        try:
            await self._redis.set(f"tg:offset:{channel.id}", str(offset), ex=3600)
        except Exception:
            pass

        return updates


class TelegramAPIError(Exception):
    """Ошибка Telegram Bot API."""

    def __init__(self, message: str, method: str = "") -> None:
        super().__init__(message)
        self.method = method
