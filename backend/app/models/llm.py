"""Аудит вызовов LLM (требование ТЗ: логировать все ответы модели)."""

from __future__ import annotations

import datetime as dt
import uuid

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPkMixin

if False:  # только для типов, без цикла импорта в рантайме
    from app.models.conversation import Conversation


class LLMCallLog(UUIDPkMixin, Base):
    __tablename__ = "llm_calls"

    # SET NULL: лог переживает удаление диалога (персданные чистятся, аудит остаётся)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("conversations.id", ondelete="SET NULL")
    )
    provider: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    model: Mapped[str | None] = mapped_column(sa.String(64))
    prompt_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    response: Mapped[str | None] = mapped_column(sa.Text)
    escalated: Mapped[bool] = mapped_column(
        sa.Boolean, default=False, server_default=text("false"), nullable=False
    )
    tokens_in: Mapped[int] = mapped_column(sa.Integer, default=0, server_default=text("0"), nullable=False)
    tokens_out: Mapped[int] = mapped_column(sa.Integer, default=0, server_default=text("0"), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(sa.Integer)
    created_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True
    )

    conversation: Mapped[Conversation | None] = relationship(back_populates="llm_calls")

    __table_args__ = (
        sa.Index("ix_llm_calls_conversation", "conversation_id"),
    )
