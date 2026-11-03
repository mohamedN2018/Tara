"""The user management console (roadmap 8.6): search, the account page, staff actions.

Identity owns accounts and makes every decision about them (suspension,
sign-out, verification): admin asks through ``identity_client``, and the audit
rows for those decisions come back as events. Admin's own decisions here are
reads: opening an account's page and revealing its personal data. Each one is
audited by admin itself, and the row commits *before* the data is returned, so
nobody sees an account without the log knowing.

Profile names and per-account counts are best effort: a service that does not
answer shows as ``None``, never as zero, and never fails the page.
"""

from __future__ import annotations

import logging
import re
import uuid
from concurrent.futures import ThreadPoolExecutor

import requests
from django.conf import settings
from django.db import transaction

from tara_common.auth import mint_internal_token
from tara_common.exceptions import TaraAPIError
from tara_common.middleware import current_request_id
from tara_resilience import CircuitBreaker

from . import audit, identity_client

logger = logging.getLogger("tara.admin.users")
_breakers: dict[str, CircuitBreaker] = {}

SEARCH_FIELDS = ("auto", "email", "handle", "name", "id")
COUNT_METRICS = {"post": "posts", "marketplace": "listings", "moderation": "open_cases"}
_EMAIL_LIKE = re.compile(r"^[^@\s]+@")


def _breaker(name: str) -> CircuitBreaker:
    return _breakers.setdefault(name, CircuitBreaker(name=name, recovery_timeout=15.0))


