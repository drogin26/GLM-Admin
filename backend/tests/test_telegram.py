"""Тесты Telegram-канала: incoming processing, dedup, fallback-поллинг."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
import pytest_asyncio
import sqlalchemy as sa

from app.models import (
    Business,
    Channel,
    ChannelStatus,
    ChannelType,
    Conversation,
    ConversationStatus,
    Message,
    MessageDirection,
    MessageSender,
)
from app.services.messaging.telegram import TelegramChannel

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(loop_scope="session")
async def telegram_channel(session_factory, redis_client):
    """Активный Telegram-канал с зашифрованными credentials."""
    from cryptography.fernet import Fernet
    from app.security import encrypt_credentials

    key = Fernet.generate_key().decode()

    async with session_factory() as session:
        business = Business(name="Салон красоты")
        session.add(business)
        await session.flush()

        creds = encrypt_credentials({"token": "123456:BOT-TOKEN-TEST"}, [key])
        channel = Channel(
            business_id=business.id,
            type=ChannelType.TELEGRAM,
            external_id="test_bot",
            credentials_enc=creds,
            status=ChannelStatus.ACTIVE,
        )
        session.add(channel)
        await session.commit()

        # Подменяем fernet_keys в настройках на test-key
        from app.config import Settings

        old_key = Settings.fernet_keys.fget(None)  # type: ignore
        Settings.model_config["env_file"] = ".env"

        class _TestSettings:
            fernet_key_list = [key]
            llm_provider = "gigachat"

        yield TelegramChannel(session_factory, redis_client, _TestSettings())

        async with session_factory() as s:
            await s.execute(sa.text('DELETE FROM "channels"'))
            await s.execute(sa.text('DELETE FROM "businesses"'))
            await s.commit()


@pytest_asyncio.fixture(loop_scope="session")
def telegram_update():
    """Тестовое обновление от Telegram (обычное текстовое сообщение)."""
    return {
        "update_id": 123456,
        "message": {
            "update_id": 123456,
            "message_id": 42,
            "chat": {"id": 100200300, "type": "private", "username": "testuser"},
            "from": {"id": 100200300, "is_bot": False, "username": "testuser", "first_name": "Тест"},
            "date": int(dt.datetime.now(dt.UTC).timestamp()),
            "text": "Здравствуйте! Хочу записаться на маникюр.",
        },
    }


async def test_process_incoming_creates_conversation(telegram_channel, session_factory, telegram_update):
    result = await telegram_channel.process_incoming(telegram_update)
    assert result is not None
    assert result["should_respond"] is True
    assert result["incoming_text"] == "Хочу записаться на маникюр"

    # Проверяем, что conversation и message созданы в БД
    async with session_factory() as session:
        conv_id = uuid.UUID(result["conversation_id"])
        conv = await session.get(Conversation, conv_id)
        assert conv is not None
        assert conv.status == ConversationStatus.BOT
        assert conv.last_msg_at is not None

        msgs = await session.execute(
            sa.select(Message).where(Message.conversation_id == conv_id)
        )
        msgs_list = list(msgs.scalars())
        assert len(msgs_list) == 1
        msg = msgs_list[0]
        assert msg.direction == MessageDirection.IN
        assert msg.sender == MessageSender.CLIENT
        assert msg.text == "Хочу записаться на маникюр"
        assert msg.external_id == "42"


async def test_process_incoming_dedup(telegram_channel, session_factory, telegram_update):
    """Двойной webhook с тем же message_id не создаёт дубликат."""
    await telegram_channel.process_incoming(telegram_update)

    result2 = await telegram_channel.process_incoming(telegram_update)
    assert result2 is None  # дедуп сработал — возвращаем None

    async with session_factory() as session:
        count = await session.scalar(sa.select(sa.func.count(Message.id)))
        assert count == 1


async def test_process_incoming_non_text_ignored(telegram_channel, session_factory):
    """Сообщения без text (например, стикер) игнорируются."""
    update = {
        "update_id": 123457,
        "message": {
            "message_id": 99,
            "chat": {"id": 100200300},
            "text": "",  # пустой текст
            "sticker": {"emoji": "👍"},
        },
    }
    result = await telegram_channel.process_incoming(update)
    assert result is None

    async with session_factory() as session:
        count = await session.scalar(sa.select(sa.func.count(Message.id)))
        assert count == 0


async def test_process_incoming_command_ignored(telegram_channel, session_factory):
    """Команды бота (/start, /help) игнорируются."""
    for cmd in ["/start", "/help", "/settings"]:
        update = {
            "update_id": 123458,
            "message": {
                "message_id": 99,
                "chat": {"id": 100200300},
                "text": cmd,
            },
        }
        result = await telegram_channel.process_incoming(update)
        assert result is None


async def test_process_incoming_creates_new_conversation(telegram_channel, session_factory):
    """Новый chat_id создаёт новую conversation."""
    update1 = {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "chat": {"id": 111111},
            "text": "Привет от первого",
        },
    }
    update2 = {
        "update_id": 2,
        "message": {
            "message_id": 2,
            "chat": {"id": 222222},
            "text": "Привет от второго",
        },
    }
    r1 = await telegram_channel.process_incoming(update1)
    r2 = await telegram_channel.process_incoming(update2)
    assert r1 is not None and r2 is not None
    assert r1["conversation_id"] != r2["conversation_id"]

    async with session_factory() as session:
        count = await session.scalar(sa.select(sa.func.count(Conversation.id)))
        assert count == 2


async def test_verify_webhook_returns_true(telegram_channel):
    """Telegram webhook не подписывает payload — всегда возвращаем True."""
    assert await telegram_channel.verify_webhook(b"{}", {}) is True
