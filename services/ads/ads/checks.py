"""Ads system checks: the serving switch and the serve-token secret.

The production entrypoint runs ``manage.py check --deploy --fail-level ERROR``,
so an Error here keeps a misconfigured production container from booting while
a Warning only shows in its log.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.checks import Error, Tags, register
from django.core.checks import Warning as CheckWarning

# Campaigns go active on create with no funding check. This turns True only
# when prepaid funding with verification ships (roadmap 6.3).
PAYMENT_VERIFICATION_AVAILABLE = False

MIN_SECRET_LENGTH = 32
_PLACEHOLDER_MARKERS = ("dev-only", "change-me", "changeme", "insecure", "replace", "generated")


def _production() -> bool:
    return settings.TARA_ENV == "production"


@register(Tags.security, deploy=True)
def check_serving_switch(app_configs: Any = None, **kwargs: Any) -> list:
    if not _production() or PAYMENT_VERIFICATION_AVAILABLE:
        return []
    if settings.ADS_SERVING_ENABLED:
        return [
            Error(
                "Ads serving is on in production, but there is no payment verification: "
                "unfunded campaigns would serve.",
                hint="Set ADS_SERVING_ENABLED=false until verified funding ships (roadmap 6.3).",
                id="ads.E001",
            )
        ]
    return [
        CheckWarning(
            "Ads serving is off in production: the feed slot stays empty until "
            "payment verification exists.",
            id="ads.W001",
        )
    ]


@register(Tags.security, deploy=True)
def check_serve_token_secret(app_configs: Any = None, **kwargs: Any) -> list:
    if not _production():
        return []
    secret = settings.ADS_SERVE_TOKEN_SECRET
    if not secret:
        return [
            Error(
                "ADS_SERVE_TOKEN_SECRET is not set; ads cannot sign serve tokens.",
                hint="Generate one with scripts/gen-dokploy-env.sh (openssl rand -hex 32).",
                id="ads.E002",
            )
        ]
    if secret == settings.SECRET_KEY:
        return [Error("ADS_SERVE_TOKEN_SECRET must not reuse ADS_SECRET_KEY.", id="ads.E005")]
    lowered = secret.lower()
    if len(secret) < MIN_SECRET_LENGTH or any(m in lowered for m in _PLACEHOLDER_MARKERS):
        return [
            Error(
                "ADS_SERVE_TOKEN_SECRET is a placeholder or shorter than "
                f"{MIN_SECRET_LENGTH} characters.",
                id="ads.E004",
            )
        ]
    return []


@register(Tags.security)
def check_serve_token_secret_is_ads_only(app_configs: Any = None, **kwargs: Any) -> list:
    """Every environment: the shared secret would let any service forge billable events."""
    secret = settings.ADS_SERVE_TOKEN_SECRET
    if secret and secret == settings.TARA_INTERNAL_JWT_SECRET:
        return [
            Error(
                "ADS_SERVE_TOKEN_SECRET reuses INTERNAL_JWT_SECRET, which every service holds.",
                hint="Give ads its own secret.",
                id="ads.E003",
            )
        ]
    if not secret and not _production():
        return [
            CheckWarning(
                "ADS_SERVE_TOKEN_SECRET is not set; serve tokens use a development key "
                "derived from SECRET_KEY.",
                id="ads.W002",
            )
        ]
    return []
