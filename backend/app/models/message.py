"""Сообщение диалога. Хранится целиком — на него опираются RAG-контекст и отчёты.

external_id + UNIQUE (conversation_id, external_id) — дедупликация повторных
вебхуков (Telegram ретраит доставку при недоступности сервера).
"""

from __future__ import annotations

import datetime as dt
import typing as t
import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPkMixin, str_enum
from app.models.enums import MessageDirection, MessageSender

if t.TYPE_CHECKING:
    from app.models.conversation import Conversation


class Message(UUIDPkMixin, Base):
    __tablename__ = "messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    direction: Mapped[MessageDirection] = mapped_column(str_enum(MessageDirection), nullable=False)
    sender: Mapped[MessageSender] = mapped_column(str_enum(MessageSender), nullable=False)
    text: Mapped[str] = mapped_column(sa.Text, nullable=False)
    external_id: Mapped[str | None] = mapped_column(sa.String(128))
    # Сырье для аналитики: provider, model, escalated, токены, черновик и т.д.
    llm_metadata: Mapped[dict[str, t.Any]] = mapped_column(
        JSONB, default=dict, server_default=sa.text("'{}'::jsonb"), nullable=False
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")

    __table_args__ = (
        sa.Index("ix_messages_conversation_created", "conversation_id", "created_at"),
        sa.UniqueConstraint("conversation_id", "external_id", name="uq_messages_conversation_external"),
    )
