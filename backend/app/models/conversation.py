"""Диалог: клиент ↔ канал ↔ бизнес."""

from __future__ import annotations

import datetime as dt
import typing as t
import uuid

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPkMixin, str_enum
from app.models.enums import ConversationStatus

if t.TYPE_CHECKING:
    from app.models.business import Business
    from app.models.channel import Channel
    from app.models.client import Client
    from app.models.lead import Lead
    from app.models.llm import LLMCallLog
    from app.models.message import Message


class Conversation(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "conversations"

    business_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("channels.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("clients.id", ondelete="SET NULL")
    )
    # Идентификатор чата в канале (chat_id TG, peer_id VK, visitor_id виджета)
    external_chat_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    client_name: Mapped[str | None] = mapped_column(sa.String(255))
    client_phone: Mapped[str | None] = mapped_column(sa.String(32))
    status: Mapped[ConversationStatus] = mapped_column(
        str_enum(ConversationStatus), default=ConversationStatus.NEW,
        server_default=text("'new'"), nullable=False,
    )
    last_msg_at: Mapped[dt.datetime | None] = mapped_column(sa.DateTime(timezone=True))

    business: Mapped[Business] = relationship(back_populates="conversations")
    channel: Mapped[Channel] = relationship(back_populates="conversations")
    client: Mapped[Client | None] = relationship(back_populates="conversations")
    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan",
        order_by="Message.created_at",
    )
    leads: Mapped[list[Lead]] = relationship(back_populates="conversation")
    llm_calls: Mapped[list[LLMCallLog]] = relationship(back_populates="conversation")

    __table_args__ = (
        sa.UniqueConstraint("channel_id", "external_chat_id", name="uq_conversations_channel_chat"),
        sa.Index("ix_conversations_business_status", "business_id", "status"),
        sa.Index("ix_conversations_last_msg_at", "last_msg_at"),
    )
