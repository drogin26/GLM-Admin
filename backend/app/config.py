"""Конфигурация приложения: все настройки приходят из переменных окружения (12-factor).

Локальная разработка может использовать `.env` рядом с `backend/`.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from cryptography.fernet import Fernet


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

    cors_origins_str: str = Field(default="", alias="CORS_ORIGINS")

    @property
    def cors_origins(self) -> list[str]:
        if not self.cors_origins_str:
            return []
        return [item.strip() for item in self.cors_origins_str.split(",") if item.strip()]

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
        keys = [key.strip() for key in self.fernet_keys.split(",") if key.strip()]
        if keys:
            return keys
        # Если FERNET_KEYS не задан — генерируем временный ключ и предупреждаем.
        # Это удобно для dev и для first-run, когда .env ещё не заполнен.
        import warnings

        warnings.warn(
            "FERNET_KEYS не задан: сгенерирован временный ключ. "
            "Данные, зашифрованные этим ключом, будут невалидны после перезапуска. "
            "Добавьте FERNET_KEYS в .env для стабильной работы.",
            RuntimeWarning,
            stacklevel=2,
        )
        return [Fernet.generate_key().decode()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
