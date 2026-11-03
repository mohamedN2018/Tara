"""Client for Identity's internal role API. Identity owns roles; Admin only asks."""

from __future__ import annotations

import logging
import time

import jwt
import requests
from django.conf import settings

from tara_common.exceptions import DependencyUnavailable, TaraAPIError

logger = logging.getLogger("tara.admin.identity_client")


def _token() -> str:
    now = int(time.time())
    return jwt.encode(
        {"iss": "admin", "aud": "identity-internal", "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )


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
