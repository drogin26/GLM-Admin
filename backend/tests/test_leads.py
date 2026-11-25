"""Тесты квалификации лидов: извлечение сущностей, score, urgent."""

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
    Lead,
    LeadScore,
    LeadUrgency,
    Message,
    MessageDirection,
    MessageSender,
)
from app.services.leads import (
    create_lead_from_conversation,
    extract_lead_info,
    notify_owner_via_telegram,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(loop_scope="session")
async def business(session_factory):
    async with session_factory() as session:
        b = Business(name="Автосервис", telegram_notify_chat_id="123456789")
        session.add(b)
        await session.flush()
        yield b


@pytest_asyncio.fixture(loop_scope="session")
async def channel(session_factory, business):
    async with session_factory() as session:
        c = Channel(business_id=business.id, type=ChannelType.TELEGRAM, status=ChannelStatus.ACTIVE)
        session.add(c)
        await session.flush()
        yield c


@pytest_asyncio.fixture(loop_scope="session")
async def conversation(session_factory, business, channel):
    async with session_factory() as session:
        c = Conversation(business_id=business.id, channel_id=channel.id, external_chat_id="chat_1")
        session.add(c)
        await session.flush()
        yield c


def make_msg(session, conv_id: uuid.UUID, text: str) -> None:
    session.add(Message(
        conversation_id=conv_id,
        direction=MessageDirection.IN,
        sender=MessageSender.CLIENT,
        text=text,
    ))


class TestExtractLeadInfo:
    """Тесты извлечения сущностей из текста диалога."""

    async def test_extract_hot_lead_with_phone(self, session_factory, conversation, business):
        """Лид с телефоном и услугой → HOT."""
        async with session_factory() as session:
            make_msg(session, conversation.id, "Здравствуйте! Хочу поменять тормозные колодки в Москве")
            make_msg(session, conversation.id, "Мой номер +7 (900) 123-45-67, нужно срочно!")
            await session.commit()

        result = await extract_lead_info(session, conversation, [], business)
        assert result is not None
        assert result["score"] == LeadScore.HOT
        assert result["phone"] == "+7900123456"  # Извлечён
        assert result["city"] == "Москва"
        assert result["urgency"] == LeadUrgency.HIGH

    async def test_extract_warm_lead_no_phone(self, session_factory, conversation, business):
        """Лид без телефона → WARM."""
        async with session_factory() as session:
            make_msg(session, conversation.id, "Нужна оклейка автомобиля в матовый чёрный")
            await session.commit()

        result = await extract_lead_info(session, conversation, [], business)
        assert result is not None
        assert result["score"] == LeadScore.WARM
        assert result["phone"] is None

    async def test_extract_cold_lead_no_info(self, session_factory, conversation, business):
        """Общий вопрос без конкретики → None (не лид)."""
        async with session_factory() as session:
            make_msg(session, conversation.id, "Привет!")
            await session.commit()

        result = await extract_lead_info(session, conversation, [], business)
        assert result is None

    async def test_extract_phone_various_formats(self):
        """Различные форматы телефона корректно извлекаются."""
        from app.services.leads import _extract_phone

        assert _extract_phone("+7 (900) 123-45-67") is not None
        assert _extract_phone("89001234567") is not None
        assert _extract_phone("+7-900-1234567") is not None
        assert _extract_phone("нет телефона") is None

    async def test_extract_city(self):
        from app.services.leads import _extract_city

        assert _extract_city("работаю в москве") == "Москва"
        assert _extract_city("спб, петербург") == "Санкт-Петербург"
        assert _extract_city("нужно в казани") == "Казань"
        assert _extract_city("где угодно") is None

    async def test_urgency_high(self):
        from app.services.leads import _determine_urgency, LeadUrgency

        assert _determine_urgency("нужно срочно завтра") == LeadUrgency.HIGH
        assert _determine_urgency("как можно скорее") == LeadUrgency.HIGH
        assert _determine_urgency("не горящее, можно на следующей неделе") == LeadUrgency.NORMAL


class TestCreateLead:
    """Тесты создания лида из диалога."""

    async def test_create_lead_hot(self, session_factory, conversation, business):
        async with session_factory() as session:
            make_msg(session, conversation.id, "Нужна замена масла, Москва, срочно!")
            make_msg(session, conversation.id, "Телефон +79001234567")
            await session.commit()

        lead = await create_lead_from_conversation(session, conversation, business)
        assert lead is not None
        assert lead.score == LeadScore.HOT
        assert lead.phone == "+7900123456"

    async def test_create_lead_no_service(self, session_factory, conversation, business):
        async with session_factory() as session:
            make_msg(session, conversation.id, "Просто спрашиваю, без заявки")
            await session.commit()

        lead = await create_lead_from_conversation(session, conversation, business)
        assert lead is None


class TestNotifyOwner:
    """Тесты уведомлений владельцу."""

    async def test_notify_hot_lead(self, session_factory, conversation, business):
        async with session_factory() as session:
            lead = Lead(
                conversation_id=conversation.id,
                summary="Замена масла, Москва",
                score=LeadScore.HOT,
                urgency=LeadUrgency.HIGH,
                phone="+79001234567",
            )
            session.add(lead)
            await session.flush()

            result = await notify_owner_via_telegram(business, lead, session)
            assert result is True
            assert lead.notified is True
            assert lead.notified_at is not None

    async def test_no_notify_warm_lead(self, session_factory, conversation, business):
        async with session_factory() as session:
            lead = Lead(
                conversation_id=conversation.id,
                summary="Общий вопрос",
                score=LeadScore.WARM,
            )
            session.add(lead)
            await session.flush()

            result = await notify_owner_via_telegram(business, lead, session)
            assert result is False
            assert lead.notified is False

    async def test_no_notify_no_chat_id(self, session_factory, conversation):
        async with session_factory() as session:
            b = Business(name="Без telegram", telegram_notify_chat_id=None)
            session.add(b)
            await session.flush()

            lead = Lead(
                conversation_id=conversation.id,
                summary="Тест",
                score=LeadScore.HOT,
            )
            session.add(lead)
            await session.flush()

            result = await notify_owner_via_telegram(b, lead, session)
            assert result is False
