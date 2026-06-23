"""Synchronous JWT verification for WebSocket connects (JWKS or static PEM)."""

from __future__ import annotations

import threading
import time

import jwt
from django.conf import settings
from jwt import PyJWKClient

_lock = threading.Lock()
_client: PyJWKClient | None = None
_fetched_at = 0.0


def _signing_key(token: str):
    pem = getattr(settings, "TARA_JWT_PUBLIC_KEY", "")
    if pem:
        return pem
    global _client, _fetched_at
    with _lock:
        now = time.monotonic()
        ttl = settings.TARA_JWKS_CACHE_TTL
        if _client is None or (now - _fetched_at) > ttl:
            _client = PyJWKClient(settings.TARA_JWKS_URL, cache_keys=True)
            _fetched_at = now
    return _client.get_signing_key_from_jwt(token).key


def verify_access_token(token: str) -> dict:
    """Return claims for a valid RS256 access token, else raise jwt exceptions."""
    return jwt.decode(
        token,
        _signing_key(token),
        algorithms=["RS256"],
        audience=settings.TARA_JWT_AUDIENCE,
        issuer=settings.TARA_JWT_ISSUER,
        options={"require": ["exp", "iat", "sub"]},
    )
