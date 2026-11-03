"""Ad serve tokens.

Serving a creative signs a short-lived token for that viewer, creative and
placement. The events endpoint spends budget only against such a token, so
nobody can burn a competitor's budget by posting a creative id they were never
shown, and each token pays for at most one impression and one click.

The key is ``ADS_SERVE_TOKEN_SECRET``, which only ads holds. It used to be
derived from the shared ``INTERNAL_JWT_SECRET``, so any service could mint
billable events; tokens signed that way are no longer accepted.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
import uuid

import jwt
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured

from tara_common.exceptions import TaraAPIError

AUDIENCE = "ad-serve"
TTL_SECONDS = 30 * 60

logger = logging.getLogger("tara.ads.serve_tokens")
_warned_dev_key = False


def _dev_key() -> str:
    """Development only: derived from ads' own SECRET_KEY, never the internal secret."""
    return hmac.new(
        settings.SECRET_KEY.encode(), b"ads-serve-token-dev-fallback", hashlib.sha256
    ).hexdigest()


def _key() -> str:
    """Fail closed: production never signs without ads' own secret."""
    global _warned_dev_key
    secret = settings.ADS_SERVE_TOKEN_SECRET
    if secret and secret == settings.TARA_INTERNAL_JWT_SECRET:
        raise ImproperlyConfigured(
            "ADS_SERVE_TOKEN_SECRET must not reuse INTERNAL_JWT_SECRET: every service holds it."
        )
    if secret:
        return secret
    if settings.TARA_ENV == "production":
        raise ImproperlyConfigured("ADS_SERVE_TOKEN_SECRET is required in production.")
    if not _warned_dev_key:
        _warned_dev_key = True
        logger.warning(
            "ADS_SERVE_TOKEN_SECRET is not set; signing ad serve tokens with a "
            "development key derived from SECRET_KEY."
        )
    return _dev_key()


def issue(viewer_id: str, creative_id: str, placement: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "aud": AUDIENCE,
            "sub": str(viewer_id),
            "cid": str(creative_id),
            "pl": placement,
            "iat": now,
            "exp": now + TTL_SECONDS,
            "jti": uuid.uuid4().hex,
        },
        _key(),
        algorithm="HS256",
    )


def _refuse() -> TaraAPIError:
    return TaraAPIError(
        "This ad was not served to you.", code="permission_denied", http_status_code=403
    )


def verify(token: str, viewer_id: str, creative_id: str) -> dict:
    try:
        claims = jwt.decode(
            token,
            _key(),
            algorithms=["HS256"],
            audience=AUDIENCE,
            options={"require": ["exp", "sub", "cid", "jti"]},
        )
    except jwt.PyJWTError as exc:
        raise _refuse() from exc
    if claims["sub"] != str(viewer_id) or claims["cid"] != str(creative_id):
        raise _refuse()
    return claims


def spend(claims: dict, kind: str) -> bool:
    """True the first time this token is used for this kind of event."""
    return cache.add(f"ad-token:{kind}:{claims['jti']}", 1, TTL_SECONDS)
