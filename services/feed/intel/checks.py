"""Deploy checks for Tara Intelligence (``manage.py check --deploy`` at boot in production)."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.checks import Error, Tags
from django.core.checks import Warning as CheckWarning
from django.core.checks import register as _register

MIN_SECRET_LENGTH = 32
_PLACEHOLDER_MARKERS = ("replace_me", "change-me", "changeme", "dev-only")


def _production() -> bool:
    return settings.TARA_ENV == "production"


def serve_token_secret(app_configs: Any = None, **kwargs: Any) -> list:
    """Serve tokens attribute telemetry; a shared or guessable key would let anyone forge it."""
    secret = settings.INTEL_SERVE_TOKEN_SECRET
    if secret and secret in (settings.SECRET_KEY, settings.TARA_INTERNAL_JWT_SECRET):
        return [
            Error(
                "INTEL_SERVE_TOKEN_SECRET must not reuse FEED_SECRET_KEY or INTERNAL_JWT_SECRET.",
                hint="Generate one with scripts/gen-dokploy-env.sh (openssl rand -hex 32).",
                id="intel.E001",
            )
        ]
    if not _production():
        if not secret:
            return [
                CheckWarning(
                    "INTEL_SERVE_TOKEN_SECRET is not set; serve tokens use a development key "
                    "derived from FEED_SECRET_KEY.",
                    id="intel.W001",
                )
            ]
        return []
    lowered = (secret or "").lower()
    if (
        not secret
        or len(secret) < MIN_SECRET_LENGTH
        or any(m in lowered for m in _PLACEHOLDER_MARKERS)
    ):
        return [
            Error(
                f"INTEL_SERVE_TOKEN_SECRET is missing, a placeholder or shorter than "
                f"{MIN_SECRET_LENGTH} characters.",
                id="intel.E002",
            )
        ]
    return []


def synthetic_in_production(app_configs: Any = None, **kwargs: Any) -> list:
    """Synthetic behaviour never reaches production analytics or ranking."""
    if not _production():
        return []
    errors = []
    if settings.INTEL_ACCEPT_SYNTHETIC:
        errors.append(Error("INTEL_ACCEPT_SYNTHETIC must be false in production.", id="intel.E003"))
    if settings.INTEL_SYNTHETIC_IN_RANKING:
        errors.append(
            Error("INTEL_SYNTHETIC_IN_RANKING must be false in production.", id="intel.E004")
        )
    return errors


def register() -> None:
    _register(Tags.security)(serve_token_secret)
    _register(Tags.security, deploy=True)(synthetic_in_production)
