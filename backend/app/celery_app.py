"""Celery: воркер + beat.

Локально на Windows воркер запускать с пулом solo:
    celery -A app.celery_app:celery worker -P solo --loglevel=info
В Docker (Linux) — обычный prefork.
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "aiadmin",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.tasks.maintenance",
        "app.tasks.polling",
        "app.tasks.reports",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone=settings.timezone,
    enable_utc=True,
    # Задачи не теряются при падении воркера: ack после выполнения
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    task_ignore_result=True,
    beat_schedule={
        # Еженедельный отчёт «Потерянные заявки» — понедельник 10:00 MSK
        "reports.weekly_lost_leads": {
            "task": "reports.weekly_lost_leads",
            "schedule": crontab(hour=10, day_of_week=1),
        },
        # Fallback-поллинг Telegram: ищем потерянные webhook-сообщения каждые 30 сек
        "polling.telegram_fallback": {
            "task": "polling.telegram_fallback",
            "schedule": 30.0,
        },
        # Daily heartbeat для алертов
        "reports.daily_heartbeat": {
            "task": "reports.daily_heartbeat",
            "schedule": 3600.0,
        },
        # Автоочистка переписки (90 дней, ограничение по персданным)
        "maintenance.cleanup_old_messages": {
            "task": "maintenance.cleanup_old_messages",
            "schedule": crontab(hour=3, minute=0),
        },
    },
)
