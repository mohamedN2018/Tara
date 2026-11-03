"""Admin service settings."""

from __future__ import annotations

import os
from pathlib import Path

from tara_common.rate_limits import api_throttling
from tara_observability.logging import build_logging_config

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in ("1", "true", "yes", "on")


def env_list(name: str, default: str = "") -> list[str]:
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


SECRET_KEY = os.getenv("ADMIN_SECRET_KEY", "dev-only-insecure-secret-change-me")
DEBUG = env_bool("ADMIN_DEBUG", False)
ALLOWED_HOSTS = env_list("ADMIN_ALLOWED_HOSTS", "localhost,127.0.0.1")
SERVICE_NAME = "admin"

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "rest_framework",
    "drf_spectacular",
    "corsheaders",
    "django_prometheus",
    "adminsvc",
]

MIDDLEWARE = [
    "django_prometheus.middleware.PrometheusBeforeMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "tara_common.middleware.RequestIDMiddleware",
    "django_prometheus.middleware.PrometheusAfterMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
TEMPLATES = []

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "ATOMIC_REQUESTS": True,
        "NAME": os.getenv("ADMIN_DB_NAME", "admin_db"),
        "USER": os.getenv("ADMIN_DB_USER", "adminsvc"),
        "PASSWORD": os.getenv("ADMIN_DB_PASSWORD", "admin-dev-pass"),
        "HOST": os.getenv("POSTGRES_HOST", "127.0.0.1"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": os.getenv("REDIS_URL", "redis://127.0.0.1:6379/12"),
    }
}

_throttling = api_throttling()
REST_FRAMEWORK = {
    **_throttling,
    "DEFAULT_THROTTLE_RATES": {
        **_throttling["DEFAULT_THROTTLE_RATES"],
        "audit_export": os.getenv("ADMIN_AUDIT_EXPORT_RATE", "10/min"),
    },
    "DEFAULT_AUTHENTICATION_CLASSES": ["tara_common.auth.JWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "tara_common.pagination.CursorPagination",
    "PAGE_SIZE": 30,
    "EXCEPTION_HANDLER": "tara_common.exceptions.tara_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Tara Admin API",
    "DESCRIPTION": "Feature flags, roles, capability matrix, audit log, monitoring.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": "/api/v1",
}

TARA_JWKS_URL = os.getenv("TARA_JWKS_URL", "http://identity:8000/.well-known/jwks.json")
TARA_JWT_PUBLIC_KEY = os.getenv("TARA_JWT_PUBLIC_KEY", "")
TARA_JWT_ISSUER = os.getenv("JWT_ISSUER", "tara-identity")
TARA_JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "tara")
TARA_INTERNAL_JWT_SECRET = os.getenv("INTERNAL_JWT_SECRET", "dev-only-internal-secret-change-me")
# Shared with identity alone (roadmap 1.0d): signs calls to identity's role and
# staff API, which refuses INTERNAL_JWT_SECRET. The deploy check rejects a
# missing, short or development value.
ADMIN_IDENTITY_SECRET = os.getenv(
    "ADMIN_IDENTITY_SECRET", "dev-only-admin-identity-secret-change-me"
)
IDENTITY_INTERNAL_URL = os.getenv("IDENTITY_INTERNAL_URL", "http://identity:8000")
IDENTITY_CALL_TIMEOUT = float(os.getenv("IDENTITY_CALL_TIMEOUT", "3"))

# Services whose /readyz the beat task polls (every HEALTH_POLL_SECONDS).
HEALTH_TARGETS = {
    "identity": "http://identity:8000/readyz/",
    "profile": "http://profile:8000/readyz/",
    "graph": "http://graph:8000/readyz/",
    "media": "http://media:8000/readyz/",
    "post": "http://post:8000/readyz/",
    "feed": "http://feed:8000/readyz/",
    "chat": "http://chat:8000/readyz/",
    "marketplace": "http://marketplace:8000/readyz/",
    "notification": "http://notification:8000/readyz/",
    "search": "http://search:8000/readyz/",
    "moderation": "http://moderation:8000/readyz/",
    "ads": "http://ads:8000/readyz/",
    "realtime": "http://realtime:8000/readyz/",
    "admin": "http://admin:8000/readyz/",
    "bff": os.getenv("ADMIN_BFF_READY_URL", "http://bff:8090/readyz"),
}
HEALTH_TIMEOUT = float(os.getenv("ADMIN_HEALTH_TIMEOUT", "2.0"))
HEALTH_POLL_SECONDS = float(os.getenv("ADMIN_HEALTH_POLL_SECONDS", "30"))
# Health snapshots kept per service; older ones are deleted on each poll.
HEALTH_SNAPSHOTS_KEPT = int(os.getenv("ADMIN_HEALTH_SNAPSHOTS_KEPT", "500"))

# Platform statistics (8.11): each owner counts its own rows at
# /internal/v1/stats/ (shared internal secret, audience <service>-internal).
STATS_TARGETS = {
    "identity": "http://identity:8000",
    "post": "http://post:8000",
    "chat": "http://chat:8000",
    "marketplace": "http://marketplace:8000",
    "moderation": "http://moderation:8000",
}
STATS_TIMEOUT = float(os.getenv("ADMIN_STATS_TIMEOUT", "5.0"))
STATS_POLL_SECONDS = float(os.getenv("ADMIN_STATS_POLL_SECONDS", "300"))

# The audit CSV export streams at most this many rows (newest first).
ADMIN_AUDIT_EXPORT_MAX_ROWS = int(os.getenv("ADMIN_AUDIT_EXPORT_MAX_ROWS", "10000"))

# Events: admin consumes audit-worthy events (queue admin.events). Its outbox
# exists for the shared relay and purge tasks; admin emits nothing yet.
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "")
TARA_EVENT_PUBLISHER = "rabbitmq" if RABBITMQ_URL else "null"
TARA_EVENT_BROKER_URL = RABBITMQ_URL
TARA_EVENT_EXCHANGE = os.getenv("TARA_EVENT_EXCHANGE", "tara.events")
TARA_OUTBOX_MODEL = "adminsvc.OutboxEvent"
TARA_EVENT_QUEUE = "admin.events"

CELERY_BROKER_URL = RABBITMQ_URL or "memory://"
CELERY_TASK_DEFAULT_QUEUE = f"{SERVICE_NAME}.tasks"
CELERY_RESULT_BACKEND = None
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", not bool(RABBITMQ_URL))
CELERY_BEAT_SCHEDULE = {
    "drain-outbox": {"task": "tara_events.publish_outbox", "schedule": 2.0},
    "purge-events": {"task": "tara_events.purge_events", "schedule": 3600.0},
    "poll-service-health": {
        "task": "adminsvc.poll_service_health",
        "schedule": HEALTH_POLL_SECONDS,
    },
    "poll-platform-stats": {
        "task": "adminsvc.poll_platform_stats",
        "schedule": STATS_POLL_SECONDS,
    },
}

CORS_ALLOWED_ORIGINS = env_list("ADMIN_CORS_ORIGINS", "http://localhost:5173")
CORS_ALLOW_CREDENTIALS = True
SECURE_CONTENT_TYPE_NOSNIFF = True

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
