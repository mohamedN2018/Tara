"""Ad serve tokens.

Serving a creative signs a short-lived token for that viewer, creative and
placement. The events endpoint spends budget only against such a token, so
nobody can burn a competitor's budget by posting a creative id they were never
shown, and each token pays for at most one impression and one click.
"""

from __future__ import annotations

import hashlib
import hmac
import time
import uuid

import jwt
from django.conf import settings
from django.core.cache import cache

from tara_common.exceptions import TaraAPIError

AUDIENCE = "ad-serve"
TTL_SECONDS = 30 * 60


def _key() -> str:
    """Browsers hold these tokens, so they never get the internal secret itself."""
    return hmac.new(
        settings.TARA_INTERNAL_JWT_SECRET.encode(), b"ad-serve-token", hashlib.sha256
    ).hexdigest()


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
