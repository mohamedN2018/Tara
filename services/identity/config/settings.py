"""Identity service settings.

Twelve-factor: every environment-specific value comes from the environment.
No secrets are hard-coded. See .env.example at the repo root.
"""

from __future__ import annotations

import os
from pathlib import Path

from identity.keys import load_keys

from tara_common.rate_limits import NUM_PROXIES
from tara_observability.logging import build_logging_config

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in ("1", "true", "yes", "on")


def env_list(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


# ---- Core -------------------------------------------------------------------
SECRET_KEY = os.getenv("IDENTITY_SECRET_KEY", "dev-only-insecure-secret-change-me")
DEBUG = env_bool("IDENTITY_DEBUG", False)
ALLOWED_HOSTS = env_list("IDENTITY_ALLOWED_HOSTS", "localhost,127.0.0.1")
SERVICE_NAME = "identity"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third-party
    "rest_framework",
    "drf_spectacular",
    "corsheaders",
    "django_prometheus",
    # local
    "identity",
]

MIDDLEWARE = [
    "django_prometheus.middleware.PrometheusBeforeMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "tara_common.middleware.RequestIDMiddleware",
    "django_prometheus.middleware.PrometheusAfterMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

AUTH_USER_MODEL = "identity.Account"

# ---- Database (per-service) -------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("IDENTITY_DB_NAME", "identity_db"),
        "USER": os.getenv("IDENTITY_DB_USER", "identity"),
        "PASSWORD": os.getenv("IDENTITY_DB_PASSWORD", "identity-dev-pass"),
        "HOST": os.getenv("POSTGRES_HOST", "127.0.0.1"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---- Cache (Redis) ----------------------------------------------------------
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"),
    }
}

# ---- Password hashing (Argon2id first) --------------------------------------
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
]
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
]

# ---- DRF --------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "tara_common.auth.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "tara_common.pagination.CursorPagination",
    "PAGE_SIZE": 20,
    "EXCEPTION_HANDLER": "tara_common.exceptions.tara_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "NUM_PROXIES": NUM_PROXIES,
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.ScopedRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {
        "auth_register": os.getenv("AUTH_REGISTER_RATE", "10/hour"),
        "auth_login": os.getenv("AUTH_LOGIN_RATE", "20/min"),
        "auth_password": os.getenv("AUTH_PASSWORD_RATE", "5/hour"),
        "auth_refresh": "60/min",
    },
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Tara Identity API",
    "DESCRIPTION": "Authentication, sessions, and account security for the Tara platform.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": "/api/v1",
}

# ---- JWT keys & token policy (ADR-005) --------------------------------------
JWT_KEY_DIR = Path(os.getenv("IDENTITY_JWT_KEY_DIR", str(BASE_DIR / ".keys")))
JWT_PRIVATE_KEY, JWT_PUBLIC_KEY = load_keys(
    private_env=os.getenv("IDENTITY_JWT_PRIVATE_KEY", ""),
    public_env=os.getenv("IDENTITY_JWT_PUBLIC_KEY", ""),
    key_dir=JWT_KEY_DIR,
)
JWT_KEY_ID = os.getenv("IDENTITY_JWT_KEY_ID", "dev-key-1")
JWT_ISSUER = os.getenv("JWT_ISSUER", "tara-identity")
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "tara")
ACCESS_TOKEN_TTL_SECONDS = int(os.getenv("ACCESS_TOKEN_TTL_SECONDS", "900"))
REFRESH_TOKEN_TTL_SECONDS = int(os.getenv("REFRESH_TOKEN_TTL_SECONDS", "2592000"))

# Consumed by tara_common.auth.JWTAuthentication to verify our own tokens locally.
TARA_JWT_PUBLIC_KEY = JWT_PUBLIC_KEY
TARA_JWT_ISSUER = JWT_ISSUER
TARA_JWT_AUDIENCE = JWT_AUDIENCE
TARA_INTERNAL_JWT_SECRET = os.getenv("INTERNAL_JWT_SECRET", "dev-only-internal-secret-change-me")
# Held only by identity and admin (roadmap 1.0d). The /internal/v1/ role and
# staff endpoints verify admin's tokens with it and refuse INTERNAL_JWT_SECRET.
# The deploy check rejects a missing, short or development value.
ADMIN_IDENTITY_SECRET = os.getenv(
    "ADMIN_IDENTITY_SECRET", "dev-only-admin-identity-secret-change-me"
)

# ---- Events / outbox (ADR-003) ----------------------------------------------
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "")
TARA_EVENT_PUBLISHER = "rabbitmq" if RABBITMQ_URL else "null"
TARA_EVENT_BROKER_URL = RABBITMQ_URL
TARA_EVENT_EXCHANGE = os.getenv("TARA_EVENT_EXCHANGE", "tara.events")
TARA_OUTBOX_MODEL = "identity.OutboxEvent"

# ---- Celery -----------------------------------------------------------------
CELERY_BROKER_URL = RABBITMQ_URL or "memory://"
CELERY_TASK_DEFAULT_QUEUE = f"{SERVICE_NAME}.tasks"
CELERY_RESULT_BACKEND = None
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", not bool(RABBITMQ_URL))
CELERY_BEAT_SCHEDULE = {
    "purge-events": {"task": "tara_events.purge_events", "schedule": 3600.0},
    "drain-outbox": {
        "task": "tara_events.publish_outbox",
        "schedule": 2.0,  # seconds
    },
}

# ---- Email (Mailpit in dev) -------------------------------------------------
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.getenv("EMAIL_HOST", "127.0.0.1")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "1025"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", False)
EMAIL_TIMEOUT = 15
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "no-reply@tara.local")
FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:5173")

# ---- CORS / security --------------------------------------------------------
CORS_ALLOWED_ORIGINS = env_list("IDENTITY_CORS_ORIGINS", "http://localhost:5173")
CORS_ALLOW_CREDENTIALS = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31_536_000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# ---- i18n / static ----------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = os.getenv("TZ", "UTC")
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# ---- Logging ----------------------------------------------------------------
LOGGING = build_logging_config(
    SERVICE_NAME,
    level=os.getenv("LOG_LEVEL", "INFO"),
    fmt=os.getenv("LOG_FORMAT", "json" if not DEBUG else "console"),
)
