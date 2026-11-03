"""Client for Identity's internal role API. Identity owns roles; Admin only asks.

Identity accepts these calls only with a token signed with ADMIN_IDENTITY_SECRET,
which identity and admin alone hold (roadmap 1.0d), never with the shared
INTERNAL_JWT_SECRET.
"""

from __future__ import annotations

import logging

import requests
from django.conf import settings

from tara_common.auth import mint_internal_token
from tara_common.exceptions import DependencyUnavailable, TaraAPIError

logger = logging.getLogger("tara.admin.identity_client")

ISSUER = "admin"
ROLES_AUDIENCE = "identity.roles"


def _token() -> str:
    secret = getattr(settings, "ADMIN_IDENTITY_SECRET", "")
    if not secret:
        logger.error("ADMIN_IDENTITY_SECRET is not set; not calling identity")
        raise DependencyUnavailable("Identity is unavailable.")
    return mint_internal_token(issuer=ISSUER, audience=ROLES_AUDIENCE, secret=secret)


def _call(method: str, path: str, **kwargs):
    try:
        resp = requests.request(
            method,
            f"{settings.IDENTITY_INTERNAL_URL}/internal/v1/{path}",
            headers={"Authorization": f"Bearer {_token()}"},
            timeout=settings.IDENTITY_CALL_TIMEOUT,
            **kwargs,
        )
    except requests.RequestException as exc:
        logger.warning("identity unreachable", exc_info=True)
        raise DependencyUnavailable("Identity is unavailable.") from exc
    if resp.status_code == 404:
        raise TaraAPIError("Account not found.", code="not_found", http_status_code=404)
    if resp.status_code in (401, 403):
        # Identity and admin disagree on ADMIN_IDENTITY_SECRET (or it is unset there).
        logger.error("identity refused admin's service token", extra={"status": resp.status_code})
        raise DependencyUnavailable("Identity is unavailable.")
    if not resp.ok:
        logger.warning("identity role call failed", extra={"status": resp.status_code})
        raise DependencyUnavailable("Identity is unavailable.")
    return resp.json()["data"]


def account_roles(account_id: str) -> dict:
    return _call("GET", f"accounts/{account_id}/roles/")


def lookup(email: str) -> dict:
    return _call("GET", "accounts/lookup/", params={"email": email})


def role_holders() -> list[dict]:
    return _call("GET", "role-holders/")


def grant(account_id: str, role: str, actor_id: str) -> dict:
    return _call(
        "POST", f"accounts/{account_id}/roles/", json={"role": role, "actor_id": str(actor_id)}
    )


def revoke(account_id: str, role: str, actor_id: str) -> dict:
    return _call(
        "DELETE", f"accounts/{account_id}/roles/", json={"role": role, "actor_id": str(actor_id)}
    )
