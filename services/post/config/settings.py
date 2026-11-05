"""Post service settings."""

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


SECRET_KEY = os.getenv("POST_SECRET_KEY", "dev-only-insecure-secret-change-me")
DEBUG = env_bool("POST_DEBUG", False)
ALLOWED_HOSTS = env_list("POST_ALLOWED_HOSTS", "localhost,127.0.0.1")
SERVICE_NAME = "post"

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "rest_framework",
    "drf_spectacular",
    "corsheaders",
    "django_prometheus",
    "posts",
    "gatherings",
    "stories",
    "reels",
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
        "NAME": os.getenv("POST_DB_NAME", "post_db"),
        "USER": os.getenv("POST_DB_USER", "post"),
        "PASSWORD": os.getenv("POST_DB_PASSWORD", "post-dev-pass"),
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
        "LOCATION": os.getenv("REDIS_URL", "redis://127.0.0.1:6379/4"),
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
# Post and comment reports per account (each can open a moderation case).
POST_REPORT_RATE = os.getenv("POST_REPORT_RATE", "20/hour")
# group.post.published / group.announcement.pinned (1.11): two-release rollout
# (roadmap 3.3); deploy notification first, then turn this on.
POST_EMIT_GROUP_EVENTS = env_bool("POST_EMIT_GROUP_EVENTS", True)
# post.tagged (2C): two-release rollout; notification's post.tag consumer ships first.
POST_EMIT_TAG_EVENTS = env_bool("POST_EMIT_TAG_EVENTS", True)
# story.reacted / story.deleted / story.reported (1.9): two-release rollout; the
# notification and moderation consumers ship first.
POST_EMIT_STORY_EVENTS = env_bool("POST_EMIT_STORY_EVENTS", True)
# post.hidden / post.unhidden (account deactivation, plan 08 3C): two-release
# rollout; feed's and search's consumers ship first. Off: deactivation emits
# post.deleted, which feed cannot undo on reactivation.
POST_EMIT_HIDE_EVENTS = env_bool("POST_EMIT_HIDE_EVENTS", True)
# post.saved / post.unsaved (Tara Intelligence WP 2.6, owner decision 6): ids
# only, consumed by feed only. Two-release rollout: feed's consumer ships first;
# off turns the emission off without touching saves themselves.
POST_EMIT_SAVE_EVENTS = env_bool("POST_EMIT_SAVE_EVENTS", True)

SPECTACULAR_SETTINGS = {
    "TITLE": "Tara Post API",
    "DESCRIPTION": "Posts, comments, reactions, shares, saved content.",
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
PROFILE_INTERNAL_URL = os.getenv("PROFILE_INTERNAL_URL", "http://profile:8000")
GRAPH_CALL_TIMEOUT = float(os.getenv("GRAPH_CALL_TIMEOUT", "2.0"))
# Attachment checks and media restriction (fail closed: 503 when media is down).
MEDIA_INTERNAL_URL = os.getenv("MEDIA_INTERNAL_URL", "http://media:8000")
MEDIA_CALL_TIMEOUT = float(os.getenv("MEDIA_CALL_TIMEOUT", "2.0"))

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "")
TARA_EVENT_PUBLISHER = "rabbitmq" if RABBITMQ_URL else "null"
TARA_EVENT_BROKER_URL = RABBITMQ_URL
TARA_EVENT_EXCHANGE = os.getenv("TARA_EVENT_EXCHANGE", "tara.events")
TARA_OUTBOX_MODEL = "posts.OutboxEvent"
TARA_EVENT_QUEUE = "post.events"

CELERY_BROKER_URL = RABBITMQ_URL or "memory://"
CELERY_TASK_DEFAULT_QUEUE = f"{SERVICE_NAME}.tasks"
CELERY_RESULT_BACKEND = None
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", not bool(RABBITMQ_URL))
CELERY_BEAT_SCHEDULE = {
    "drain-outbox": {"task": "tara_events.publish_outbox", "schedule": 2.0},
    "purge-events": {"task": "tara_events.purge_events", "schedule": 3600.0},
    # Event reminders (about 24 h and 1 h before; once each) and marking ended events.
    "gatherings-tick": {"task": "gatherings.tick", "schedule": 300.0},
    # Scheduled posts whose time has come (2C); SKIP LOCKED, so once per post.
    "posts-publish-scheduled": {"task": "posts.publish_scheduled", "schedule": 60.0},
    # Reels whose video was deleted, failed or left unbound in media (5.5).
    "reels-reconcile": {"task": "reels.reconcile", "schedule": 900.0},
}

CORS_ALLOWED_ORIGINS = env_list("POST_CORS_ORIGINS", "http://localhost:5173")
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
