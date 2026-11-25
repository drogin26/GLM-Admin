"""Лид — результат квалификации диалога (итерация 4)."""

from __future__ import annotations

import datetime as dt
import typing as t
import uuid

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPkMixin, str_enum
from app.models.enums import LeadScore, LeadUrgency

if t.TYPE_CHECKING:
    from app.models.conversation import Conversation


class Lead(UUIDPkMixin, Base):
    __tablename__ = "leads"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    summary: Mapped[str] = mapped_column(sa.Text, nullable=False)
    urgency: Mapped[LeadUrgency] = mapped_column(
        str_enum(LeadUrgency), default=LeadUrgency.NORMAL,
        server_default=text("'normal'"), nullable=False,
    )
    city: Mapped[str | None] = mapped_column(sa.String(128))
    phone: Mapped[str | None] = mapped_column(sa.String(32))
    score: Mapped[LeadScore] = mapped_column(
        str_enum(LeadScore), default=LeadScore.WARM,
        server_default=text("'warm'"), nullable=False,
    )
    # Сырые извлечённые сущности (что нужно, адрес, сроки) для карточки лида
    extra: Mapped[dict[str, t.Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
    notified: Mapped[bool] = mapped_column(
        sa.Boolean, default=False, server_default=text("false"), nullable=False
    )
    notified_at: Mapped[dt.datetime | None] = mapped_column(sa.DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True
    )

    conversation: Mapped[Conversation] = relationship(back_populates="leads")

    __table_args__ = (
        sa.Index("ix_leads_conversation", "conversation_id"),
        sa.Index("ix_leads_notified", "notified"),
    )
