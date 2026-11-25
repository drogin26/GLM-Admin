"""Тесты конфигурации (чистые, без БД)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings

pytestmark = pytest.mark.asyncio(loop_scope="session")  # общий session-loop с движками из conftest



def test_database_url_driver_injection():
    settings = Settings(database_url="postgresql://u:p@h:5432/db")
    assert settings.async_db_url == "postgresql+asyncpg://u:p@h:5432/db"
    assert settings.sync_db_url == "postgresql+psycopg://u:p@h:5432/db"


def test_database_url_driver_preserved():
    settings = Settings(database_url="postgresql+asyncpg://u:p@h:5432/db")
    assert settings.async_db_url == "postgresql+asyncpg://u:p@h:5432/db"
    assert settings.sync_db_url == "postgresql+psycopg://u:p@h:5432/db"


def test_legacy_postgres_scheme():
    settings = Settings(database_url="postgres://u:p@h:5432/db")
    assert settings.async_db_url == "postgresql+asyncpg://u:p@h:5432/db"


def test_fernet_keys_split():
    settings = Settings(fernet_keys="k1, k2 ,k3")
    assert settings.fernet_key_list == ["k1", "k2", "k3"]


def test_cors_comma_string(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://a, http://b")
    assert Settings().cors_origins == ["http://a", "http://b"]


def test_prod_requires_secret_key():
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(app_env="prod", secret_key="", fernet_keys="k")


def test_prod_requires_fernet_keys():
    with pytest.raises(ValidationError, match="FERNET_KEYS"):
        Settings(app_env="prod", secret_key="s", fernet_keys="")


def test_prod_ok_with_secrets():
    settings = Settings(app_env="prod", secret_key="s", fernet_keys="k")
    assert settings.retention_days == 90
