"""Аутентификация кабинета: JWT через python-jose.

Заглушка: в MVP используем simple JWT-based auth.
В продакшене заменить на OAuth2 + refresh tokens.
"""

from __future__ import annotations

import datetime as dt
import typing as t
import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import BaseModel

from app.config import get_settings

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 часа

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


class TokenData(BaseModel):
    sub: uuid.UUID
    business_id: uuid.UUID | None = None
    role: str
    exp: dt.datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


def create_access_token(user_id: uuid.UUID, business_id: uuid.UUID | None, role: str) -> str:
    settings = get_settings()
    expire = dt.datetime.now(dt.UTC) + dt.timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "business_id": str(business_id) if business_id else None,
        "role": role,
        "exp": expire,
        "iat": dt.datetime.now(dt.UTC),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def verify_token(token: str = Depends(oauth2_scheme)) -> TokenData:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        return TokenData(
            sub=uuid.UUID(payload["sub"]),
            business_id=uuid.UUID(payload["business_id"]) if payload.get("business_id") else None,
            role=payload.get("role", "owner"),
            exp=dt.datetime.fromisoformat(payload["exp"]),
        )
    except (JWTError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Недействительный токен",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def get_current_user(
    token_data: TokenData = Depends(verify_token),
) -> dict[str, t.Any]:
    """Получить данные текущего пользователя из токена."""
    return {
        "id": token_data.sub,
        "business_id": token_data.business_id,
        "role": token_data.role,
    }


class LoginRequest(BaseModel):
    email: str
    password: str


__all__ = [
    "create_access_token",
    "verify_token",
    "get_current_user",
    "oauth2_scheme",
    "Token",
    "TokenData",
    "LoginRequest",
]
