"""Владелец бизнеса (пользователь кабинета)."""

from __future__ import annotations

import typing as t
import uuid

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPkMixin

if t.TYPE_CHECKING:
    from app.models.business import Business


class User(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(sa.String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    # owner | admin (расширяемо без миграции данных)
    role: Mapped[str] = mapped_column(
        sa.String(32), default="owner", server_default=text("'owner'"), nullable=False
    )
    business_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("businesses.id", ondelete="SET NULL")
    )
    is_active: Mapped[bool] = mapped_column(
        sa.Boolean, default=True, server_default=text("true"), nullable=False
    )

    business: Mapped[Business | None] = relationship(back_populates="users")