def _internal_get(service: str, url: str, *, method: str = "GET", **kwargs):
    """Call another service's internal API with the shared secret; None when it can't answer."""

    def _call():
        token = mint_internal_token(issuer="admin", audience=f"{service}-internal")
        resp = requests.request(
            method,
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=settings.USERS_CALL_TIMEOUT,
            **kwargs,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    try:
        return _breaker(f"users:{service}").call(_call)
    except Exception:  # noqa: BLE001 - one service down must not break the page
        logger.warning("user console call failed", extra={"service": service})
        return None


# ---- search -----------------------------------------------------------------


def _field(q: str, field: str) -> str:
    if field != "auto":
        return field
    try:
        uuid.UUID(q)
        return "id"
    except ValueError:
        pass
    if q.startswith("@"):
        return "handle"
    if _EMAIL_LIKE.match(q):
        return "email"
    return "any"


def _profiles_by_account(ids: list[str]) -> dict[str, dict]:
    if not ids:
        return {}
    body = _internal_get(
        "profile",
        f"{settings.PROFILE_INTERNAL_URL}/internal/v1/profiles/by-account/",
        method="POST",
        json={"account_ids": ids},
    )
    data = (body or {}).get("data")
    return data if isinstance(data, dict) else {}


def _row(summary: dict, profile: dict | None) -> dict:
    return {
        "account_id": summary["account_id"],
        "email_masked": summary.get("email_masked", ""),
        "status": summary.get("status", ""),
        "email_verified": bool(summary.get("email_verified")),
        "created_at": summary.get("created_at"),
        "handle": (profile or {}).get("handle"),
        "display_name": (profile or {}).get("display_name"),
    }


def search(q: str, *, field: str = "auto", cursor: str | None = None, limit: int = 20) -> dict:
    """One page of matching accounts: ``{"data": [...], "page": {...}, "field": mode}``.

    Ids and emails are searched in identity (keyset on the email), handles and
    names in profile (keyset on the handle); the cursor is the owner's own, so
    the same query walks the same index page after page.
    """
    q = q.strip()
    mode = _field(q, field)
    if mode in ("id", "email"):
        if mode == "id":
            try:
                q = str(uuid.UUID(q))
            except ValueError as exc:
                raise TaraAPIError(
                    "That is not an account id.", code="validation_error", http_status_code=400
                ) from exc
        page = identity_client.search_accounts(q, cursor, limit)
        summaries = page["data"]
        profiles = _profiles_by_account([s["account_id"] for s in summaries])
        rows = [_row(s, profiles.get(s["account_id"])) for s in summaries]
        return {"data": rows, "page": page["page"], "field": mode}

    params = {"q": q, "field": {"handle": "handle", "name": "name"}.get(mode, "any")}
    if cursor:
        params["cursor"] = cursor
    params["limit"] = str(limit)
    body = _internal_get(
        "profile", f"{settings.PROFILE_INTERNAL_URL}/internal/v1/profiles/search/", params=params
    )
    if body is None:
        raise TaraAPIError(
            "Searching by handle or name is unavailable right now. Search by email or id.",
            code="dependency_unavailable",
            http_status_code=503,
        )
    profiles = body.get("data") or []
    summaries = identity_client.account_summaries([p["account_id"] for p in profiles])
    by_id = {s["account_id"]: s for s in summaries}
    rows = [_row(by_id[p["account_id"]], p) for p in profiles if p["account_id"] in by_id]
    return {"data": rows, "page": body.get("page") or {}, "field": mode}


# ---- the account page -------------------------------------------------------


def _profile(account_id: str) -> dict | None:
    body = _internal_get(
        "profile", f"{settings.PROFILE_INTERNAL_URL}/internal/v1/profiles/{account_id}/snapshot/"
    )
    data = (body or {}).get("data")
    if not isinstance(data, dict):
        return None
    return {k: data.get(k) for k in ("handle", "display_name", "avatar_media_id")}


def _count(service: str, base_url: str, account_id: str) -> int | None:
    body = _internal_get(service, f"{base_url}/internal/v1/stats/accounts/{account_id}/")
    stats = ((body or {}).get("data") or {}).get("stats") or {}
    value = stats.get(COUNT_METRICS[service])
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def detail(account_id: str) -> dict:
    """Identity's overview (required) with the profile and counts (best effort)."""
    overview = identity_client.account_overview(account_id)
    targets = dict(settings.USER_COUNT_TARGETS)
    with ThreadPoolExecutor(max_workers=1 + len(targets)) as pool:
        profile = pool.submit(_profile, account_id)
        counts = {
            COUNT_METRICS[svc]: pool.submit(_count, svc, url, account_id)
            for svc, url in targets.items()
            if svc in COUNT_METRICS
        }
        return {
            **overview,
            "profile": profile.result(),
            "counts": {metric: future.result() for metric, future in counts.items()},
        }


def record_view(account_id: str, actor_id: str) -> None:
    """Audit one look at an account page (commits before the page is returned)."""
    with transaction.atomic():
        audit.record(
            "user.viewed",
            actor_id=actor_id,
            target_type="account",
            target_id=account_id,
            request_id=current_request_id() or "",
        )


def reveal(account_id: str, actor_id: str, reason: str) -> dict:
    """Personal data, after its audit row (with the typed reason) has committed."""
    personal = identity_client.account_personal_data(account_id)
    with transaction.atomic():
        audit.record(
            "user.personal_data.revealed",
            actor_id=actor_id,
            target_type="account",
            target_id=account_id,
            request_id=current_request_id() or "",
            detail={"fields": ["email", "phone", "sessions"]},
            reason=reason,
        )
    return personal


# ---- staff actions (identity decides and audits them through its events) -----


def _not_self(account_id: str, actor_id: str) -> None:
    if str(account_id) == str(actor_id):
        raise TaraAPIError(
            "You can't do this to your own account.", code="validation_error", http_status_code=400
        )


def suspend(account_id: str, actor_id: str, *, reason: str, until, idempotency_key: str) -> dict:
    _not_self(account_id, actor_id)
    return identity_client.suspend(
        account_id,
        actor_id=actor_id,
        reason=reason,
        until=until.isoformat() if until else None,
        idempotency_key=idempotency_key,
    )


def unsuspend(account_id: str, actor_id: str, *, reason: str) -> dict:
    _not_self(account_id, actor_id)
    return identity_client.unsuspend(account_id, actor_id=actor_id, reason=reason)


def sign_out_everywhere(account_id: str, actor_id: str) -> dict:
    _not_self(account_id, actor_id)
    return identity_client.sign_out_everywhere(account_id, actor_id=actor_id)


def resend_verification(account_id: str, actor_id: str) -> dict:
    return identity_client.resend_verification(account_id, actor_id=actor_id)
