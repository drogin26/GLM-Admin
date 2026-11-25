"""Обслуживающие задачи."""

from __future__ import annotations

import logging

from app.celery_app import celery_app
from app.services.retention import cleanup_messages_older_than

logger = logging.getLogger(__name__)


@celery_app.task(name="maintenance.cleanup_old_messages", bind=True, max_retries=3, default_retry_delay=60)
def cleanup_old_messages(self) -> dict[str, int]:  # noqa: ANN001 (self — celery Task)
    from app.config import get_settings

    days = get_settings().retention_days
    try:
        deleted = cleanup_messages_older_than(days)
    except Exception as exc:
        logger.exception("retention_cleanup_failed", extra={"days": days})
        raise self.retry(exc=exc) from exc
    logger.info("retention_cleanup_done", extra={"deleted": deleted, "days": days})
    return {"deleted": deleted}
