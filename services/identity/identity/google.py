"""Google Identity Services ID-token verification.

Verified locally against Google's published JWKS (signature, ``aud``, ``iss``,
``exp``), with no per-login call to Google's tokeninfo endpoint. The key set is
cached by PyJWKClient. Off unless ``GOOGLE_CLIENT_ID`` is set.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache

import jwt
from django.conf import settings
from jwt import PyJWKClient

logger = logging.getLogger("tara.identity.google")

GOOGLE_ISSUERS = ("accounts.google.com", "https://accounts.google.com")
# GIS credentials are short JWTs; anything far larger is not one.
MAX_CREDENTIAL_LENGTH = 4096
CLOCK_SKEW_SECONDS = 30


class GoogleTokenError(Exception):
    """The credential is not a valid Google ID token for this client."""


@dataclass(frozen=True)
class GoogleIdentity:
    subject: str
    email: str
    name: str


def google_enabled() -> bool:
    return bool(settings.GOOGLE_CLIENT_ID)


@lru_cache(maxsize=1)
def jwk_client() -> PyJWKClient:
    # Google rotates keys about weekly and publishes the next one in advance.
    return PyJWKClient(settings.GOOGLE_JWKS_URL, cache_keys=True, lifespan=3600, timeout=5)


def verify_credential(credential: object) -> GoogleIdentity:
    """Return the verified identity, or raise GoogleTokenError."""
    if not google_enabled():
        raise GoogleTokenError("Google sign-in is not enabled.")
    if not isinstance(credential, str) or not credential or len(credential) > MAX_CREDENTIAL_LENGTH:
        raise GoogleTokenError("Missing or malformed credential.")
    try:
        signing_key = jwk_client().get_signing_key_from_jwt(credential)
        claims = jwt.decode(
            credential,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.GOOGLE_CLIENT_ID,
            leeway=CLOCK_SKEW_SECONDS,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.PyJWKClientError as exc:
        # Unknown kid or JWKS unreachable: indistinguishable for the caller.
        logger.warning("google jwks lookup failed: %s", exc)
        raise GoogleTokenError("Unable to verify the credential signature.") from exc
    except jwt.InvalidTokenError as exc:
        raise GoogleTokenError("Invalid Google credential.") from exc

    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise GoogleTokenError("Unexpected issuer.")
    # GIS sends a boolean; older tokens used the string "true".
    if claims.get("email_verified") not in (True, "true"):
        raise GoogleTokenError("The Google email address is not verified.")
    email = claims.get("email")
    subject = claims.get("sub")
    if not isinstance(email, str) or "@" not in email or not isinstance(subject, str):
        raise GoogleTokenError("The credential has no usable email.")
    return GoogleIdentity(
        subject=subject,
        email=email.strip().lower(),
        name=str(claims.get("name") or "")[:120],
    )
