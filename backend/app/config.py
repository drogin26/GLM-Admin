"""Конфигурация приложения: все настройки приходят из переменных окружения (12-factor).

Локальная разработка может использовать `.env` рядом с `backend/`.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["dev", "test", "prod"] = "dev"
    app_version: str = "0.1.0"

    # --- Логи ---
    log_level: str = "INFO"
    log_json: bool = True

    # --- Хранилища ---
    database_url: str = "postgresql://aiadmin:aiadmin@localhost:5433/aiadmin"
    redis_url: str = "redis://localhost:6380/0"

    # --- Безопасность ---
    # Секрет для подписи сессий/JWT (кабинет, итерация 7)
    secret_key: str = ""
    # Один или несколько ключей Fernet через запятую (шифрование credentials каналов).
    # Ротация: добавить новый ключ ПЕРВЫМ — им шифруем, остальными расшифровываем старое.
    fernet_keys: str = ""

    # --- Домен ---
    retention_days: int = Field(default=90, ge=1)  # хранение переписки, дней (152-ФЗ)
    embedding_dim: int = 1024  # размерность эмбеддингов GigaChat
    llm_provider: Literal["gigachat", "yandexgpt"] = "gigachat"
    timezone: str = "Europe/Moscow"

    cors_origins: list[str] = Field(default_factory=list)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def _validate_secrets(self) -> Settings:
        if self.app_env == "prod":
            if not self.secret_key:
                raise ValueError("SECRET_KEY обязателен в prod")
            if not self.fernet_keys:
                raise ValueError("FERNET_KEYS обязателен в prod (шифрование credentials каналов)")
        return self

    # ---- Производные URL ----
    def _with_driver(self, driver: str) -> str:
        url = self.database_url
        for scheme in (
            "postgresql+asyncpg://",
            "postgresql+psycopg://",
            "postgres://",
            "postgresql://",
        ):
            if url.startswith(scheme):
                return driver + url[len(scheme) :]
        return url

    @property
    def async_db_url(self) -> str:
        return self._with_driver("postgresql+asyncpg://")

    @property
    def sync_db_url(self) -> str:
        return self._with_driver("postgresql+psycopg://")

    @property
    def fernet_key_list(self) -> list[str]:
        return [key.strip() for key in self.fernet_keys.split(",") if key.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
