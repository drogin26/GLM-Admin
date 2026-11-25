"""Провайдер GigaChat через REST API.

Использует OAuth-токен для аутентификации.
Документация: https://developers.sber.ru/docs/ru/gigachat/api/api-workflow

Переменные окружения:
  GIGACHAT_CLIENT_ID     — ID клиента (из кабинета GigaChat)
  GIGACHAT_CLIENT_SECRET — Secret клиента
  GIGACHAT_SCOPE         — область видимости (по умолчанию "GIGACHAT_BASICS:PANDR")
  GIGACHAT_BASE_URL      — базовый URL (по умолчанию https://gigachat.devices.sber.ru/api)
"""

from __future__ import annotations

import datetime as dt
import logging
import typing as t
import urllib.parse

import httpx
from pydantic import BaseModel, Field

from app.services.llm import LLMCallResult, LLMProvider, register_provider

logger = logging.getLogger(__name__)


class _GigaChatCredentials(BaseModel):
    client_id: str = Field(..., alias="clientId")
    client_secret: str = Field(..., alias="clientSecret")
    scope: str = "GIGACHAT_BASICS:PANDR"
    base_url: str = "https://gigachat.devices.sber.ru/api"


class _GigaChatToken(BaseModel):
    access_token: str
    expires_in: int
    token_type: str = "Bearer"

    @property
    def expires_at(self) -> dt.datetime:
        return dt.datetime.now(dt.UTC) + dt.timedelta(seconds=self.expires_in)


class _GigaChatMessage(BaseModel):
    role: str = "user"
    content: str


class _GigaChatChoice(BaseModel):
    message: _GigaChatMessage
    finish_reason: str | None = None


class _GigaChatResponse(BaseModel):
    choices: list[_GigaChatChoice]
    usage: dict[str, t.Any] | None = None


@register_provider("gigachat")
class GigaChatProvider(LLMProvider):
    """Провайдер GigaChat."""

    name = "gigachat"

    def __init__(
        self,
        client_id: str = "",
        client_secret: str = "",
        scope: str = "GIGACHAT_BASICS:PANDR",
        base_url: str = "https://gigachat.devices.sber.ru/api",
        **kwargs: t.Any,
    ) -> None:
        super().__init__(**kwargs)
        self.client_id = client_id
        self.client_secret = client_secret
        self.scope = scope
        self.base_url = base_url.rstrip("/")
        self._token: _GigaChatToken | None = None
        self._token_lock: t.Any = None  # Placeholder — в продакшене threading.Lock

    async def _authenticate(self) -> str:
        """Получить OAuth-токен. Кэширует до истечения."""
        if self._token and self._token.expires_at > dt.datetime.now(dt.UTC):
            return self._token.access_token

        creds = _GigaChatCredentials(
            clientId=self.client_id,
            clientSecret=self.client_secret,
            scope=self.scope,
        )

        # OAuth-запрос к GigaChat
        auth_url = f"{self.base_url}/auth"
        payload = urllib.parse.urlencode({
            "scope": creds.scope,
        })

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                auth_url,
                data=payload,
                headers={
                    "Authorization": f"Basic {self.client_secret}",
                    "RqUID": self.client_id,
                },
            )
            resp.raise_for_status()
            token_data = resp.json()

        self._token = _GigaChatToken(**token_data)
        logger.info("gigachat_authenticated", extra={"token_expires_in_sec": self._token.expires_in})
        return self._token.access_token

    async def generate(
        self,
        prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 500,
    ) -> LLMCallResult:
        token = await self._authenticate()
        started = dt.datetime.now(dt.UTC)

        payload = {
            "model": "GigaChat-Pro",
            "messages": [
                {"role": "system", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                        "X-Request-Id": dt.datetime.now(dt.UTC).isoformat(),
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            choices = _GigaChatResponse(**data).choices
            response_text = choices[0].message.content if choices else None

            latency_ms = int((dt.datetime.now(dt.UTC) - started).total_seconds() * 1000)
            usage = data.get("usage", {})

            result = LLMCallResult(
                response=response_text,
                provider="gigachat",
                model=data.get("model"),
                tokens_in=usage.get("prompt_tokens", 0),
                tokens_out=usage.get("completion_tokens", 0),
                latency_ms=latency_ms,
                prompt_hash=self.hash_prompt(prompt),
            )
            logger.info(
                "gigachat_generated",
                extra={
                    "tokens_in": result["tokens_in"],
                    "tokens_out": result["tokens_out"],
                    "latency_ms": latency_ms,
                },
            )
            return result

        except httpx.HTTPStatusError as exc:
            logger.error("gigachat_http_error", extra={"status": exc.response.status_code, "detail": exc.response.text})
            raise
        except Exception as exc:
            logger.error("gigachat_error", extra={"error": str(exc)})
            raise

    async def embed(self, text: str) -> list[float]:
        token = await self._authenticate()

        payload = {
            "model": "EmbedDaVinci",
            "input": [text[:2000]],  # LLM ограничивает длину ввода
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self.base_url}/embeddings",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            # GigaChat embeddings: {data: [{embedding: [...]}]}
            embedding = data.get("data", [{}])[0].get("embedding", [])
            logger.info("gigachat_embedded", extra={"length": len(embedding)})
            return embedding

        except Exception as exc:
            logger.error("gigachat_embed_error", extra={"error": str(exc)})
            raise
