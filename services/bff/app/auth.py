"""Local JWT verification for the BFF using the issuer's JWKS (cached)."""

from __future__ import annotations

import time

import jwt
from fastapi import Depends, HTTPException, Request
from jwt import PyJWKClient

from .config import settings

_client: PyJWKClient | None = None
_fetched_at: float = 0.0


def _jwk_client() -> PyJWKClient:
    global _client, _fetched_at
    now = time.monotonic()
    if _client is None or (now - _fetched_at) > settings.jwks_cache_ttl:
        _client = PyJWKClient(settings.jwks_url, cache_keys=True)
        _fetched_at = now
    return _client


def verify_token(token: str) -> dict:
    try:
        signing_key = _jwk_client().get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="access token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="invalid access token") from exc
    except Exception as exc:  # JWKS fetch failure, etc.
        raise HTTPException(status_code=503, detail="unable to verify token") from exc


def current_claims(request: Request) -> dict:
    """FastAPI dependency: extract + verify the bearer token."""
    header = request.headers.get("authorization", "")
    parts = header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="missing bearer token")
    return verify_token(parts[1])


CurrentClaims = Depends(current_claims)
