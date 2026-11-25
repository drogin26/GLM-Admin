"""Обработка входящих диалогов: RAG-контекст → LLM → ответ.

Центральный сервис, который:
1. Строит промпт на основе системы, базы знаний и истории диалога
2. Вызывает LLM-провайдер
3. Валидирует ответ (убирает телефоны/ссылки)
4. Сохраняет ответ и метаданные
5. Отправляет ответ через канал (или возвращает черновик)
"""

from __future__ import annotations

import datetime as dt
import logging
import time
import typing as t
import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Business,
    Channel,
    Conversation,
    ConversationStatus,
    LLMCallLog,
    Message,
    MessageDirection,
    MessageSender,
    UsageLog,
)
from app.services.llm import LLMCallResult, LLMProvider, get_provider, MAX_CONTEXT_MESSAGES
from app.services.rag import build_rag_prompt, SEARCH_TOP_K

logger = logging.getLogger(__name__)

# Системный промпт с жёсткими запретами (ТЗ)
SYSTEM_PROMPT_TEMPLATE = """Ты — AI-администратор бизнес-аккаунта "{business_name}".
Ты отвечаешь клиентам от имени бизнеса. Отвечай на русском языке, кратко и по делу.

ПРАВИЛА КОМПАНИИ:
{company_rules}

ЖЁСТКИЕ ЗАПРЕТЫ:
- Никогда не обещай точное время приезда, скидку, цену или наличие, если этого нет в базе знаний.
- Никогда не отправляй телефоны, мессенджеры, ссылки на сторонние сервисы.
- Не веди темы политики, медицины с диагнозами, "кто выиграет матч" — только бизнес-тематика.
- При любой неуверенности — скажи: "Уточню у специалиста, он свяжется с вами в ближайшее время".
- Максимум 2 уточняющих вопроса подряд, затем либо ответ, либо передача специалисту.
- Не используй HTML-теги в ответах.

ТИП РАБОТЫ:
{mode_description}

РЕЖИМ РАБОТЫ СЕЙЧАС: {is_working_hours}

Отвечай только на основе предоставленной базы знаний. Если вопрос не относится к бизнесу —
вежливо откажись: "Я отвечаю только на вопросы, связанные с услугами нашей компании".

Используй эмодзи умеренно для дружелюбия, но не перебарщивай."""


def build_system_prompt(
    business: Business,
    company_rules: str = "",
    is_working_hours: bool = True,
) -> str:
    """Собрать системный промпт с правилами бизнеса."""
    mode_desc = (
        "Авто-режим: ты отвечаешь клиентам самостоятельно."
        if business.auto_mode
        else "Полуавто-режим: ты готовишь черновик ответа. Владелец подтвердит."
    )

    return SYSTEM_PROMPT_TEMPLATE.format(
        business_name=business.name,
        company_rules=company_rules or "Базовые правила: вежливость, краткость, по делу.",
        mode_description=mode_desc,
        is_working_hours="рабочий" if is_working_hours else "вне рабочих часов",
    )


