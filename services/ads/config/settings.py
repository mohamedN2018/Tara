"""Advertisement service settings."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from tara_common.rate_limits import api_throttling
from tara_observability.logging import build_logging_config

_throttling = api_throttling()

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in ("1", "true", "yes", "on")


def env_list(name: str, default: str = "") -> list[str]:
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


def ads_serving_enabled(environ: Mapping[str, str]) -> bool:
    """An explicit ADS_SERVING_ENABLED wins; unset or empty means on, except in production."""
    explicit = environ.get("ADS_SERVING_ENABLED", "").strip().lower()
    if explicit:
        return explicit in ("1", "true", "yes", "on")
    return environ.get("TARA_ENV", "development").strip().lower() != "production"


TARA_ENV = os.getenv("TARA_ENV", "development").strip().lower()

SECRET_KEY = os.getenv("ADS_SECRET_KEY", "dev-only-insecure-secret-change-me")
DEBUG = env_bool("ADS_DEBUG", False)
ALLOWED_HOSTS = env_list("ADS_ALLOWED_HOSTS", "localhost,127.0.0.1")
SERVICE_NAME = "ads"

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "rest_framework",
    "drf_spectacular",
    "corsheaders",
    "django_prometheus",
    "ads",
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
        "NAME": os.getenv("ADS_DB_NAME", "ads_db"),
        "USER": os.getenv("ADS_DB_USER", "ads"),
        "PASSWORD": os.getenv("ADS_DB_PASSWORD", "ads-dev-pass"),
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
        "LOCATION": os.getenv("REDIS_URL", "redis://127.0.0.1:6379/13"),
    }
}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["tara_common.auth.JWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "tara_common.pagination.CursorPagination",
    "PAGE_SIZE": 20,
    "EXCEPTION_HANDLER": "tara_common.exceptions.tara_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    # The platform read/write limits for every endpoint; the events endpoint
    # uses its own `ad_events` scope instead (views.EventsView).
    **_throttling,
    "DEFAULT_THROTTLE_RATES": {**_throttling["DEFAULT_THROTTLE_RATES"], "ad_events": "600/min"},
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Tara Advertisement API",
    "DESCRIPTION": "Advertiser accounts, campaigns, creatives, review, serving, events.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": "/api/v1",
}

TARA_JWKS_URL = os.getenv("TARA_JWKS_URL", "http://identity:8000/.well-known/jwks.json")
TARA_JWT_PUBLIC_KEY = os.getenv("TARA_JWT_PUBLIC_KEY", "")
TARA_JWT_ISSUER = os.getenv("JWT_ISSUER", "tara-identity")
TARA_JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "tara")
TARA_INTERNAL_JWT_SECRET = os.getenv("INTERNAL_JWT_SECRET", "dev-only-internal-secret-change-me")

# Creative images are checked with media's internal batch lookup (fail closed).
MEDIA_INTERNAL_URL = os.getenv("MEDIA_INTERNAL_URL", "http://media:8000")
MEDIA_CALL_TIMEOUT = float(os.getenv("MEDIA_CALL_TIMEOUT", "2.0"))

# Until the Moderation/ad-review team is staffed, dev auto-approves creatives.
ADS_AUTO_APPROVE = env_bool("ADS_AUTO_APPROVE", False)
ADS_DEFAULT_FREQUENCY_CAP = int(os.getenv("ADS_DEFAULT_FREQUENCY_CAP", "5"))  # per viewer/day

# No campaign may serve in production before funding is verified (roadmap 1.0b,
# 6.3): while this is off the feed slot is always empty and no serve token is
# minted. The deploy check refuses to boot production with it on.
ADS_SERVING_ENABLED = ads_serving_enabled(os.environ)

# Signs the serve tokens browsers hold. Only ads has it, so no other service can
# mint billable impressions or clicks (roadmap 1.0e). Required in production; an
# empty value in development falls back to a key derived from SECRET_KEY.
ADS_SERVE_TOKEN_SECRET = os.getenv("ADS_SERVE_TOKEN_SECRET", "")

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "")
TARA_EVENT_PUBLISHER = "rabbitmq" if RABBITMQ_URL else "null"
TARA_EVENT_BROKER_URL = RABBITMQ_URL
TARA_EVENT_EXCHANGE = os.getenv("TARA_EVENT_EXCHANGE", "tara.events")
TARA_OUTBOX_MODEL = "ads.OutboxEvent"
TARA_EVENT_QUEUE = "ads.events"

CELERY_BROKER_URL = RABBITMQ_URL or "memory://"
CELERY_TASK_DEFAULT_QUEUE = f"{SERVICE_NAME}.tasks"
CELERY_RESULT_BACKEND = None
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", not bool(RABBITMQ_URL))
CELERY_BEAT_SCHEDULE = {
    "drain-outbox": {"task": "tara_events.publish_outbox", "schedule": 2.0},
    "purge-events": {"task": "tara_events.purge_events", "schedule": 3600.0},
}

CORS_ALLOWED_ORIGINS = env_list("ADS_CORS_ORIGINS", "http://localhost:5173")
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
