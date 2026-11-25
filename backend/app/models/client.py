"""Клиент (end user) — для сквозной идентификации между каналами.

Совпадение телефона (собирает бот) связывает диалоги из Telegram, VK и виджета
в один профиль в рамках бизнеса.
"""

from __future__ import annotations

import typing as t
import uuid

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPkMixin

if t.TYPE_CHECKING:
    from app.models.business import Business
    from app.models.conversation import Conversation


class Client(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "clients"

    business_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False
    )
    phone: Mapped[str | None] = mapped_column(sa.String(32))
    name: Mapped[str | None] = mapped_column(sa.String(255))
    # {"tg": "<chat_id>", "vk": "<user_id>", "widget": "<visitor_id>"}
    external_refs: Mapped[dict[str, t.Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )

    business: Mapped[Business] = relationship()
    conversations: Mapped[list[Conversation]] = relationship(back_populates="client")

    __table_args__ = (
        sa.Index("ix_clients_business_phone", "business_id", "phone", unique=True),
    )
