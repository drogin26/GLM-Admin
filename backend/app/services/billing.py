"""Биллинг: проверка лимитов тарифов и учёт использования.

Тарифы:
  TRIAL  — 14 дней, до 50 диалогов
  BASIC  — 3 900 ₽/мес, до 300 диалогов
  PRO    — 5 990 ₽/мес, безлимит

Реальная интеграция ЮKassa — следующей итерацией.
Здесь — заглушка с проверкой лимитов и логированием.
"""

from __future__ import annotations

import datetime as dt
import logging
import typing as t

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PlanType, Subscription, SubscriptionStatus, UsageLog

logger = logging.getLogger(__name__)

# Тарифы
PLAN_CONFIG: dict[PlanType, dict[str, t.Any]] = {
    PlanType.TRIAL: {
        "name": "Триал",
        "price_rub": 0,
        "dialog_limit": 50,
        "period_days": 14,
        "description": "14 дней бесплатно, до 50 диалогов",
    },
    PlanType.BASIC: {
        "name": "Basic",
        "price_rub": 3900,
        "dialog_limit": 300,
        "period_days": 30,
        "description": "До 300 диалогов в месяц",
    },
    PlanType.PRO: {
        "name": "Pro",
        "price_rub": 5990,
        "dialog_limit": -1,  # безлимит
        "period_days": 30,
        "description": "Безлимитные диалоги",
    },
}


class PlanLimitExceeded(Exception):
    """Превышен лимит тарифа."""

    def __init__(self, plan: PlanType, current: int, limit: int) -> None:
        self.plan = plan
        self.current = current
        self.limit = limit
        super().__init__(f"Лимит тарифа {plan.value}: {current}/{limit}")


async def check_plan_limit(
    session: AsyncSession,
    business_id: sa.Column,  # type: ignore[name-defined]
    action: str = "llm_reply",
) -> None:
    """Проверить, не превышен ли лимит тарифа."""
    # Получаем подписку
    result = await session.execute(
        sa.select(Subscription).where(Subscription.business_id == business_id)
    )
    sub = result.scalar_one_or_none()

    if not sub:
        raise ValueError("Подписка не найдена")

    # Проверяем период
    if sub.period_end and sub.period_end < dt.datetime.now(dt.UTC):
        # Период истёк — триггерим продление
        if sub.auto_renew:
            logger.info("auto_renew_needed", extra={"business_id": str(business_id)})
        else:
            sub.status = SubscriptionStatus.PAST_DUE
            await session.commit()
            raise PlanLimitExceeded(sub.plan, 0, 0)

    # Безлимит
    if PLAN_CONFIG.get(sub.plan, {}).get("dialog_limit", 0) == -1:
        return

    # Считаем использование за период
    period_start = sub.period_end - dt.timedelta(days=30) if sub.period_end else dt.datetime.min.replace(tzinfo=dt.UTC)

    count_result = await session.execute(
        sa.select(sa.func.count(UsageLog.id)).where(
            UsageLog.business_id == business_id,
            UsageLog.action == "llm_reply",
            UsageLog.created_at >= period_start,
        )
    )
    current_usage = count_result.scalar() or 0

    limit = PLAN_CONFIG.get(sub.plan, {}).get("dialog_limit", 0)
    if current_usage >= limit:
        logger.warning(
            "plan_limit_exceeded",
            extra={"business_id": str(business_id), "plan": sub.plan.value, "usage": current_usage, "limit": limit},
        )
        raise PlanLimitExceeded(sub.plan, current_usage, limit)


async def log_usage(
    session: AsyncSession,
    business_id: sa.Column,  # type: ignore[name-defined]
    action: str,
    tokens: int = 0,
    meta: dict[str, t.Any] | None = None,
) -> None:
    """Залогировать использование ресурса."""
    session.add(
        UsageLog(
            business_id=business_id,
            action=action,
            llm_tokens=tokens,
            meta=meta or {},
        )
    )
    await session.flush()


async def upgrade_plan(
    session: AsyncSession,
    business_id: sa.Column,  # type: ignore[name-defined]
    new_plan: PlanType,
) -> dict[str, t.Any]:
    """Переключение тарифа (заглушка для ЮKassa)."""
    from app.models import PlanType

    result = await session.execute(
        sa.select(Subscription).where(Subscription.business_id == business_id)
    )
    sub = result.scalar_one_or_none()

    if not sub:
        # Создаём подписку
        sub = Subscription(
            business_id=business_id,
            plan=new_plan,
            status=SubscriptionStatus.ACTIVE,
            period_end=dt.datetime.now(dt.UTC) + dt.timedelta(days=30),
        )
        session.add(sub)
    else:
        sub.plan = new_plan
        sub.status = SubscriptionStatus.ACTIVE
        sub.period_end = dt.datetime.now(dt.UTC) + dt.timedelta(days=30)

    await session.commit()

    config = PLAN_CONFIG.get(new_plan, {})
    return {
        "plan": new_plan.value,
        "price_rub": config.get("price_rub", 0),
        "dialog_limit": config.get("dialog_limit", 0),
        "period_end": sub.period_end.isoformat() if sub.period_end else None,
    }


__all__ = [
    "PLAN_CONFIG",
    "PlanLimitExceeded",
    "check_plan_limit",
    "log_usage",
    "upgrade_plan",
]