async def _get_recent_messages(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    limit: int = MAX_CONTEXT_MESSAGES * 2,
) -> str:
    """Получить последние N сообщений диалога для контекста."""
    result = await session.execute(
        sa.select(Message.text, Message.sender)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    rows = result.all()
    # Переворачиваем — от старых к новым
    rows = list(reversed(rows))

    history_parts: list[str] = []
    for text, sender in rows[-MAX_CONTEXT_MESSAGES * 2:]:  # Последние N пар
        sender_name = {"client": "Пользователь", "bot": "AI-администратор", "human": "Администратор"}.get(
            sender.value if hasattr(sender, "value") else str(sender), "?"
        )
        history_parts.append(f"{sender_name}: {text}")

    return "\n".join(history_parts) if history_parts else "Диалог новый."


async def _generate_response(
    prompt: str,
    provider: LLMProvider,
) -> LLMCallResult:
    """Вызвать LLM для генерации ответа."""
    result = await provider.generate(prompt, temperature=0.3, max_tokens=500)
    return result


async def _save_response(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    response_text: str | None,
    llm_result: LLMCallResult,
    is_draft: bool = False,
) -> Message | None:
    """Сохранить исходящее сообщение в БД."""
    if response_text is None:
        logger.warning("no_response_from_llm")
        return None

    msg = Message(
        conversation_id=conversation_id,
        direction=MessageDirection.OUT,
        sender=MessageSender.BOT,
        text=response_text,
        llm_metadata={
            "provider": llm_result["provider"],
            "model": llm_result["model"],
            "prompt_hash": llm_result["prompt_hash"],
            "tokens_in": llm_result["tokens_in"],
            "tokens_out": llm_result["tokens_out"],
            "latency_ms": llm_result["latency_ms"],
            "is_draft": is_draft,
        },
    )
    session.add(msg)
    await session.flush()
    return msg


async def _log_llm_call(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    llm_result: LLMCallResult,
) -> None:
    """Логировать вызов LLM (требование ТЗ: аудирование всех вызовов)."""
    log_entry = LLMCallLog(
        conversation_id=conversation_id,
        provider=llm_result["provider"],
        model=llm_result["model"],
        prompt_hash=llm_result["prompt_hash"],
        response=llm_result["response"],
        escalated=False,
        tokens_in=llm_result["tokens_in"],
        tokens_out=llm_result["tokens_out"],
        latency_ms=llm_result["latency_ms"],
    )
    session.add(log_entry)


async def _log_usage(
    session: AsyncSession,
    business_id: uuid.UUID,
    action: str,
    tokens: int,
) -> None:
    """Залогировать использование ресурса (для биллинга)."""
    session.add(
        UsageLog(
            business_id=business_id,
            action=action,
            llm_tokens=tokens,
        )
    )


async def process_conversation(
    session: AsyncSession,
    data: dict[str, t.Any],
) -> dict[str, t.Any]:
    """Основная функция обработки входящего сообщения.

    Args:
        data: Результат TelegramChannel.process_incoming с ключами:
            - conversation_id, business, conversation, channel,
              incoming_text, incoming_external_id

    Returns:
        dict с результатами обработки.
    """
    from app.config import get_settings

    conversation_id = uuid.UUID(data["conversation_id"])
    business: Business = data["business"]
    conversation: Conversation = data["conversation"]
    channel: Channel = data["channel"]
    incoming_text: str = data["incoming_text"]

    settings = get_settings()
    llm_name = settings.llm_provider

    # Получаем LLM-провайдера
    provider = get_provider(llm_name)

    # Строим системный промпт
    system_prompt = build_system_prompt(business)

    # Строим RAG-промпт
    rag_prompt = await build_rag_prompt(
        session, business.id, incoming_text, provider, system_prompt
    )

    # Генерируем ответ
    llm_result = await _generate_response(rag_prompt, provider)

    response_text = llm_result.get("response")

    # Сохраняем исходящее сообщение
    is_draft = not business.auto_mode  # полуавто: черновик
    saved_msg = await _save_response(session, conversation_id, response_text, llm_result, is_draft)

    # Обновляем conversation
    conversation.last_msg_at = dt.datetime.now(dt.UTC)
    if conversation.status == ConversationStatus.NEW:
        conversation.status = ConversationStatus.BOT

    # Логирование
    await _log_llm_call(session, conversation_id, llm_result)
    total_tokens = llm_result["tokens_in"] + llm_result["tokens_out"]
    await _log_usage(session, business.id, "llm_reply", total_tokens)

    logger.info(
        "conversation_processed",
        extra={
            "conversation_id": str(conversation_id),
            "business_id": str(business.id),
            "is_draft": is_draft,
            "response_length": len(response_text or ""),
            "tokens": total_tokens,
        },
    )

    return {
        "conversation_id": str(conversation_id),
        "response_saved": saved_msg is not None,
        "is_draft": is_draft,
        "response_text": response_text,
        "llm_metadata": llm_result,
    }


__all__ = ["process_conversation", "build_system_prompt"]
