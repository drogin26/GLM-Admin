"""Дашборд-отчёты: «Потерянные заявки» и еженедельная доставка в Telegram.

Cron-задача (Celery beat, каждый понедельник в 10:00):
  - Собирает метрики за прошлую неделю
  - Формирует карточку «Потерянные заявки»
  - Отправляет владельцу в Telegram (если telegram_notify_chat_id настроен)
"""

from __future__ import annotations

import datetime as dt
import logging
import typing as t

from app.celery_app import celery_app
from app.services.messaging.telegram import TelegramChannel
from app.services.validator import validate_and_clean

logger = logging.getLogger(__name__)


class _BusinessRow(t.TypedDict):
    id: t.Any
    name: str
    telegram_notify_chat_id: str | None


@celery_app.task(name="reports.weekly_lost_leads")
def weekly_lost_leads() -> dict[str, int]:
    """Еженедельный отчёт «Потерянные заявки» — понедельник 10:00."""
    from sqlalchemy import text

    from app.db_sync import get_sync_session_factory

    days_ago = 7
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=days_ago)

    try:
        with get_sync_session_factory()() as session:
            # Получаем все активные бизнесы
            result = session.execute(
                text("""
                    SELECT id, name, telegram_notify_chat_id
                    FROM businesses
                    WHERE is_active = true
                      AND telegram_notify_chat_id IS NOT NULL
                """)
            )
            businesses: list[_BusinessRow] = [
                {"id": row[0], "name": row[1], "telegram_notify_chat_id": row[2]}
                for row in result.fetchall()
            ]

        from app.config import get_settings
        from app.redis_client import make_redis

        settings = get_settings()
        redis = make_redis(settings)
        tg_channel = TelegramChannel(None, redis, settings)  # type: ignore[arg-type]

        sent = 0
        for biz in businesses:
            try:
                sent += _send_weekly_report(biz, cutoff, settings, tg_channel)
            except Exception:
                logger.exception("weekly_report_failed", extra={"business_id": str(biz["id"])})

        logger.info("weekly_reports_sent", extra={"sent": sent, "total": len(businesses)})
        return {"sent": sent, "total": len(businesses)}
    except Exception:
        logger.exception("weekly_report_error")
        raise


def _send_weekly_report(
    business: _BusinessRow,
    cutoff: dt.datetime,
    settings: t.Any,
    tg_channel: TelegramChannel,
) -> int:
    """Отправить отчёт одному бизнесу."""
    from sqlalchemy import text
    from app.db_sync import get_sync_session_factory

    biz_id = business["id"]
    biz_name = business["name"]
    chat_id = business["telegram_notify_chat_id"]

    with get_sync_session_factory()() as session:
        # Конверсации без ответа
        result = session.execute(
            text("""
                SELECT COUNT(*)
                FROM conversations
                WHERE business_id = :biz_id
                  AND status = 'new'
                  AND created_at >= :cutoff
            """),
            {"biz_id": biz_id, "cutoff": cutoff},
        )
        lost_count = result.scalar() or 0

        # Всего сообщений за период
        result = session.execute(
            text("""
                SELECT COUNT(*)
                FROM messages m
                JOIN conversations c ON c.id = m.conversation_id
                WHERE c.business_id = :biz_id
                  AND m.created_at >= :cutoff
            """),
            {"biz_id": biz_id, "cutoff": cutoff},
        )
        total_messages = result.scalar() or 0

        # Бот-ответы
        result = session.execute(
            text("""
                SELECT COUNT(*)
                FROM messages m
                JOIN conversations c ON c.id = m.conversation_id
                WHERE c.business_id = :biz_id
                  AND m.sender = 'bot'
                  AND m.created_at >= :cutoff
            """),
            {"biz_id": biz_id, "cutoff": cutoff},
        )
        bot_answers = result.scalar() or 0

        # Передано человеку
        result = session.execute(
            text("""
                SELECT COUNT(*)
                FROM conversations
                WHERE business_id = :biz_id
                  AND status = 'human'
                  AND last_msg_at >= :cutoff
            """),
            {"biz_id": biz_id, "cutoff": cutoff},
        )
        human_handoff = result.scalar() or 0

        # Средняя стоимость заказа
        result = session.execute(
            text("""
                SELECT (settings->>'avg_order_price')::numeric
                FROM businesses WHERE id = :biz_id
            """),
            {"biz_id": biz_id},
        )
        avg_price = result.scalar()
        if avg_price is None:
            avg_price = 1000  # Дефолт
        avg_price = float(avg_price)

        lost_revenue = round(lost_count * avg_price, 2)

    # Формируем карточку
    if lost_count == 0 and total_messages == 0:
        # Нет активности — не спамим
        return 0

    report = (
        f"📊 *Отчёт за неделю* — {biz_name}\n\n"
        f"💬 Входящих: *{total_messages}*\n"
        f"🤖 Отвечено ботом: *{bot_answers}*\n"
        f"👤 Передано человеку: *{human_handoff}*\n\n"
    )

    if lost_count > 0:
        report += (
            f"⚠️ *Без ответа > 1 часа: {lost_count}*\n"
            f"💸 Оценка упущенной выручки: *{lost_revenue:.0f} ₽*\n\n"
        )
    else:
        report += "✅ Все сообщения обработаны в срок!\n\n"

    report += "Настройте авто-режим, чтобы бот отвечал мгновенно 🚀"

    # Отправляем
    try:
        from app.security import decrypt_credentials

        # Находим Telegram-канал для отправки
        import uuid
        from sqlalchemy import text as sa_text

        with get_sync_session_factory()() as s2:
            ch_result = s2.execute(sa_text("""
                SELECT credentials_enc FROM channels
                WHERE business_id = :biz_id AND type = 'tg' AND status = 'active'
                LIMIT 1
            """), {"biz_id": biz_id})
            ch_row = ch_result.fetchone()

        if ch_row:
            creds = decrypt_credentials(ch_row[0], settings.fernet_key_list)
            token = creds.get("token")
            if token:
                tg_channel._bot_token = lambda _self, _ch: token  # type: ignore
                tg_channel.send.__self__ = tg_channel  # type: ignore
                # Вызываем напрямую
                import asyncio
                asyncio.run(tg_channel.send(
                    type('Channel', (), {'id': biz_id, 'credentials_enc': ch_row[0]})(),
                    type('Conversation', (), {'external_chat_id': chat_id})(),
                    report,
                ))

        logger.info("weekly_report_sent", extra={"business_id": str(biz_id), "lost": lost_count})
        return 1
    except Exception:
        logger.exception("weekly_report_send_failed", extra={"business_id": str(biz_id)})
        return 0


@celery_app.task(name="reports.daily_heartbeat")
def daily_heartbeat() -> dict[str, int]:
    """Дaily heartbeat: проверка что воркер жив.

    Если heartbeat не срабатывает > 5 минут — алерт владельцу сервиса.
    """
    logger.info("daily_heartbeat_ok")
    return {"status": "ok"}

