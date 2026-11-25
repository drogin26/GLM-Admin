"""Биллинг: подписка и лог использования (лимиты тарифов)."""

from __future__ import annotations

import datetime as dt
import typing as t
import uuid

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPkMixin, str_enum
from app.models.enums import PlanType, SubscriptionStatus

if t.TYPE_CHECKING:
    from app.models.business import Business


class Subscription(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "subscriptions"

    business_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    plan: Mapped[PlanType] = mapped_column(str_enum(PlanType), nullable=False)
    status: Mapped[SubscriptionStatus] = mapped_column(
        str_enum(SubscriptionStatus), default=SubscriptionStatus.TRIALING,
        server_default=text("'trialing'"), nullable=False,
    )
    period_end: Mapped[dt.datetime | None] = mapped_column(sa.DateTime(timezone=True))
    auto_renew: Mapped[bool] = mapped_column(
        sa.Boolean, default=True, server_default=text("true"), nullable=False
    )

    business: Mapped[Business] = relationship(back_populates="subscription")


class UsageLog(UUIDPkMixin, Base):
    """Лимиты тарифов и биллинг: action = llm_reply | embed | escalation | ..."""

    __tablename__ = "usage_logs"

    business_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    llm_tokens: Mapped[int] = mapped_column(sa.Integer, default=0, server_default=text("0"), nullable=False)
    meta: Mapped[dict[str, t.Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )

    business: Mapped[Business] = relationship(back_populates="usage_logs")

    __table_args__ = (
        sa.Index("ix_usage_logs_business_created", "business_id", "created_at"),
        sa.Index("ix_usage_logs_business_action", "business_id", "action"),
    )
