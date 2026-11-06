"""Media service settings."""

from __future__ import annotations

import hashlib
import os
import secrets
from pathlib import Path

from kombu import Queue

from tara_common.rate_limits import api_throttling
from tara_observability.logging import build_logging_config

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in ("1", "true", "yes", "on")


def env_list(name: str, default: str = "") -> list[str]:
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


# ``transcoder``: the media-transcoder container (roadmap 5.2). It runs untrusted
# files through ffmpeg, so it gets a minimal environment: its database, the
# broker and a storage user scoped to ``videos/``. Secrets it never needs are
# random per process instead of shared defaults.
MEDIA_ROLE = os.getenv("MEDIA_ROLE", "")
_TRANSCODER = MEDIA_ROLE == "transcoder"

SECRET_KEY = os.getenv("MEDIA_SECRET_KEY") or (
    secrets.token_urlsafe(48) if _TRANSCODER else "dev-only-insecure-secret-change-me"
)
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
if _TRANSCODER and not os.getenv("REDIS_URL"):
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

_throttling = api_throttling()
REST_FRAMEWORK = {
    **_throttling,
    # The batch lookups (views.ResolveView, PlaybackResolveView) use their own
    # scope: each call stands for up to 100 media.
    "DEFAULT_THROTTLE_RATES": {
        **_throttling["DEFAULT_THROTTLE_RATES"],
        "media_resolve": "240/min",
    },
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
TARA_INTERNAL_JWT_SECRET = os.getenv("INTERNAL_JWT_SECRET") or (
    secrets.token_urlsafe(48) if _TRANSCODER else "dev-only-internal-secret-change-me"
)

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

# ---- Video pipeline (roadmap 5.2 / 5.3) ---------------------------------------
# Per-purpose caps: the most a video of that purpose may weigh and last.
MEDIA_VIDEO_PURPOSES = {
    "post": {
        "max_bytes": int(os.getenv("MEDIA_VIDEO_MAX_BYTES_POST", str(200 * 1024 * 1024))),
        "max_seconds": int(os.getenv("MEDIA_VIDEO_MAX_SECONDS_POST", "600")),
    },
}
# Per account, over the last 24 hours: transcoded videos signed, and their bytes.
MEDIA_VIDEO_DAILY_UPLOADS = int(os.getenv("MEDIA_VIDEO_DAILY_UPLOADS", "20"))
MEDIA_VIDEO_DAILY_BYTES = int(os.getenv("MEDIA_VIDEO_DAILY_BYTES", str(2 * 1024**3)))
# The HLS ladder (short side, px) is cut at this height and never upscales.
MEDIA_VIDEO_MAX_HEIGHT = int(os.getenv("MEDIA_VIDEO_MAX_HEIGHT", "720"))
MEDIA_VIDEO_MAX_FPS = int(os.getenv("MEDIA_VIDEO_MAX_FPS", "30"))
# Sources bigger than this many pixels per frame are refused (``dimensions_too_large``).
MEDIA_VIDEO_MAX_PIXELS = int(os.getenv("MEDIA_VIDEO_MAX_PIXELS", str(3840 * 2160)))
# HDR sources: ``tonemap`` to SDR (needs ffmpeg's zscale) or ``reject`` (``hdr_unsupported``).
MEDIA_VIDEO_HDR_MODE = os.getenv("MEDIA_VIDEO_HDR_MODE", "tonemap")
MEDIA_VIDEO_MP4_FALLBACK = env_bool("MEDIA_VIDEO_MP4_FALLBACK", False)
MEDIA_KEEP_VIDEO_ORIGINALS = env_bool("MEDIA_KEEP_VIDEO_ORIGINALS", False)
# Each ffmpeg run (one chain step) is killed after this many seconds (``timeout``).
MEDIA_TRANSCODE_STEP_TIMEOUT = int(os.getenv("MEDIA_TRANSCODE_STEP_TIMEOUT", "1200"))
# Address-space limit for ffmpeg, in MB (0: none; the container's mem_limit still applies).
MEDIA_FFMPEG_MAX_MEMORY_MB = int(os.getenv("MEDIA_FFMPEG_MAX_MEMORY_MB", "1200"))
MEDIA_FFMPEG_THREADS = int(os.getenv("MEDIA_FFMPEG_THREADS", "2"))
# One private mkdtemp per step under this root, removed in ``finally``.
MEDIA_TRANSCODE_SCRATCH_DIR = os.getenv("MEDIA_TRANSCODE_SCRATCH_DIR", "/tmp/tara-transcode")  # noqa: S108
MEDIA_TRANSCODE_MAX_ATTEMPTS = 3
# Playback (5.3): playlist tokens signed with a media-only secret, segment URLs
# presigned per time bucket. A removed video stops within the window.
# Optional: derived from MEDIA_SECRET_KEY when unset (the transcoder never has it).
MEDIA_PLAYBACK_SECRET = (
    os.getenv("MEDIA_PLAYBACK_SECRET")
    or hashlib.sha256(f"tara-media-playback:{SECRET_KEY}".encode()).hexdigest()
)
MEDIA_PLAYBACK_TOKEN_TTL = int(os.getenv("MEDIA_PLAYBACK_TOKEN_TTL", "3600"))
MEDIA_HLS_URL_WINDOW_SECONDS = int(os.getenv("MEDIA_HLS_URL_WINDOW_SECONDS", "300"))
MEDIA_PLAYBACK_ACCESS_CACHE_SECONDS = int(os.getenv("MEDIA_PLAYBACK_ACCESS_CACHE_SECONDS", "30"))
# Display GETs (images, thumbnails, display sizes, posters; Tara Intelligence WP
# 4c.5-B3) are signed per bucket of this many seconds: one URL per object per bucket,
# so browsers cache them across reloads (Cache-Control private, max-age=<bucket>).
# Each URL is valid to the bucket's end plus 55 minutes.
MEDIA_DISPLAY_URL_BUCKET_SECONDS = int(os.getenv("MEDIA_DISPLAY_URL_BUCKET_SECONDS", "3600"))

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
# Transcoding runs on its own queue, consumed only by media-transcoder
# (concurrency 1). Its steps ack late, so the per-queue consumer timeout is
# raised above RabbitMQ's 30-minute default (each step is also time-limited).
MEDIA_TRANSCODE_QUEUE = f"{SERVICE_NAME}.transcode"
MEDIA_TRANSCODE_CONSUMER_TIMEOUT_MS = int(
    os.getenv("MEDIA_TRANSCODE_CONSUMER_TIMEOUT_MS", str(2 * 3600 * 1000))
)
CELERY_TASK_QUEUES = (
    Queue(CELERY_TASK_DEFAULT_QUEUE),
    Queue(
        MEDIA_TRANSCODE_QUEUE,
        queue_arguments={"x-consumer-timeout": MEDIA_TRANSCODE_CONSUMER_TIMEOUT_MS},
    ),
)
CELERY_TASK_ROUTES = {"media.video.*": {"queue": MEDIA_TRANSCODE_QUEUE}}
CELERY_RESULT_BACKEND = None
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", not bool(RABBITMQ_URL))
CELERY_BEAT_SCHEDULE = {
    "drain-outbox": {"task": "tara_events.publish_outbox", "schedule": 2.0},
    "purge-events": {"task": "tara_events.purge_events", "schedule": 3600.0},
    "expire-stale-uploads": {"task": "media.expire_stale_uploads", "schedule": 900.0},
    "requeue-stalled-videos": {"task": "media.requeue_stalled_videos", "schedule": 900.0},
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
