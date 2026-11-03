"""Access + refresh token engine (ADR-005).

- Access token: RS256 JWT, short TTL, verified anywhere via JWKS.
- Refresh token: opaque random string; only its SHA-256 hash is stored. Rotation
  forms a family; reusing a spent/revoked token revokes the whole family.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

import jwt
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from tara_events.envelope import uuid7

from .events import emit_security_event
from .models import Account, RefreshToken, UserSession


class TokenError(Exception):
    """Raised on invalid/expired/reused refresh tokens."""


def _now():
    return timezone.now()


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


# ---- Access tokens ----------------------------------------------------------


def issue_access_token(account: Account, session_id: str) -> tuple[str, int]:
    """Return (jwt, expires_in_seconds)."""
    if not settings.JWT_PRIVATE_KEY:
        raise TokenError("JWT signing key is not configured.")
    ttl = settings.ACCESS_TOKEN_TTL_SECONDS
    now = _now()
    # RBAC roles embedded in the access token (read by tara_common TokenUser.roles
    # and the IsAdmin/IsModerator permissions). Bridged from the account flags:
    # superuser -> admin, staff -> moderator.
    roles: list[str] = []
    if getattr(account, "is_superuser", False):
        roles.append("admin")
    if getattr(account, "is_staff", False):
        roles.append("moderator")
    claims = {
        "sub": str(account.id),
        "email": account.email,
        "type": "access",
        "sid": str(session_id),
        "scope": "user",
        "roles": roles,
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl)).timestamp()),
        "jti": str(uuid7()),
    }
    token = jwt.encode(
        claims,
        settings.JWT_PRIVATE_KEY,
        algorithm="RS256",
        headers={"kid": settings.JWT_KEY_ID},
    )
    return token, ttl


# ---- Refresh tokens ---------------------------------------------------------


def _new_raw_refresh() -> str:
    return secrets.token_urlsafe(48)


def create_refresh_token(
    account: Account,
    session: UserSession,
    *,
    family_id=None,
    rotated_from: RefreshToken | None = None,
) -> tuple[str, RefreshToken]:
    raw = _new_raw_refresh()
    token = RefreshToken.objects.create(
        account=account,
        session=session,
        token_hash=hash_token(raw),
        family_id=family_id or uuid7(),
        rotated_from=rotated_from,
        expires_at=_now() + timedelta(seconds=settings.REFRESH_TOKEN_TTL_SECONDS),
    )
    return raw, token


def _revoke_family(family_id, *, reason: str) -> None:
    RefreshToken.objects.filter(family_id=family_id, revoked_at__isnull=True).update(
        revoked_at=_now()
    )


def rotate_refresh_token(raw: str) -> tuple[Account, UserSession, str, int, str]:
    """Validate + rotate a refresh token.

    Returns (account, session, new_access, access_ttl, new_raw_refresh).
    Raises TokenError on any problem; on reuse, revokes the whole family.
    """
    token_hash = hash_token(raw)
    reused = False
    with transaction.atomic():
        try:
            current = (
                RefreshToken.objects.select_for_update(of=("self",))
                .select_related("account", "session")
                .get(token_hash=token_hash)
            )
        except RefreshToken.DoesNotExist as exc:
            raise TokenError("Invalid refresh token.") from exc

        # Reuse / replay detection. The revocation must commit, so raise afterwards.
        if current.revoked_at is not None or current.used_at is not None:
            reused = True
            _revoke_family(current.family_id, reason="reuse_detected")
            UserSession.objects.filter(id=current.session_id, revoked_at__isnull=True).update(
                revoked_at=_now()
            )
            emit_security_event(
                current.account, "refresh_reuse_detected", {"family_id": str(current.family_id)}
            )
        else:
            if current.expires_at <= _now():
                raise TokenError("Refresh token has expired.")
            if current.session.revoked_at is not None:
                raise TokenError("Session has been revoked.")
            if not current.account.is_usable:
                raise TokenError("Account is not active.")

            # Mark current used, issue the next in the family.
            current.used_at = _now()
            current.save(update_fields=["used_at"])
            current.session.last_seen_at = _now()
            current.session.save(update_fields=["last_seen_at"])

            new_raw, _ = create_refresh_token(
                current.account, current.session, family_id=current.family_id, rotated_from=current
            )
            access, ttl = issue_access_token(current.account, str(current.session_id))

    if reused:
        raise TokenError("Refresh token reuse detected; session revoked.")
    return current.account, current.session, access, ttl, new_raw


def revoke_session(session: UserSession) -> None:
    """Logout: revoke the session and all its refresh tokens."""
    if session.revoked_at is None:
        session.revoked_at = _now()
        session.save(update_fields=["revoked_at"])
    RefreshToken.objects.filter(session=session, revoked_at__isnull=True).update(revoked_at=_now())


# ---- JWKS -------------------------------------------------------------------


def build_jwks() -> dict:
    """Return the JWKS document advertising our RS256 public key."""
    if not settings.JWT_PUBLIC_KEY:
        return {"keys": []}
    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    from jwt.algorithms import RSAAlgorithm

    public_key = load_pem_public_key(settings.JWT_PUBLIC_KEY.encode())
    jwk = RSAAlgorithm.to_jwk(public_key, as_dict=True)
    jwk.update({"use": "sig", "alg": "RS256", "kid": settings.JWT_KEY_ID})
    return {"keys": [jwk]}
