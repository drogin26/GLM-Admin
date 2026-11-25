"""Абстракция LLM-провайдера.

Все вызовы LLM проходят через этот интерфейс. По умолчанию используется
GigaChat (настраивается LLm_PROVIDER). Новый провайдер добавляется без
изменения ядра — достаточно реализовать интерфейс и добавить регистр.
"""

from __future__ import annotations

import hashlib
import logging
import typing as t
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

# Максимум сообщений в контексте диалога (ограничение контекстного окна + стоимость)
MAX_CONTEXT_MESSAGES = 10


class LLMCallResult(t.TypedDict):
    """Результат вызова LLM."""

    response: str | None
    provider: str
    model: str | None
    tokens_in: int
    tokens_out: int
    latency_ms: int | None
    prompt_hash: str


class LLMProvider(ABC):
    """Базовый класс LLM-провайдера."""

    name: str  # Например, "gigachat", "yandexgpt"

    def __init__(self, **kwargs: t.Any) -> None:  # noqa: ANN401
        self._kwargs = kwargs

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 500,
    ) -> LLMCallResult:
        """Сгенерировать ответ на промпт.

        Args:
            prompt: Текстовый промпт для модели.
            temperature: Температура генерации (0.0 — детерминировано).
            max_tokens: Максимум токенов в ответе.

        Returns:
            LLMCallResult с ответом и метаданными.
        """

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Получить эмбеддинг текста.

        Returns:
            Вектор эмбеддинга (список float).
        """

    @staticmethod
    def hash_prompt(text: str) -> str:
        """Хэш промпта для аудита (без сохранения сырого текста)."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:64]


class EmptyProvider:
    """Заглушка: возвращает пустой ответ.

    Используется когда LLM недоступен или в тестах.
    """

    name = "empty"

    async def generate(
        self,
        prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 500,
    ) -> LLMCallResult:
        logger.warning("llm_provider_unavailable")
        return LLMCallResult(
            response=None,
            provider="empty",
            model=None,
            tokens_in=0,
            tokens_out=0,
            latency_ms=None,
            prompt_hash=LLMProvider.hash_prompt(prompt),
        )

    async def embed(self, text: str) -> list[float]:
        return [0.0] * 1024  # Нулевой вектор


# Регистр провайдеров
_REGISTRY: dict[str, type[LLMProvider]] = {}


def register_provider(name: str) -> t.Callable[[t.Type[LLMProvider]], t.Type[LLMProvider]]:
    """Декоратор для регистрации LLM-провайдера."""
    def wrapper(cls: type[LLMProvider]) -> type[LLMProvider]:
        _REGISTRY[name] = cls
        return cls
    return wrapper


def get_provider(name: str, **kwargs: t.Any) -> LLMProvider:
    """Получить провайдер из регистра."""
    if name not in _REGISTRY:
        logger.warning("unknown_llm_provider", extra={"name": name})
        return EmptyProvider()
    return _REGISTRY[name](**kwargs)


__all__ = [
    "LLMProvider",
    "LLMCallResult",
    "register_provider",
    "get_provider",
    "EmptyProvider",
    "MAX_CONTEXT_MESSAGES",
]
