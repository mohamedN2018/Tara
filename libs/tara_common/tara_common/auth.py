"""Decentralized JWT verification.

Every service verifies a user's RS256 access token **locally** — either against
a configured public key (PEM) or by fetching the issuer's JWKS (cached). No
per-request call to the Identity service. See ADR-005 / ADR-001.

Settings used (any Django service):
    TARA_JWT_PUBLIC_KEY   PEM string of the issuer public key (optional)
    TARA_JWKS_URL         URL to fetch JWKS from (optional; used if no PEM)
    TARA_JWT_ISSUER       expected `iss`
    TARA_JWT_AUDIENCE     expected `aud`
    TARA_JWKS_CACHE_TTL   seconds to cache JWKS (default 300)
    TARA_JWKS_TIMEOUT     seconds to wait for the JWKS fetch (default 5)
"""

from __future__ import annotations

import threading
import time
from typing import Any

import jwt
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from jwt import PyJWKClient
from rest_framework import authentication, exceptions


class VerificationUnavailable(exceptions.APIException):
    """The issuer's JWKS cannot be fetched: says nothing about the token itself."""

    status_code = 503
    default_detail = "Unable to verify the access token right now."
    default_code = "dependency_unavailable"


class TokenUser:
    """Lightweight authenticated principal carried by a verified access token.

    We do NOT hit the database here — the token's claims are the identity. The
    owning service loads its own row if it needs more than the account id.
    """

    is_authenticated = True
    is_anonymous = False

    def __init__(self, claims: dict[str, Any]) -> None:
        self.claims = claims
        self.id = claims.get("sub")
        self.pk = claims.get("sub")  # DRF throttles/permissions read request.user.pk
        self.account_id = claims.get("sub")
        self.handle = claims.get("handle")
        self.email = claims.get("email")
        self.scopes = set(claims.get("scope", "").split()) if claims.get("scope") else set()
        # RBAC roles (e.g. "moderator", "admin"); Identity owns them and embeds
        # them in the access token. Empty for ordinary users.
        self.roles = set(claims.get("roles", []) or [])

    def __str__(self) -> str:  # pragma: no cover - debug aid
        return f"TokenUser(id={self.id})"


class _JWKSCache:
    """Tiny TTL cache around PyJWKClient (thread-safe)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._client: PyJWKClient | None = None
        self._fetched_at: float = 0.0
        self._url: str | None = None

    def signing_key(self, url: str, token: str, ttl: int, timeout: float = 5):
        with self._lock:
            now = time.monotonic()
            if self._client is None or self._url != url or (now - self._fetched_at) > ttl:
                self._client = PyJWKClient(url, cache_keys=True, timeout=timeout)
                self._url = url
                self._fetched_at = now
        return self._client.get_signing_key_from_jwt(token)


_jwks_cache = _JWKSCache()


class JWTAuthentication(authentication.BaseAuthentication):
    """DRF authentication that validates the RS256 access token."""

    keyword = "Bearer"

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).decode("latin-1")
        if not header:
            return None  # allow other authenticators / AllowAny
        parts = header.split()
        if not parts or parts[0] != self.keyword:
            return None
        if len(parts) != 2:
            raise exceptions.AuthenticationFailed("Malformed Authorization header.")

        token = parts[1]
        claims = self._decode(token)
        return (TokenUser(claims), token)

    def authenticate_header(self, request):
        return self.keyword

    def _decode(self, token: str) -> dict[str, Any]:
        issuer = getattr(settings, "TARA_JWT_ISSUER", None)
        audience = getattr(settings, "TARA_JWT_AUDIENCE", None)
        options = {"require": ["exp", "iat", "sub"]}
        try:
            key = self._resolve_key(token)
            return jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=audience,
                issuer=issuer,
                options=options,
            )
        except jwt.ExpiredSignatureError as exc:
            raise exceptions.AuthenticationFailed("Access token has expired.") from exc
        except jwt.PyJWKClientConnectionError as exc:
            # Not a 401: clients would throw their session away for it.
            raise VerificationUnavailable() from exc
        except jwt.PyJWKClientError as exc:  # unknown kid
            raise exceptions.AuthenticationFailed("Unable to verify token signature.") from exc
        except jwt.InvalidTokenError as exc:
            raise exceptions.AuthenticationFailed("Invalid access token.") from exc

    def _resolve_key(self, token: str):
        pem = getattr(settings, "TARA_JWT_PUBLIC_KEY", None)
        if pem:
            return pem
        jwks_url = getattr(settings, "TARA_JWKS_URL", None)
        if not jwks_url:
            raise exceptions.AuthenticationFailed(
                "No verification key configured (set TARA_JWT_PUBLIC_KEY or TARA_JWKS_URL)."
            )
        ttl = int(getattr(settings, "TARA_JWKS_CACHE_TTL", 300))
        timeout = float(getattr(settings, "TARA_JWKS_TIMEOUT", 5))
        return _jwks_cache.signing_key(jwks_url, token, ttl, timeout).key


INTERNAL_TOKEN_TTL_SECONDS = 30


def mint_internal_token(
    *,
    issuer: str,
    audience: str,
    secret: str | None = None,
    ttl_seconds: int = INTERNAL_TOKEN_TTL_SECONDS,
) -> str:
    """Sign a short-lived HS256 service-to-service token.

    ``secret`` defaults to the shared ``TARA_INTERNAL_JWT_SECRET``. The caller of
    a privileged endpoint passes the secret it shares with that endpoint alone.
    An empty ``secret`` raises ``ImproperlyConfigured``; it never falls back to
    the shared one.
    """
    key = getattr(settings, "TARA_INTERNAL_JWT_SECRET", None) if secret is None else secret
    if not key:
        raise ImproperlyConfigured("Internal token secret not configured.")
    now = int(time.time())
    return jwt.encode(
        {"iss": issuer, "aud": audience, "iat": now, "exp": now + ttl_seconds},
        key,
        algorithm="HS256",
    )


def verify_internal_token(
    token: str,
    *,
    expected_audience: str | None = None,
    secret: str | None = None,
    expected_issuer: str | None = None,
) -> dict[str, Any]:
    """Verify a short-lived HS256 service-to-service token (NOT a user token).

    With no ``secret`` the token must be signed with the shared
    ``TARA_INTERNAL_JWT_SECRET``. Every service holds that secret, so the
    token's ``iss`` proves nothing about who sent it.

    A privileged endpoint passes ``secret`` (a key that only it and one named
    caller hold) and ``expected_issuer``. The shared secret is then not tried at
    all, so a token signed with it fails, and an empty ``secret`` fails closed
    instead of falling back to it.

    Raises a ``jwt.InvalidTokenError`` subclass for a bad token, and
    ``AuthenticationFailed`` when no secret is configured.
    """
    if secret is None:
        secret = getattr(settings, "TARA_INTERNAL_JWT_SECRET", None)
    if not secret:
        raise exceptions.AuthenticationFailed("Internal token secret not configured.")
    required = ["exp", "iat"]
    if expected_issuer is not None:
        required.append("iss")
    return jwt.decode(
        token,
        secret,
        algorithms=["HS256"],
        audience=expected_audience,
        issuer=expected_issuer,
        options={"require": required},
    )
