"""Тесты шифрования credentials и паролей."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app.security import (

pytestmark = pytest.mark.asyncio(loop_scope="session")  # общий session-loop с движками из conftest

    CredentialsDecryptionError,
    decrypt_credentials,
    encrypt_credentials,
    generate_webhook_secret,
    hash_password,
    verify_password,
)

KEY1 = Fernet.generate_key().decode()
KEY2 = Fernet.generate_key().decode()


def test_encrypt_decrypt_roundtrip():
    credentials = {"token": "12345:ABC-DEF", "секрет": "привет ✋"}
    envelope = encrypt_credentials(credentials, [KEY1])
    assert envelope["v"] == 1
    assert "data" in envelope
    assert credentials["token"] not in envelope["data"]  # открытым текстом не лежит
    assert decrypt_credentials(envelope, [KEY1]) == credentials


def test_key_rotation():
    envelope = encrypt_credentials({"token": "t"}, [KEY1])
    # Новый ключ первым, старый — вторым: старые записи расшифровываются
    assert decrypt_credentials(envelope, [KEY2, KEY1]) == {"token": "t"}


def test_wrong_key_raises():
    envelope = encrypt_credentials({"token": "t"}, [KEY1])
    with pytest.raises(CredentialsDecryptionError):
        decrypt_credentials(envelope, [KEY2])


def test_tampered_data_raises():
    envelope = encrypt_credentials({"token": "t"}, [KEY1])
    envelope["data"] = envelope["data"][:-4] + "AAAA"
    with pytest.raises(CredentialsDecryptionError):
        decrypt_credentials(envelope, [KEY1])


@pytest.mark.parametrize("envelope", [{}, {"v": 1}, {"v": 2, "data": ""}, {"v": 1, "data": "not-base64!"}])
def test_bad_envelopes_raise(envelope):
    with pytest.raises(CredentialsDecryptionError):
        decrypt_credentials(envelope, [KEY1])


def test_password_hash_and_verify():
    password_hash = hash_password("пароль123")
    assert password_hash != "пароль123"
    assert password_hash.startswith("$2b$")
    assert verify_password("пароль123", password_hash)
    assert not verify_password("другой", password_hash)


def test_password_too_long_rejected():
    with pytest.raises(ValueError):
        hash_password("x" * 100)


def test_webhook_secret_shape():
    secret = generate_webhook_secret()
    assert len(secret) >= 32
    assert all(c.isalnum() or c in "-_" for c in secret)
