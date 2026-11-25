"""Криптография: шифрование credentials каналов (Fernet) и пароли владельцев (bcrypt).

Credentials каналов (токены ботов и т.п.) хранятся в JSONB-конверте:
    {"v": 1, "data": "<fernet-token>"}
Токен шифрует JSON со secrets. Поддерживается ротация ключей: шифруем первым
ключом списка, расшифровываем любым (MultiFernet).
"""

from __future__ import annotations

import json
import secrets
from typing import Any

import bcrypt
from cryptography.fernet import Fernet, InvalidToken, MultiFernet

CREDENTIALS_ENVELOPE_VERSION = 1


class CredentialsDecryptionError(Exception):
    """Не удалось расшифровать credentials канала."""


def generate_fernet_key() -> str:
    return Fernet.generate_key().decode()


def make_fernet(keys: list[str]) -> MultiFernet:
    if not keys:
        raise ValueError("Список ключей Fernet пуст")
    return MultiFernet([Fernet(key.strip()) for key in keys])


def encrypt_credentials(credentials: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    """Шифрует словарь credentials в JSONB-конверт. Первый ключ — основной."""
    fernet = make_fernet(keys)
    raw = json.dumps(credentials, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    token = fernet.encrypt(raw)
    return {"v": CREDENTIALS_ENVELOPE_VERSION, "data": token.decode("ascii")}


def decrypt_credentials(envelope: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    try:
        version = int(envelope.get("v", 0))
        token = envelope["data"].encode("ascii")
    except (KeyError, TypeError, ValueError, UnicodeEncodeError) as exc:
        raise CredentialsDecryptionError(f"Некорректный конверт credentials: {exc}") from exc
    if version != CREDENTIALS_ENVELOPE_VERSION:
        raise CredentialsDecryptionError(f"Неизвестная версия конверта: {version}")
    try:
        raw = make_fernet(keys).decrypt(token, ttl=None)
    except InvalidToken as exc:
        raise CredentialsDecryptionError("Неверный ключ или повреждённые данные") from exc
    return json.loads(raw)


# --- Пароли владельцев (кабинет, итерация 7) ---

def hash_password(password: str) -> str:
    if len(password.encode("utf-8")) > 72:  # ограничение bcrypt
        raise ValueError("Пароль длиннее 72 байт")
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode())
    except ValueError:
        return False


def generate_webhook_secret() -> str:
    """Секрет для верификации вебхуков (VK confirmation_code / подпись)."""
    return secrets.token_urlsafe(32)
