"""Feed service settings."""

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


SECRET_KEY = os.getenv("FEED_SECRET_KEY", "dev-only-insecure-secret-change-me")
DEBUG = env_bool("FEED_DEBUG", False)
ALLOWED_HOSTS = env_list("FEED_ALLOWED_HOSTS", "localhost,127.0.0.1")
SERVICE_NAME = "feed"

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "rest_framework",
    "drf_spectacular",
    "corsheaders",
    "django_prometheus",
    "feed",
    "intel",
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
        "NAME": os.getenv("FEED_DB_NAME", "feed_db"),
        "USER": os.getenv("FEED_DB_USER", "feed"),
        "PASSWORD": os.getenv("FEED_DB_PASSWORD", "feed-dev-pass"),
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
        "LOCATION": os.getenv("REDIS_URL", "redis://127.0.0.1:6379/5"),
    },
    # Ranking sessions (1.7) live in their own Redis with its own maxmemory and
    # noeviction: when it is full or down, "for you" falls back to latest order.
    "hot": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": os.getenv("REDIS_HOT_URL", "redis://127.0.0.1:6379/6"),
        "KEY_PREFIX": "feed",
        "OPTIONS": {"socket_connect_timeout": 0.5, "socket_timeout": 0.5},
    },
}
FEED_HOT_CACHE = "hot"
FEED_RANK_WINDOW = 500  # newest rows ranked per session; older ones follow in latest order
FEED_RANK_SESSION_TTL = 1800  # seconds

_THROTTLING = api_throttling()
# Telemetry batches (Tara Intelligence, 02 section 12.2): 60 per minute per account.
_THROTTLING["DEFAULT_THROTTLE_RATES"]["intel_signals"] = "60/min"

REST_FRAMEWORK = {
    **_THROTTLING,
    "DEFAULT_AUTHENTICATION_CLASSES": ["tara_common.auth.JWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "tara_common.pagination.CursorPagination",
    "PAGE_SIZE": 20,
    "EXCEPTION_HANDLER": "tara_common.exceptions.tara_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Tara Feed API",
    "DESCRIPTION": "Home feed (fan-out-on-write) with cursor pagination.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": "/api/v1",
}

TARA_JWKS_URL = os.getenv("TARA_JWKS_URL", "http://identity:8000/.well-known/jwks.json")
TARA_JWT_PUBLIC_KEY = os.getenv("TARA_JWT_PUBLIC_KEY", "")
TARA_JWT_ISSUER = os.getenv("JWT_ISSUER", "tara-identity")
TARA_JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "tara")
TARA_INTERNAL_JWT_SECRET = os.getenv("INTERNAL_JWT_SECRET", "dev-only-internal-secret-change-me")

GRAPH_INTERNAL_URL = os.getenv("GRAPH_INTERNAL_URL", "http://graph:8000")
GRAPH_CALL_TIMEOUT = float(os.getenv("GRAPH_CALL_TIMEOUT", "3.0"))
# Tara Intelligence backfills (WP 3.2) read post's and profile's internal exports.
# Both names already exist in every environment's shared env (*common-env).
POST_INTERNAL_URL = os.getenv("POST_INTERNAL_URL", "http://post:8000")
PROFILE_INTERNAL_URL = os.getenv("PROFILE_INTERNAL_URL", "http://profile:8000")
IDENTITY_INTERNAL_URL = os.getenv("IDENTITY_INTERNAL_URL", "http://identity:8000")
MODERATION_INTERNAL_URL = os.getenv("MODERATION_INTERNAL_URL", "http://moderation:8000")

# Ads service for sponsored feed slots (optional; feed degrades to organic).
ADS_INTERNAL_URL = os.getenv("ADS_INTERNAL_URL", "http://ads:8000")
ADS_CALL_TIMEOUT = float(os.getenv("ADS_CALL_TIMEOUT", "1.5"))
FANOUT_MAX_RECIPIENTS = int(os.getenv("FANOUT_MAX_RECIPIENTS", "5000"))  # celebrity guard

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "")
TARA_EVENT_PUBLISHER = "rabbitmq" if RABBITMQ_URL else "null"
TARA_EVENT_BROKER_URL = RABBITMQ_URL
TARA_EVENT_EXCHANGE = os.getenv("TARA_EVENT_EXCHANGE", "tara.events")
TARA_OUTBOX_MODEL = "feed.OutboxEvent"
TARA_EVENT_QUEUE = "feed.events"

CELERY_BROKER_URL = RABBITMQ_URL or "memory://"
CELERY_TASK_DEFAULT_QUEUE = f"{SERVICE_NAME}.tasks"
CELERY_RESULT_BACKEND = None
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", not bool(RABBITMQ_URL))
CELERY_BEAT_SCHEDULE = {
    "drain-outbox": {"task": "tara_events.publish_outbox", "schedule": 2.0},
    "purge-events": {"task": "tara_events.purge_events", "schedule": 3600.0},
    # Tara Intelligence (WP 2.2): partitions 7 days ahead and retention drops
    # (idempotent, so hourly is safe and survives a beat restart), batch dedupe purge.
    "intel-partitions": {"task": "intel.maintain_partitions", "schedule": 3600.0},
    "intel-purge-signal-batches": {"task": "intel.purge_signal_batches", "schedule": 3600.0},
}

# ---- Tara Intelligence (docs/intelligence) ---------------------------------------
TARA_ENV = os.getenv("TARA_ENV", "development").strip().lower()
# Signs the serve tokens that attribute telemetry. Feed only: never FEED_SECRET_KEY
# or INTERNAL_JWT_SECRET. Required in production; dev derives a key and warns.
INTEL_SERVE_TOKEN_SECRET = os.getenv("INTEL_SERVE_TOKEN_SECRET", "")
# Rows from accounts in intel_synthetic_account are stored as synthetic/test only
# when this is true (dev, staging). Production: false, and the table must be empty.
INTEL_ACCEPT_SYNTHETIC = env_bool("INTEL_ACCEPT_SYNTHETIC", False)
# Dev only: let synthetic actors move post_stats / affinity / reaction_state.
INTEL_SYNTHETIC_IN_RANKING = env_bool("INTEL_SYNTHETIC_IN_RANKING", False)
# Raw telemetry partitions are dropped after this many days (owner decision: 30).
INTEL_SIGNAL_RETENTION_DAYS = max(1, int(os.getenv("INTEL_SIGNAL_RETENTION_DAYS", "30")))
# Per-user-item engagement (weekly partitions): 30 days, configurable from 7 to 30.
INTEL_ENGAGEMENT_RETENTION_DAYS = min(
    30, max(7, int(os.getenv("INTEL_ENGAGEMENT_RETENTION_DAYS", "30")))
)

CORS_ALLOWED_ORIGINS = env_list("FEED_CORS_ORIGINS", "http://localhost:5173")
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
