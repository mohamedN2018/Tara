"""Structured JSON logging.

Every log line carries `service`, `request_id` (when bound), level, logger, and
message. A context-var holds the current request id so any log within a request
is correlated without threading it through call sites. NEVER log secrets, raw
message bodies, tokens, or passwords.
"""

from __future__ import annotations

import contextvars
import logging

_request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "tara_request_id", default=None
)


def bind_request_id(request_id: str | None) -> None:
    _request_id_var.set(request_id)


def current_request_id() -> str | None:
    return _request_id_var.get()


class RequestContextFilter(logging.Filter):
    """Inject request_id + service name into every record."""

    def __init__(self, service: str = "unknown") -> None:
        super().__init__()
        self.service = service

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = current_request_id()
        record.service = self.service
        return True


def build_logging_config(service: str, *, level: str = "INFO", fmt: str = "json") -> dict:
    """Return a Django LOGGING dict. ``fmt`` = 'json' (prod) or 'console' (dev)."""
    formatter = (
        {
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
            "format": "%(asctime)s %(levelname)s %(name)s %(service)s %(request_id)s %(message)s",
            "rename_fields": {"asctime": "ts", "levelname": "level", "name": "logger"},
        }
        if fmt == "json"
        else {
            "format": "%(asctime)s [%(levelname)s] %(name)s [%(request_id)s] %(message)s",
        }
    )
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "request_context": {
                "()": "tara_observability.logging.RequestContextFilter",
                "service": service,
            }
        },
        "formatters": {"default": formatter},
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "filters": ["request_context"],
            }
        },
        "root": {"handlers": ["console"], "level": level},
        "loggers": {
            "django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False},
            "tara": {"handlers": ["console"], "level": level, "propagate": False},
        },
    }
