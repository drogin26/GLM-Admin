"""Абстракция канала связи.

Интерфейс MessagingChannel с методами receive/send обеспечивает
добавление новых каналов без изменения ядра.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


class MessagingChannel(ABC):
    """Базовый класс канала."""

    type: str

    def __init__(self, session_factory: Any, redis_client: Any, settings: Any) -> None:
        self._session_factory = session_factory
        self._redis = redis_client
        self._settings = settings

    @abstractmethod
    async def process_incoming(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Обработать входящее сообщение от мессенджера.

        Возвращает dicts с ключами:
          - conversation_id: UUID (str)
          - response_text: str | None  — сгенерированный ответ (если готов)
          - is_draft: bool  — True если полуавто-режим
          - should_escalate: bool  — триггер эскалации
          - lead_score: str | None  — квалификация лида
        """

    @abstractmethod
    async def send(self, channel: Any, conversation: Any, text: str) -> dict[str, Any]:
        """Отправить сообщение клиенту через канал.

        Возвращает метаданные отправки для сохранения в message.llm_metadata.
        """

    @abstractmethod
    async def verify_webhook(self, payload: bytes, headers: dict[str, Any]) -> bool:
        """Верифицировать подпись вебхука. Реализуется в подклассах."""

    @abstractmethod
    async def fallback_poll(self, channel: Any) -> list[dict[str, Any]]:
        """Получить непройдённые сообщения (fallback на случай потери вебхуков)."""


__all__ = ["MessagingChannel"]
