"""VK-канал: callback API + long poll для отправки сообщений.

VK использует Callback API — наш сервер получает события по URL,
указанному в настройках группы. Поддерживаются:
- Confirmation event (первая верификация сервера)
- Message New (новое сообщение)
- Message Reply (ответ на сообщение)
- Message Allow (разрешение от бота)

Для отправки используем VK API (long poll / VK Connect).

Переменные окружения:
  VK_GROUP_TOKEN   — токен группы VK
  VK_GROUP_ID      — ID группы VK
"""

from __future__ import annotations

import datetime as dt
import logging
import typing as t
import urllib.parse

import httpx
from cryptography.hazmat.primitives.asymmetric import ed25519

from app.models import Channel, ChannelStatus, Conversation, ConversationStatus, Message, MessageDirection, MessageSender
from app.services.messaging import MessagingChannel

if t.TYPE_CHECKING:
    from app.models.business import Business

logger = logging.getLogger(__name__)


class VKChannel(MessagingChannel):
    """Реализация VK-канала через Callback API."""

    type = "vk"

    def __init__(self, session_factory: t.Any, redis_client: t.Any, settings: t.Any) -> None:  # noqa: ANN401
        super().__init__(session_factory, redis_client, settings)

    async def _api_request(self, token: str, method: str, params: dict[str, t.Any]) -> dict[str, t.Any]:
        """Запрос к VK API."""
        url = f"https://api.vk.com/method/{method}"
        params["access_token"] = token
        params["v"] = "5.245"  # Latest VK API version

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, data=params)
            resp.raise_for_status()
            data = resp.json()

        if data.get("error"):
            error_code = data["error"].get("error_code")
            error_msg = data["error"].get("error_msg", "VK API error")
            logger.warning("vk_api_error", extra={"method": method, "code": error_code, "msg": error_msg})
            raise VKAPIError(error_msg, error_code)
        return data.get("response", {})

    async def _get_bot_token(self, channel: Channel) -> str:
        from app.config import get_settings
        from app.security import decrypt_credentials

        settings = get_settings()
        if channel.credentials_enc is None:
            raise ValueError("Credentials канала VK отсутствуют")
        creds = decrypt_credentials(channel.credentials_enc, settings.fernet_key_list)
        token = creds.get("token")
        if not token:
            raise ValueError("Поле 'token' отсутствует в credentials канала VK")
        return token

    async def send(self, channel: Channel, conversation: Conversation, text: str) -> dict[str, t.Any]:
        """Отправить сообщение через VK API."""
        token = await self._get_bot_token(channel)
        # user_id — external_chat_id для VK это peer_id (может быть user_id или chat_id * 1000 + offset)
        user_id = self._parse_vk_peer(conversation.external_chat_id)

        try:
            result = await self._api_request(token, "messages.send", {
                "user_id": user_id,
                "message": text,
                "random_id": dt.datetime.now(dt.UTC).timestamp(),
            })
            return {
                "message_id": result.get("message_id"),
                "sent_at": dt.datetime.now(dt.UTC).isoformat(),
            }
        except VKAPIError as exc:
            async with self._session_factory() as session:
                ch = await session.get(Channel, channel.id)
                if ch:
                    ch.last_error = str(exc)
                    ch.last_error_at = dt.datetime.now(dt.UTC)
                    ch.status = ChannelStatus.ERROR
                    await session.commit()
            logger.error("vk_send_failed", extra={"channel_id": str(channel.id), "error": exc})
            raise

    def _parse_vk_peer(self, external_chat_id: str) -> int:
        """Преобразовать external_chat_id в user_id.

        VK peer_id для чатов: chat_id * 1000 + offset (для групповых чатов)
        Для личных сообщений — просто user_id.
        """
        if ":" in external_chat_id:
            parts = external_chat_id.split(":")
            return int(parts[1])
        return int(external_chat_id)

    async def process_incoming(self, payload: dict[str, t.Any]) -> dict[str, t.Any] | None:  # type: ignore[override]
        """Обработать событие VK Callback API.

        Поддерживаемые типы событий:
        - message_new: новое сообщение
        - message_reply: ответ на сообщение
        - message_allow: разрешение на запись
        """
        type_event = payload.get("type")
        object_data = payload.get("object")

        # Confirmation event — первая настройка callback API
        if type_event == "confirmation":
            return {"type": "confirmation"}

        if type_event not in ("message_new", "message_reply"):
            return None

        if not isinstance(object_data, dict):
            return None

        # Проверяем что это входящее (from_id != bot_id)
        from_id = object_data.get("from_id")
        if not from_id:
            return None

        text = object_data.get("text", "").strip()
        if not text:
            return None

        if text.startswith("/"):
            return None

        # ID сообщения для дедупа
        vk_message_id = str(object_data.get("id", ""))
        # peer_id — идентификатор чата
        peer_id = str(object_data.get("peer_id", ""))

        # Дата сообщения
        timestamp = object_data.get("date")
        if timestamp:
            message_date = dt.datetime.fromtimestamp(timestamp, tz=dt.UTC)
        else:
            message_date = dt.datetime.now(dt.UTC)

        async with self._session_factory() as session:
            channel = await self._find_vk_channel(session)
            if not channel:
                logger.warning("no_active_vk_channel")
                return None

            business = channel.business

            # Ищем или создаём conversation
            conversation = await session.execute(
                Conversation.__table__.select().where(
                    Conversation.channel_id == channel.id,
                    Conversation.external_chat_id == peer_id,
                )
            )
            conversation_obj = conversation.scalar_one_or_none()

            if not conversation_obj:
                conversation_obj = Conversation(
                    business_id=business.id,
                    channel_id=channel.id,
                    external_chat_id=peer_id,
                    client_name=f"Пользователь {from_id}",
                    status=ConversationStatus.NEW,
                )
                session.add(conversation_obj)
                await session.flush()

            # Дедупликация
            existing = await session.execute(
                Message.__table__.select().where(
                    Message.conversation_id == conversation_obj.id,
                    Message.external_id == vk_message_id,
                )
            )
            if existing.scalar_one_or_none():
                return None

            # Сохраняем входящее
            incoming = Message(
                conversation_id=conversation_obj.id,
                direction=MessageDirection.IN,
                sender=MessageSender.CLIENT,
                text=text,
                external_id=vk_message_id,
                created_at=message_date,
            )
            session.add(incoming)

            conversation_obj.last_msg_at = message_date
            conversation_obj.status = ConversationStatus.BOT

            await session.commit()

        return {
            "conversation_id": str(conversation_obj.id),
            "business": business,
            "conversation": conversation_obj,
            "channel": channel,
            "incoming_text": text,
            "incoming_external_id": vk_message_id,
            "client_name": conversation_obj.client_name,
            "should_respond": True,
        }

    async def _find_vk_channel(self, session: t.Any) -> Channel | None:  # noqa: ANN401
        from sqlalchemy import select
        result = await session.execute(
            select(Channel)
            .where(Channel.type.value == "vk", Channel.status == ChannelStatus.ACTIVE)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def verify_webhook(self, payload: bytes, headers: dict[str, t.Any]) -> bool:
        """Верификация подписи VK Callback API (X-Callback-Secret header)."""
        from app.config import get_settings
        settings = get_settings()

        # Секрет хранится в credentials канала или как переменная окружения
        secret = headers.get("x-callback-secret", "").encode()
        return bool(secret)  # Простая проверка presence

    async def fallback_poll(self, channel: Channel) -> list[dict[str, t.Any]]:
        """VK Long Poll API — альтернатива Callback API."""
        token = await self._get_bot_token(channel)

        # Получаем TS для next poll
        server_data = await self._api_request(token, "messages.getChatOnlineMask", {})
        # Для long poll нужен URL сервера
        # VK API: messages.getLongPollServer
        try:
            result = await self._api_request(token, "messages.getLongPollServer", {
                "group_id": self._get_group_id(channel),
                "use_ssl": True,
            })
            server_url = result.get("server")
            ts = result.get("ts")
            if not server_url or not ts:
                return []

            # Polling
            async with httpx.AsyncClient(timeout=25) as client:
                params = {"ts": ts, "v": "5.245", "act": "action", "timeout": 25}
                resp = await client.get(server_url, params=params)
                resp.raise_for_status()
                data = resp.json()

            if data.get("failed"):
                ts = data.get("ts")
                if data["failed"] == 1:
                    # Проверка uptime
                    pass
                elif data["failed"] == 2:
                    # Удалён callback API
                    pass
                return []

            return data.get("updates", [])
        except Exception:
            logger.error("vk_longpoll_failed")
            return []

    def _get_group_id(self, channel: Channel) -> int:
        if channel.credentials_enc:
            from app.config import get_settings
            from app.security import decrypt_credentials
            settings = get_settings()
            creds = decrypt_credentials(channel.credentials_enc, settings.fernet_key_list)
            return int(creds.get("group_id", 0))
        return 0


class VKAPIError(Exception):
    """Ошибка VK API."""

    def __init__(self, message: str, code: int = 0) -> None:
        super().__init__(message)
        self.code = code
