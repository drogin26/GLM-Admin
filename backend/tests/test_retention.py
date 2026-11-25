"""Тест автоочистки переписки (retention 90 дней)."""

from __future__ import annotations

import datetime as dt

import sqlalchemy as sa

from app.models import Business, Channel, ChannelType, Conversation, Message, MessageDirection, MessageSender
from app.services.retention import cleanup_messages_older_than

pytestmark = pytest.mark.asyncio(loop_scope="session")  # общий session-loop с движками из conftest



async def test_cleanup_deletes_only_old_messages(session_factory):
    async with session_factory() as session:
        business = Business(name="Автосервис")
        session.add(business)
        await session.flush()
        channel = Channel(business_id=business.id, type=ChannelType.TELEGRAM)
        session.add(channel)
        await session.flush()
        conversation = Conversation(business_id=business.id, channel_id=channel.id, external_chat_id="c")
        session.add(conversation)
        await session.flush()

        now = dt.datetime.now(dt.UTC)
        make_msg = lambda i, offset_days: Message(  # noqa: E731
            conversation_id=conversation.id,
            direction=MessageDirection.IN,
            sender=MessageSender.CLIENT,
            text=f"msg-{i}",
            created_at=now - dt.timedelta(days=offset_days),
        )
        session.add_all([
            make_msg(1, 120),  # старое — удалить
            make_msg(2, 95),   # старое — удалить
            make_msg(3, 89),   # граница retention — оставить
            make_msg(4, 1),    # свежее — оставить
        ])
        await session.commit()  # cleanup работает через отдельный sync-engine

    deleted = cleanup_messages_older_than(90)
    assert deleted == 2

    async with session_factory() as session:
        remaining = (await session.execute(sa.select(Message.text).order_by(Message.created_at))).scalars().all()
        assert remaining == ["msg-3", "msg-4"]


async def test_cleanup_idempotent(session_factory):
    assert cleanup_messages_older_than(90) == 0
    assert cleanup_messages_older_than(90) == 0
