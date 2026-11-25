"""Бизнес (арендатор кабинета)."""

from __future__ import annotations

import typing as t

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPkMixin, str_enum
from app.models.enums import PlanType

if t.TYPE_CHECKING:
    from app.models.billing import Subscription, UsageLog
    from app.models.channel import Channel
    from app.models.conversation import Conversation
    from app.models.knowledge import KnowledgeDoc
    from app.models.user import User

DEFAULT_WORKING_HOURS: dict[str, list[list[str]]] = {
    "mon": [["09:00", "19:00"]],
    "tue": [["09:00", "19:00"]],
    "wed": [["09:00", "19:00"]],
    "thu": [["09:00", "19:00"]],
    "fri": [["09:00", "19:00"]],
    "sat": [["10:00", "16:00"]],
    "sun": [],
}


class Business(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "businesses"

    name: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    plan: Mapped[PlanType] = mapped_column(
        str_enum(PlanType), default=PlanType.TRIAL, server_default=text("'trial'"), nullable=False
    )
    # chat_id владельца для карточек лидов и эскалаций
    telegram_notify_chat_id: Mapped[str | None] = mapped_column(sa.String(64))
    working_hours: Mapped[dict[str, t.Any]] = mapped_column(
        JSONB, default=lambda: dict(DEFAULT_WORKING_HOURS),
        server_default=text("'{}'::jsonb"), nullable=False,
    )
    # Полуавто по умолчанию: ИИ готовит черновики, владелец подтверждает (ТЗ)
    auto_mode: Mapped[bool] = mapped_column(
        sa.Boolean, default=False, server_default=text("false"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        sa.Boolean, default=True, server_default=text("true"), nullable=False
    )
    # Свободные настройки бизнеса: avg_order_price (оценка потерянной выручки),
    # тема виджета, правила эскалации и т.д.
    settings: Mapped[dict[str, t.Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )

    users: Mapped[list[User]] = relationship(back_populates="business")
    channels: Mapped[list[Channel]] = relationship(back_populates="business")
    conversations: Mapped[list[Conversation]] = relationship(back_populates="business")
    knowledge_docs: Mapped[list[KnowledgeDoc]] = relationship(back_populates="business")
    subscription: Mapped[Subscription | None] = relationship(back_populates="business", uselist=False)
    usage_logs: Mapped[list[UsageLog]] = relationship(back_populates="business")
