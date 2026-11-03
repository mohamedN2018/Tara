"""Client for Identity's internal role and capability API. Identity owns both; Admin asks.

Identity accepts these calls only with a token signed with ADMIN_IDENTITY_SECRET,
which identity and admin alone hold (roadmap 1.0d), never with the shared
INTERNAL_JWT_SECRET.
"""

from __future__ import annotations

import logging

import requests
from django.conf import settings

from tara_common.auth import mint_internal_token
from tara_common.exceptions import Conflict, DependencyUnavailable, TaraAPIError
from tara_common.middleware import current_request_id

logger = logging.getLogger("tara.admin.identity_client")

ISSUER = "admin"
ROLES_AUDIENCE = "identity.roles"


def _token() -> str:
    secret = getattr(settings, "ADMIN_IDENTITY_SECRET", "")
    if not secret:
        logger.error("ADMIN_IDENTITY_SECRET is not set; not calling identity")
        raise DependencyUnavailable("Identity is unavailable.")
    return mint_internal_token(issuer=ISSUER, audience=ROLES_AUDIENCE, secret=secret)


def _headers() -> dict:
    headers = {"Authorization": f"Bearer {_token()}"}
    # The edge's id for this admin request: identity puts it on the events
    # it emits, so the audit log ties the decision to the request.
    request_id = current_request_id()
    if request_id:
        headers["X-Request-Id"] = request_id
    return headers


def _request(method: str, path: str, **kwargs) -> dict:
    try:
        resp = requests.request(
            method,
            f"{settings.IDENTITY_INTERNAL_URL}/internal/v1/{path}",
            headers=_headers(),
            timeout=settings.IDENTITY_CALL_TIMEOUT,
            **kwargs,
        )
    except requests.RequestException as exc:
        logger.warning("identity unreachable", exc_info=True)
        raise DependencyUnavailable("Identity is unavailable.") from exc
    if resp.status_code == 404:
        raise TaraAPIError("Account not found.", code="not_found", http_status_code=404)
    if resp.status_code in (400, 409, 429):
        # Identity validated the change (the locked admin role, a staff account
        # that can't be suspended, a resend too soon): pass it on.
        try:
            error = resp.json().get("error") or {}
        except ValueError:
            error = {}
        message = str(error.get("message") or "Invalid request.")
        if resp.status_code == 409:
            raise Conflict(message, code="conflict")
        if resp.status_code == 429:
            raise TaraAPIError(message, code="throttled", http_status_code=429)
        raise TaraAPIError(
            message,
            code="validation_error",
            details=error.get("details") if isinstance(error.get("details"), list) else None,
            http_status_code=400,
        )
    if resp.status_code in (401, 403):
        # Identity and admin disagree on ADMIN_IDENTITY_SECRET (or it is unset there).
        logger.error("identity refused admin's service token", extra={"status": resp.status_code})
        raise DependencyUnavailable("Identity is unavailable.")
    if not resp.ok:
        logger.warning("identity role call failed", extra={"status": resp.status_code})
        raise DependencyUnavailable("Identity is unavailable.")
    return resp.json()


def _call(method: str, path: str, **kwargs):
    return _request(method, path, **kwargs)["data"]


def _call_page(method: str, path: str, **kwargs) -> dict:
    body = _request(method, path, **kwargs)
    return {"data": body.get("data") or [], "page": body.get("page") or {}}


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


def capability_matrix() -> dict:
    return _call("GET", "capabilities/")


def update_capabilities(changes: list[dict], actor_id: str) -> dict:
    return _call("PUT", "capabilities/", json={"changes": changes, "actor_id": str(actor_id)})


# ---- user management console (8.6) and suspensions (8.4) --------------------


def search_accounts(q: str, cursor: str | None = None, limit: int | None = None) -> dict:
    """``{"data": [...], "page": {...}}``: accounts by id or email prefix, masked."""
    params = {"q": q}
    if cursor:
        params["cursor"] = cursor
    if limit:
        params["limit"] = str(limit)
    return _call_page("GET", "accounts/search/", params=params)


def account_summaries(ids: list[str]) -> list[dict]:
    return _call("POST", "accounts/summaries/", json={"ids": [str(i) for i in ids]})


def account_overview(account_id: str) -> dict:
    return _call("GET", f"accounts/{account_id}/overview/")


def account_personal_data(account_id: str) -> dict:
    return _call("GET", f"accounts/{account_id}/personal/")


def suspend(
    account_id: str, *, actor_id: str, reason: str, until: str | None, idempotency_key: str
) -> dict:
    return _call(
        "POST",
        f"accounts/{account_id}/suspension/",
        json={
            "actor_id": str(actor_id),
            "reason": reason,
            "until": until,
            "idempotency_key": idempotency_key,
            "source": "admin",
        },
    )


def unsuspend(account_id: str, *, actor_id: str, reason: str) -> dict:
    return _call(
        "DELETE",
        f"accounts/{account_id}/suspension/",
        json={"actor_id": str(actor_id), "reason": reason},
    )


def sign_out_everywhere(account_id: str, *, actor_id: str) -> dict:
    return _call("POST", f"accounts/{account_id}/sign-out/", json={"actor_id": str(actor_id)})


def resend_verification(account_id: str, *, actor_id: str) -> dict:
    return _call("POST", f"accounts/{account_id}/verification/", json={"actor_id": str(actor_id)})
