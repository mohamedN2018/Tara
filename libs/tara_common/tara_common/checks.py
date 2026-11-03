"""Production-safety deploy checks for every Tara service.

The brief forbids hard-coded secrets and toy configuration shipping to
production. These checks turn that rule into an enforced gate: when a service
runs with ``DEBUG=False`` (i.e. production), it refuses to pass
``manage.py check --deploy`` if any secret is still a development default,
``ALLOWED_HOSTS`` is wide-open/empty, or CORS allows all origins with
credentials.

The detection logic (:func:`evaluate_production_safety`) is a pure function with
**no Django import at module load**, so it is unit-testable anywhere (and so this
module can be imported by tooling that has no Django configured). The Django
wiring lives in :func:`register_checks`, which a service calls from its
``AppConfig.ready()``.
"""

from __future__ import annotations

from typing import Any

# Substrings that mark a development default or an unfilled placeholder. If any
# survive into a DEBUG=False process, the deploy is misconfigured. Covers the
# dev defaults shipped in settings/.env.example AND the "REPLACE_ME" markers used
# in the production env / Secret templates.
_DEV_MARKERS = (
    "dev-only",
    "change-me",
    "changeme",
    "insecure",
    "dev-pass",
    "dev-secret",
    "-dev-",
    "replace_me",
    "replace-me",
    "replace_from",
)

# (id, level, message). level is "error" (blocks deploy) or "warning".
Finding = tuple[str, str, str]

# Caller-specific secrets (roadmap 1.0d): each is held only by one privileged
# endpoint and its named caller, never by every service. A service is checked
# for one only when its settings declare it (identity and admin declare
# ADMIN_IDENTITY_SECRET; post, chat and the rest do not).
_CALLER_SECRET_SETTINGS = ("ADMIN_IDENTITY_SECRET",)
# RFC 7518 section 3.2: an HS256 key needs at least 256 bits.
_MIN_CALLER_SECRET_LENGTH = 32


def _looks_like_dev_secret(value: Any) -> bool:
    text = str(value or "").lower()
    return any(marker in text for marker in _DEV_MARKERS)


def evaluate_production_safety(settings_obj: Any) -> list[Finding]:
    """Return production-safety findings for a settings-like object.

    Only enforced when ``DEBUG`` is false; in development it returns nothing so
    local workflows are never blocked.
    """
    findings: list[Finding] = []

    if getattr(settings_obj, "DEBUG", False):
        return findings

    # --- Secrets must not be development defaults ----------------------------
    if _looks_like_dev_secret(getattr(settings_obj, "SECRET_KEY", "")):
        findings.append(
            (
                "tara.E001",
                "error",
                "SECRET_KEY is a development default; provide a real value from the "
                "environment / secret manager.",
            )
        )

    if _looks_like_dev_secret(getattr(settings_obj, "TARA_INTERNAL_JWT_SECRET", "")):
        findings.append(
            (
                "tara.E002",
                "error",
                "TARA_INTERNAL_JWT_SECRET is a development default; set INTERNAL_JWT_SECRET.",
            )
        )

    shared_secret = getattr(settings_obj, "TARA_INTERNAL_JWT_SECRET", None)
    for name in _CALLER_SECRET_SETTINGS:
        if not hasattr(settings_obj, name):
            continue
        value = str(getattr(settings_obj, name) or "")
        if len(value) < _MIN_CALLER_SECRET_LENGTH or _looks_like_dev_secret(value):
            findings.append(
                (
                    "tara.E007",
                    "error",
                    f"{name} is missing, shorter than {_MIN_CALLER_SECRET_LENGTH} characters "
                    "or a development default; set it from a secret.",
                )
            )
        elif value == shared_secret:
            findings.append(
                (
                    "tara.E008",
                    "error",
                    f"{name} equals INTERNAL_JWT_SECRET, which every service holds; "
                    "give it its own value.",
                )
            )

    databases = getattr(settings_obj, "DATABASES", {}) or {}
    default_db = databases.get("default", {}) if isinstance(databases, dict) else {}
    if _looks_like_dev_secret(default_db.get("PASSWORD", "")):
        findings.append(
            (
                "tara.E003",
                "error",
                "Database password is a development default; set it from a secret.",
            )
        )

    # --- Host / origin allow-lists must be pinned ----------------------------
    allowed_hosts = list(getattr(settings_obj, "ALLOWED_HOSTS", []) or [])
    if "*" in allowed_hosts:
        findings.append(
            (
                "tara.E004",
                "error",
                "ALLOWED_HOSTS contains '*' in production; pin explicit hostnames.",
            )
        )
    elif not allowed_hosts:
        findings.append(("tara.E005", "error", "ALLOWED_HOSTS is empty in production."))

    if getattr(settings_obj, "CORS_ALLOW_ALL_ORIGINS", False) and getattr(
        settings_obj, "CORS_ALLOW_CREDENTIALS", False
    ):
        findings.append(
            (
                "tara.E006",
                "error",
                "CORS allows all origins with credentials in production; pin CORS_ALLOWED_ORIGINS.",
            )
        )

    # --- Transport / cookie hardening (warnings: gateway may terminate TLS) ---
    if not getattr(settings_obj, "SESSION_COOKIE_SECURE", False):
        findings.append(("tara.W001", "warning", "SESSION_COOKIE_SECURE is off in production."))
    if not getattr(settings_obj, "CSRF_COOKIE_SECURE", False):
        findings.append(("tara.W002", "warning", "CSRF_COOKIE_SECURE is off in production."))

    return findings


def production_safety_check(app_configs: Any = None, **kwargs: Any) -> list[Any]:
    """Django system-check callable. Imports Django lazily."""
    from django.conf import settings
    from django.core.checks import Error
    from django.core.checks import Warning as CheckWarning

    messages: list[Any] = []
    for finding_id, level, text in evaluate_production_safety(settings):
        cls = Error if level == "error" else CheckWarning
        messages.append(cls(text, id=finding_id))
    return messages


def register_checks() -> None:
    """Register the deploy check. Call once from an ``AppConfig.ready()``.

    Idempotent in practice: each service runs in its own process, and Django's
    registry de-duplicates the same callable.
    """
    from django.core.checks import Tags, register

    register(Tags.security, deploy=True)(production_safety_check)
