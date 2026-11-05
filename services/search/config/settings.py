"""Search service settings.

Source of truth is a Postgres `search_document` table (also the fallback when
OpenSearch is unavailable). OpenSearch is an optional accelerator (ADR-004).
"""

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


SECRET_KEY = os.getenv("SEARCH_SECRET_KEY", "dev-only-insecure-secret-change-me")
DEBUG = env_bool("SEARCH_DEBUG", False)
ALLOWED_HOSTS = env_list("SEARCH_ALLOWED_HOSTS", "localhost,127.0.0.1")
SERVICE_NAME = "search"

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.postgres",
    "rest_framework",
    "drf_spectacular",
    "corsheaders",
    "django_prometheus",
    "searchsvc",
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
        "NAME": os.getenv("SEARCH_DB_NAME", "search_db"),
        "USER": os.getenv("SEARCH_DB_USER", "search"),
        "PASSWORD": os.getenv("SEARCH_DB_PASSWORD", "search-dev-pass"),
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
        "LOCATION": os.getenv("REDIS_URL", "redis://127.0.0.1:6379/10"),
    }
}

REST_FRAMEWORK = {
    **api_throttling(),
    "DEFAULT_AUTHENTICATION_CLASSES": ["tara_common.auth.JWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "tara_common.pagination.CursorPagination",
    "PAGE_SIZE": 20,
    "EXCEPTION_HANDLER": "tara_common.exceptions.tara_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Tara Search API",
    "DESCRIPTION": (
        "Unified search: people, posts, photos, pages, groups, listings, events and"
        " hashtags; suggestions, recent searches and trending hashtags."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": "/api/v1",
}

TARA_JWKS_URL = os.getenv("TARA_JWKS_URL", "http://identity:8000/.well-known/jwks.json")
TARA_JWT_PUBLIC_KEY = os.getenv("TARA_JWT_PUBLIC_KEY", "")
TARA_JWT_ISSUER = os.getenv("JWT_ISSUER", "tara-identity")
TARA_JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "tara")
TARA_INTERNAL_JWT_SECRET = os.getenv("INTERNAL_JWT_SECRET", "dev-only-internal-secret-change-me")

# OpenSearch accelerator (optional). Postgres remains the fallback + source of truth.
SEARCH_USE_OPENSEARCH = env_bool("SEARCH_USE_OPENSEARCH", False)
OPENSEARCH_URL = os.getenv("OPENSEARCH_URL", "http://opensearch:9200")
OPENSEARCH_INDEX = os.getenv("OPENSEARCH_INDEX", "tara")

# Internal reads (short-lived HS256 tokens, timeout, circuit breaker):
# graph for the viewer's relationships on people and page results, the owners'
# export endpoints for the backfill, and post for an event's current state.
GRAPH_INTERNAL_URL = os.getenv("GRAPH_INTERNAL_URL", "http://graph:8000")
POST_INTERNAL_URL = os.getenv("POST_INTERNAL_URL", "http://post:8000")
PROFILE_INTERNAL_URL = os.getenv("PROFILE_INTERNAL_URL", "http://profile:8000")
MARKETPLACE_INTERNAL_URL = os.getenv("MARKETPLACE_INTERNAL_URL", "http://marketplace:8000")
# The standing account restrictions export (``search_backfill_restrictions``).
MODERATION_INTERNAL_URL = os.getenv("MODERATION_INTERNAL_URL", "http://moderation:8000")
SEARCH_INTERNAL_TIMEOUT = float(os.getenv("SEARCH_INTERNAL_TIMEOUT", "1.5"))

# Trending hashtags honesty rules (Tara Intelligence 4b.20-B3, 08 §3 and §9.4).
# Not intel ranking: plain settings, no env vars. A tag needs this many distinct
# authors; a post count is shown only as the largest floor it reaches (never a
# number below the first floor); answers are cached per window.
SEARCH_TRENDING_MIN_AUTHORS = 3
SEARCH_TRENDING_COUNT_FLOORS = (20, 50, 100, 500, 1000, 5000, 10000)
SEARCH_TRENDING_CACHE_S = 300

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "")
TARA_EVENT_PUBLISHER = "null"  # Search is read-only-derived; it does not publish events
TARA_EVENT_BROKER_URL = RABBITMQ_URL
TARA_EVENT_EXCHANGE = os.getenv("TARA_EVENT_EXCHANGE", "tara.events")
TARA_EVENT_QUEUE = "search.events"

CELERY_BROKER_URL = RABBITMQ_URL or "memory://"
CELERY_TASK_DEFAULT_QUEUE = f"{SERVICE_NAME}.tasks"
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", not bool(RABBITMQ_URL))

CORS_ALLOWED_ORIGINS = env_list("SEARCH_CORS_ORIGINS", "http://localhost:5173")
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
