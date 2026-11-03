"""Media service settings."""

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


SECRET_KEY = os.getenv("MEDIA_SECRET_KEY", "dev-only-insecure-secret-change-me")
DEBUG = env_bool("MEDIA_DEBUG", False)
ALLOWED_HOSTS = env_list("MEDIA_ALLOWED_HOSTS", "localhost,127.0.0.1")
SERVICE_NAME = "media"

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "rest_framework",
    "drf_spectacular",
    "corsheaders",
    "django_prometheus",
    "media_app",
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
        "NAME": os.getenv("MEDIA_DB_NAME", "media_db"),
        "USER": os.getenv("MEDIA_DB_USER", "media"),
        "PASSWORD": os.getenv("MEDIA_DB_PASSWORD", "media-dev-pass"),
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
        "LOCATION": os.getenv("REDIS_URL", "redis://127.0.0.1:6379/3"),
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
    "TITLE": "Tara Media API",
    "DESCRIPTION": "Signed uploads/downloads, media metadata, async processing.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": "/api/v1",
}

TARA_JWKS_URL = os.getenv("TARA_JWKS_URL", "http://identity:8000/.well-known/jwks.json")
TARA_JWT_PUBLIC_KEY = os.getenv("TARA_JWT_PUBLIC_KEY", "")
TARA_JWT_ISSUER = os.getenv("JWT_ISSUER", "tara-identity")
TARA_JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "tara")
TARA_INTERNAL_JWT_SECRET = os.getenv("INTERNAL_JWT_SECRET", "dev-only-internal-secret-change-me")

# Object storage
STORAGE_BACKEND = os.getenv("TARA_STORAGE_BACKEND", "s3")  # "s3" | "fake" (tests)
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL", "http://minio:9000")
S3_PUBLIC_BASE = os.getenv("S3_PUBLIC_BASE", "http://localhost:9000")
S3_BUCKET = os.getenv("S3_BUCKET", "tara-media")
S3_REGION = os.getenv("S3_REGION", "us-east-1")
S3_PUBLIC_ENDPOINT_URL = os.getenv("S3_PUBLIC_ENDPOINT_URL", "")
S3_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY_ID") or os.getenv("MINIO_ROOT_USER", "tara")
S3_SECRET_KEY = os.getenv("AWS_SECRET_ACCESS_KEY") or os.getenv(
    "MINIO_ROOT_PASSWORD", "tara-dev-pass"
)
SIGNED_URL_TTL = int(os.getenv("SIGNED_URL_TTL", "900"))
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(200 * 1024 * 1024)))  # 200 MB
# Image limits, checked from the header before decoding (the worker has 256 MB).
# One frame at most 50 MP (a 50 MP phone photo is 8160x6120); animations at most
# MEDIA_MAX_FRAMES frames and MEDIA_MAX_ANIMATION_PIXELS pixels over all frames.
MEDIA_MAX_IMAGE_PIXELS = int(os.getenv("MEDIA_MAX_IMAGE_PIXELS", "50000000"))
MEDIA_MAX_FRAMES = int(os.getenv("MEDIA_MAX_FRAMES", "1000"))
MEDIA_MAX_ANIMATION_PIXELS = int(os.getenv("MEDIA_MAX_ANIMATION_PIXELS", "100000000"))

# Restricted (non-public post) media ask post who may see them; fails closed.
POST_INTERNAL_URL = os.getenv("POST_INTERNAL_URL", "http://post:8000")
POST_CALL_TIMEOUT = float(os.getenv("POST_CALL_TIMEOUT", "2.0"))

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "")
TARA_EVENT_PUBLISHER = "rabbitmq" if RABBITMQ_URL else "null"
TARA_EVENT_BROKER_URL = RABBITMQ_URL
TARA_EVENT_EXCHANGE = os.getenv("TARA_EVENT_EXCHANGE", "tara.events")
TARA_OUTBOX_MODEL = "media_app.OutboxEvent"
TARA_EVENT_QUEUE = "media.events"

CELERY_BROKER_URL = RABBITMQ_URL or "memory://"
CELERY_TASK_DEFAULT_QUEUE = f"{SERVICE_NAME}.tasks"
CELERY_RESULT_BACKEND = None
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", not bool(RABBITMQ_URL))
CELERY_BEAT_SCHEDULE = {
    "drain-outbox": {"task": "tara_events.publish_outbox", "schedule": 2.0},
    "purge-events": {"task": "tara_events.purge_events", "schedule": 3600.0},
    "expire-stale-uploads": {"task": "media.expire_stale_uploads", "schedule": 900.0},
}

CORS_ALLOWED_ORIGINS = env_list("MEDIA_CORS_ORIGINS", "http://localhost:5173")
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
