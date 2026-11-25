"""Структурированное логирование: JSON-формат + request_id в контексте."""

from __future__ import annotations

import contextvars
import logging
import sys
import uuid

import orjson

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

# Атрибуты LogRecord, которые не попадают в JSON-полезную нагрузку как «extras»
_RESERVED = frozenset(
    {
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename", "module",
        "exc_info", "exc_text", "stack_info", "lineno", "funcName", "created", "msecs",
        "relativeCreated", "thread", "threadName", "processName", "process", "taskName",
        "message", "asctime", "stack_trace",
    }
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return orjson.dumps(payload, default=str).decode()


def setup_logging(level: str = "INFO", json_output: bool = True) -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if json_output else
                         logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s"))
    root.addHandler(handler)

    # Шумные библиотеки — только предупреждения
    for name in ("uvicorn.access", "sqlalchemy.engine", "asyncio", "celery.utils.log"):
        logging.getLogger(name).setLevel(logging.WARNING)
    # uvicorn идёт через root-обработчик (единый JSON-формат)
    for name in ("uvicorn", "uvicorn.error"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers.clear()
        uv_logger.propagate = True


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]
