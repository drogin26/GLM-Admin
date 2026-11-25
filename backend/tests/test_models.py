"""Тесты моделей на реальном PostgreSQL: дефолты, ограничения, pgvector."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError, StatementError

from app.models import (

pytestmark = pytest.mark.asyncio(loop_scope="session")  # общий session-loop с движками из conftest

    EMBEDDING_DIM,
    Business,
    Channel,
    ChannelType,
    Client,
    Conversation,
    KnowledgeChunk,
    KnowledgeDoc,
    Lead,
    LeadScore,
    Message,
    MessageDirection,
    MessageSender,
    PlanType,
)


@pytest_asyncio.fixture(loop_scope="session")
async def business(session_factory):
    async with session_factory() as session:
        business = Business(name="Салон «Ромашка»")
        session.add(business)
        await session.commit()
        yield business


@pytest_asyncio.fixture(loop_scope="session")
async def channel(session_factory, business):
    async with session_factory() as session:
        channel = Channel(
            business_id=business.id,
            type=ChannelType.TELEGRAM,
            external_id="my_shop_bot",
        )
        session.add(channel)
        await session.commit()
        yield channel


async def test_business_defaults(session_factory, business):
    assert isinstance(business.id, uuid.UUID)
    assert business.plan is PlanType.TRIAL
    assert business.auto_mode is False  # полуавто по умолчанию (ТЗ)
    assert business.is_active is True
    assert business.created_at is not None
    assert business.working_hours["mon"] == [["09:00", "19:00"]]


async def test_conversation_defaults(session_factory, business, channel):
    async with session_factory() as session:
        conversation = Conversation(
            business_id=business.id, channel_id=channel.id, external_chat_id="100200300"
        )
        session.add(conversation)
        await session.flush()
        assert conversation.status.value == "new"
        assert conversation.last_msg_at is None


async def test_unique_chat_per_channel(session_factory, business, channel):
    async with session_factory() as session:
        session.add(Conversation(business_id=business.id, channel_id=channel.id, external_chat_id="chat1"))
        await session.flush()
        session.add(Conversation(business_id=business.id, channel_id=channel.id, external_chat_id="chat1"))
        with pytest.raises(IntegrityError):
            await session.flush()


async def test_message_defaults_and_dedupe(session_factory, business, channel):
    async with session_factory() as session:
        conversation = Conversation(business_id=business.id, channel_id=channel.id, external_chat_id="c")
        session.add(conversation)
        await session.flush()
        session.add(
            Message(
                conversation_id=conversation.id,
                direction=MessageDirection.IN,
                sender=MessageSender.CLIENT,
                text="Здравствуйте, сколько стоит?",
                external_id="tg-42",
            )
        )
        await session.flush()
        session.add(
            Message(
                conversation_id=conversation.id,
                direction=MessageDirection.IN,
                sender=MessageSender.CLIENT,
                text="дубликат вебхука",
                external_id="tg-42",  # тот же external_id — должно упасть
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()


async def test_enum_string_rejected(session_factory, business, channel):
    async with session_factory() as session:
        conversation = Conversation(business_id=business.id, channel_id=channel.id, external_chat_id="c")
        session.add(conversation)
        await session.flush()
        session.add(
            Message(
                conversation_id=conversation.id,
                direction=MessageDirection.IN,
                sender="hacker",  # type: ignore[arg-type] — валидация на стороне SQLAlchemy
                text="!",
            )
        )
        with pytest.raises((LookupError, StatementError)):
            await session.flush()


async def test_cascade_delete_messages(session_factory, business, channel):
    async with session_factory() as session:
        conversation = Conversation(business_id=business.id, channel_id=channel.id, external_chat_id="c")
        session.add(conversation)
        await session.flush()
        session.add(
            Message(
                conversation_id=conversation.id,
                direction=MessageDirection.OUT,
                sender=MessageSender.BOT,
                text="Добрый день! Подскажу цену.",
            )
        )
        await session.flush()
        await session.delete(conversation)
        await session.flush()
        remaining = await session.scalar(sa.select(sa.func.count()).select_from(Message))
        assert remaining == 0


async def test_client_phone_unique_per_business(session_factory, business, channel):
    async with session_factory() as session:
        session.add(Client(business_id=business.id, phone="+79001234567", name="Иван"))
        await session.flush()
        session.add(Client(business_id=business.id, phone="+79001234567"))
        with pytest.raises(IntegrityError):
            await session.flush()


async def test_vector_roundtrip_and_search(session_factory, business):
    async with session_factory() as session:
        doc = KnowledgeDoc(business_id=business.id, title="Услуги", content="Маникюр 1500 ₽")
        session.add(doc)
        await session.flush()
        session.add(
            KnowledgeChunk(
                doc_id=doc.id,
                chunk_index=0,
                content="Маникюр 1500 ₽",
                embedding=[0.1] * EMBEDDING_DIM,
            )
        )
        session.add(
            KnowledgeChunk(
                doc_id=doc.id,
                chunk_index=1,
                content="Педикюр 2000 ₽",
                embedding=[0.9] * EMBEDDING_DIM,
            )
        )
        await session.flush()

        query_vec = [0.11] * EMBEDDING_DIM
        nearest = (
            await session.execute(
                sa.select(KnowledgeChunk)
                .order_by(KnowledgeChunk.embedding.cosine_distance(query_vec))
                .limit(1)
            )
        ).scalar_one()
        assert nearest.content == "Маникюр 1500 ₽"


async def test_lead_defaults(session_factory, business, channel):
    async with session_factory() as session:
        conversation = Conversation(business_id=business.id, channel_id=channel.id, external_chat_id="c")
        session.add(conversation)
        await session.flush()
        lead = Lead(conversation_id=conversation.id, summary="Разводка труб, Москва, завтра", phone="+79001234567")
        session.add(lead)
        await session.flush()
        assert lead.score is LeadScore.WARM
        assert lead.notified is False
        assert lead.created_at is not None
