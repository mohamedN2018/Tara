"""Realtime gateway settings (Django Channels / ASGI). Holds NO source of truth.

No database: the gateway owns only socket connections + presence (Redis) and
bridges the event bus to clients. Critical state lives in Chat/Notification/Feed.
"""

from __future__ import annotations

import os
from pathlib import Path

from tara_observability.logging import build_logging_config

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in ("1", "true", "yes", "on")


def env_list(name: str, default: str = "") -> list[str]:
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


SECRET_KEY = os.getenv("REALTIME_SECRET_KEY", "dev-only-insecure-secret-change-me")
DEBUG = env_bool("REALTIME_DEBUG", False)
ALLOWED_HOSTS = env_list("REALTIME_ALLOWED_HOSTS", "localhost,127.0.0.1")
SERVICE_NAME = "realtime"
CHAT_INTERNAL_URL = os.getenv("CHAT_INTERNAL_URL", "http://chat:8000")
GRAPH_INTERNAL_URL = os.getenv("GRAPH_INTERNAL_URL", "http://graph:8000")
INTERNAL_CALL_TIMEOUT = float(os.getenv("INTERNAL_CALL_TIMEOUT", "2.0"))
TARA_INTERNAL_JWT_SECRET = os.getenv("INTERNAL_JWT_SECRET", "dev-only-internal-secret-change-me")

INSTALLED_APPS = [
    "django_prometheus",
    "channels",
    "realtime",
]

MIDDLEWARE = [
    "django_prometheus.middleware.PrometheusBeforeMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django_prometheus.middleware.PrometheusAfterMiddleware",
]

ROOT_URLCONF = "config.urls"
ASGI_APPLICATION = "config.asgi.application"
TEMPLATES = []
DATABASES = {}  # gateway has no database

REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/7")
CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL}
}

# Channel layer (Redis in dev/prod; tests override to in-memory).
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [REDIS_URL]},
    }
}

# Token verification (same JWKS/PEM contract as the REST services).
TARA_JWKS_URL = os.getenv("TARA_JWKS_URL", "http://identity:8000/.well-known/jwks.json")
TARA_JWT_PUBLIC_KEY = os.getenv("TARA_JWT_PUBLIC_KEY", "")
TARA_JWT_ISSUER = os.getenv("JWT_ISSUER", "tara-identity")
TARA_JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "tara")
TARA_JWKS_CACHE_TTL = int(os.getenv("TARA_JWKS_CACHE_TTL", "300"))

# Event bus (the bridge consumes domain events and pushes to sockets).
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "")
TARA_EVENT_BROKER_URL = RABBITMQ_URL
TARA_EVENT_EXCHANGE = os.getenv("TARA_EVENT_EXCHANGE", "tara.events")
TARA_EVENT_QUEUE = "realtime.events"

# Presence (realtime/presence.py): a socket counts as live for PRESENCE_TTL
# seconds after its last frame (clients ping every 30 s); the per-account key
# expires on its own after PRESENCE_KEY_TTL. "memory" keeps it in-process.
PRESENCE_BACKEND = os.getenv("PRESENCE_BACKEND", "redis")
PRESENCE_TTL = int(os.getenv("PRESENCE_TTL", "70"))
PRESENCE_KEY_TTL = int(os.getenv("PRESENCE_KEY_TTL", "120"))
PRESENCE_AUDIENCE_TTL = int(os.getenv("PRESENCE_AUDIENCE_TTL", "60"))
PRESENCE_QUERY_MAX = 100
TYPING_MIN_INTERVAL = 2.0

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.getenv("TZ", "UTC")
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"

LOGGING = build_logging_config(
    SERVICE_NAME,
    level=os.getenv("LOG_LEVEL", "INFO"),
    fmt=os.getenv("LOG_FORMAT", "json" if not DEBUG else "console"),
)
