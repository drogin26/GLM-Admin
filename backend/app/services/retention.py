"""Автоочистка переписки: 90 дней (ограничение ТЗ по персданным, 152-ФЗ).

Диалоги и лиды остаются (аналитика), удаляются только тексты сообщений.
Партиями, чтобы не держать длинные транзакции на больших объёмах.
"""

from __future__ import annotations

import datetime as dt

import sqlalchemy as sa

from app.db_sync import get_sync_session_factory
from app.models import Message

BATCH_SIZE = 50_000


def cleanup_messages_older_than(days: int, now: dt.datetime | None = None) -> int:
    cutoff = (now or dt.datetime.now(dt.UTC)) - dt.timedelta(days=days)
    deleted_total = 0
    with get_sync_session_factory()() as session:
        while True:
            subquery = sa.select(Message.id).where(Message.created_at < cutoff).limit(BATCH_SIZE)
            result = session.execute(sa.delete(Message).where(Message.id.in_(subquery)))
            session.commit()
            deleted = result.rowcount or 0
            deleted_total += deleted
            if deleted < BATCH_SIZE:
                break
    return deleted_total
