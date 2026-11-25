"""Квалификация лидов: извлечение сущностей из диалога, карточки, уведомления.

Сервис анализирует последние сообщения диалога и определяет:
- Что нужно клиенту (услуга/товар)
- Город/адрес
- Срочность (HIGH/NORMAL/LOW)
- Телефон (если согласован)
- Score (HOT/WARM/COLD)

Для HOT-лидов отправляется карточка владельцу в Telegram.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import typing as t
import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Business, Conversation, Lead, LeadScore, LeadUrgency, Message

logger = logging.getLogger(__name__)

# Паттерны для извлечения телефонов
PHONE_EXTRACT_PATTERN = re.compile(
    r"([\+]?7|8)[\s.-]?(\(?\d{3}\)?)[\s.-]?(\d{3})[\s.-]?(\d{2})[\s.-]?(\d{2})"
)

# Паттерны для извлечения городов
CITY_PATTERNS = {
    "москва": "Москва",
    "спб": "Санкт-Петербург",
    "санкт-петербург": "Санкт-Петербург",
    "петербург": "Санкт-Петербург",
    "казань": "Казань",
    "новосибирск": "Новосибирск",
    "екатеринбург": "Екатеринбург",
    "нижний": "Нижний Новгород",
    "ростов": "Ростов-на-Дону",
}

# Паттерны для определения срочности
URGENCY_PATTERNS_HIGH: list[str] = [
    "срочно", "срочн[оыйые]", "завтра", "прямо сейчас", "как можно скорее",
    "неотложн[оый]", "экстренн[оой]", "горю", "горит", "вечером", "today",
]

# Ключевые слова услуг (расширяется по бизнесу)
SERVICE_KEYWORDS: list[str] = [
    "маникюр", "педикюр", "стрижка", "окрашивание", "оклейка", "тонировка",
    "разводк[ауеы]", "монтаж", "установка", "ремонт", "починк[аа]",
    "диагностик[аа]", "замена", "бронирование", "полировка", "химчистк[аа]",
    "кузовн[оой]", "двигатель", "подвеск[аа]", "тормоз[аов]", "масло",
    "аппаратн", "ультразвук", "уходов", "SPA", "гель", "лакер", "акрил",
]


async def extract_lead_info(
    session: AsyncSession,
    conversation: Conversation,
    recent_messages: list[Message],
    business: Business | None = None,
) -> dict[str, t.Any] | None:
    """Извлечь информацию о лиде из последних сообщений диалога.

    Args:
        session: SQLAlchemy сессия.
        conversation: Диалог для создания лида.
        recent_messages: Последние N сообщений.
        business: Бизнес для персонализации.

    Returns:
        dict с полями лида или None если нет достаточной информации.
    """
    full_text = " ".join(m.text for m in recent_messages)
    full_text_lower = full_text.lower()

    # 1. Извлекаем телефон
    phone = _extract_phone(full_text)

    # 2. Извлекаем город
    city = _extract_city(full_text_lower)

    # 3. Определяем срочность
    urgency = _determine_urgency(full_text_lower)

    # 4. Извлекаем что нужно (ключевые слова услуг)
    service = _extract_service(full_text_lower)

    # 5. Определяем score
    score = _calculate_score(service, city, phone, urgency)

    # Формируем summary для карточки
    summary = _build_summary(service, city, phone, urgency)

    if not summary:
        return None

    return {
        "summary": summary,
        "urgency": urgency,
        "city": city,
        "phone": phone,
        "score": score,
        "extra": {
            "service": service,
            "messages_count": len(recent_messages),
            "conversation_status": conversation.status.value,
        },
    }


def _extract_phone(text: str) -> str | None:
    """Извлечь телефон из текста."""
    match = PHONE_EXTRACT_PATTERN.search(text)
    if match:
        groups = match.groups()
        prefix = groups[0]
        return f"+{prefix[1:]}" + "".join(groups[1:])
    return None


def _extract_city(text: str) -> str | None:
    """Извлечь город из текста."""
    for pattern, name in CITY_PATTERNS.items():
        if pattern in text:
            return name
    return None


def _determine_urgency(text: str) -> LeadUrgency:
    """Определить срочность по ключевым словам."""
    for pattern in URGENCY_PATTERNS_HIGH:
        if re.search(pattern, text):
            return LeadUrgency.HIGH
    return LeadUrgency.NORMAL


def _extract_service(text: str) -> str | None:
    """Извлечь нужную услугу из текста."""
    for kw in SERVICE_KEYWORDS:
        if re.search(kw, text):
            return kw
    return None


def _calculate_score(
    service: str | None,
    city: str | None,
    phone: str | None,
    urgency: LeadUrgency,
) -> LeadScore:
    """Рассчитать score лида (HOT/WARM/COLD).

    HOT: есть телефон + услуга + срочность/город
    WARM: есть телефон или услуга
    COLD: только общая информация
    """
    hot_score = 0
    if phone:
        hot_score += 2
    if service:
        hot_score += 1
    if city:
        hot_score += 1
    if urgency == LeadUrgency.HIGH:
        hot_score += 2

    if hot_score >= 5:
        return LeadScore.HOT
    if hot_score >= 2:
        return LeadScore.WARM
    return LeadScore.COLD


def _build_summary(
    service: str | None,
    city: str | None,
    phone: str | None,
    urgency: LeadUrgency,
) -> str:
    """Сформировать краткое summary для карточки лида."""
    parts: list[str] = []
    if service:
        parts.append(f"Услуга: {service}")
    if city:
        parts.append(f"Город: {city}")
    if phone:
        parts.append(f"Телефон: {phone}")
    if urgency == LeadUrgency.HIGH:
        parts.append("Срочность: ВЫСОКАЯ")

    return "; ".join(parts) if parts else "Заявка от клиента"


async def create_lead_from_conversation(
    session: AsyncSession,
    conversation: Conversation,
    business: Business,
    recent_message_count: int = 5,
) -> Lead | None:
    """Создать лид из диалога если обнаружены признаки горячей заявки."""
    # Получаем последние N сообщений
    result = await session.execute(
        sa.select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.desc())
        .limit(recent_message_count)
    )
    messages = list(reversed(result.scalars().all()))

    # Извлекаем информацию
    lead_info = await extract_lead_info(session, conversation, messages, business)
    if not lead_info:
        return None

    # Создаём Lead
    lead = Lead(
        conversation_id=conversation.id,
        summary=lead_info["summary"],
        urgency=lead_info["urgency"],
        city=lead_info["city"],
        phone=lead_info["phone"],
        score=lead_info["score"],
        extra=lead_info["extra"],
    )
    session.add(lead)

    # Эскалация HOT-лида
    if lead.score == LeadScore.HOT:
        conversation.status = ConversationStatus.HUMAN
        logger.info("hot_lead_detected", extra={
            "conversation_id": str(conversation.id),
            "phone": lead.phone,
        })

    await session.flush()
    return lead


async def notify_owner_via_telegram(
    business: Business,
    lead: Lead,
    session: AsyncSession,
) -> bool:
    """Отправить карточку лида владельцу в Telegram.

    Отправляется только при score = HOT.
    """
    if not business.telegram_notify_chat_id:
        logger.warning("no_telegram_notify_chat", extra={"business_id": str(business.id)})
        return False

    if lead.score != LeadScore.HOT:
        return False

    # Формируем карточку
    score_emoji = {"hot": "🔥", "warm": "🔶", "cold": "⚪"}.get(lead.score.value, "⚪")
    urgency_emoji = {
        "high": "⏰",
        "normal": "📋",
        "low": "🐌",
    }.get(lead.urgency.value, "📋")

    card = (
        f"{score_emoji} {urgency_emoji} *ГОРЯЧИЙ ЛИД*\n\n"
        f"💬 {lead.summary}\n\n"
        f"📊 Оценка: *{lead.score.value.upper()}*\n"
        f"📅 Создан: {lead.created_at.strftime('%d.%m %H:%M')}"
    )

    # TODO: отправка через TelegramChannel (итерация 5 будет общий сервис отправки)
    # Пока просто логгируем
    logger.info(
        "lead_card_sent",
        extra={
            "business_id": str(business.id),
            "conversation_id": str(lead.conversation_id),
            "chat_id": business.telegram_notify_chat_id,
            "score": lead.score.value,
        },
    )

    # Помечаем как уведомлённый
    lead.notified = True
    lead.notified_at = dt.datetime.now(dt.UTC)

    return True


async def notify_owner_via_telegram(
    business: Business,
    lead: Lead,
    session: AsyncSession,
) -> bool:
    """Отправить карточку лида владельцу в Telegram."""
    if not business.telegram_notify_chat_id:
        logger.warning("no_telegram_notify_chat", extra={"business_id": str(business.id)})
        return False

    if lead.score != LeadScore.HOT:
        return False

    # Формируем карточку
    score_emoji = {"hot": "🔥", "warm": "🔶", "cold": "⚪"}.get(lead.score.value, "⚪")
    urgency_emoji = {
        "high": "⏰",
        "normal": "📋",
        "low": "🐌",
    }.get(lead.urgency.value, "📋")

    card = (
        f"{score_emoji} {urgency_emoji} *ГОРЯЧИЙ ЛИД*\n\n"
        f"💬 {lead.summary}\n\n"
        f"📊 Оценка: *{lead.score.value.upper()}*\n"
        f"📅 Создан: {lead.created_at.strftime('%d.%m %H:%M')}"
    )

    # TODO: отправка через TelegramChannel
    logger.info(
        "lead_card_sent",
        extra={
            "business_id": str(business.id),
            "conversation_id": str(lead.conversation_id),
            "chat_id": business.telegram_notify_chat_id,
            "score": lead.score.value,
        },
    )

    lead.notified = True
    lead.notified_at = dt.datetime.now(dt.UTC)

    return True


__all__ = [
    "extract_lead_info",
    "create_lead_from_conversation",
    "notify_owner_via_telegram",
]
