"""Канал связи: Telegram / ВКонтакте / чат-виджет.

credentials_enc — зашифрованный конверт (см. app.security): токены ботов
никогда не хранятся в открытом виде.
"""

from __future__ import annotations

import datetime as dt
import typing as t
import uuid

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPkMixin, str_enum
from app.models.enums import ChannelStatus, ChannelType

if t.TYPE_CHECKING:
    from app.models.business import Business
    from app.models.conversation import Conversation


class Channel(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "channels"

    business_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[ChannelType] = mapped_column(str_enum(ChannelType), nullable=False)
    credentials_enc: Mapped[dict[str, t.Any] | None] = mapped_column(JSONB)
    # username бота / id группы VK / публичный токен виджета
    external_id: Mapped[str | None] = mapped_column(sa.String(255))
    status: Mapped[ChannelStatus] = mapped_column(
        str_enum(ChannelStatus), default=ChannelStatus.DISABLED,
        server_default=text("'disabled'"), nullable=False,
    )
    last_error: Mapped[str | None] = mapped_column(sa.Text)
    last_error_at: Mapped[dt.datetime | None] = mapped_column(sa.DateTime(timezone=True))

    business: Mapped[Business] = relationship(back_populates="channels")
    conversations: Mapped[list[Conversation]] = relationship(back_populates="channel")
