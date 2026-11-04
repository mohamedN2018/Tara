"""Profile client: a page and the caller's role on its team (page conversations).

A member writes to a Page; the page's team (owner, admins, editors and
moderators) answers as the Page. Every team action asks profile again, so
someone removed from the team loses the page's inbox at once. Profile being
unreachable fails closed (503): nobody gets a page's messages by accident.
"""

from __future__ import annotations

import logging
import time

import jwt
import requests
from django.conf import settings

from tara_common.exceptions import TaraAPIError
from tara_resilience import CircuitBreaker, CircuitOpenError

logger = logging.getLogger("tara.chat.profile_client")
_breaker = CircuitBreaker(name="profile", failure_threshold=5, recovery_timeout=20.0)
# Its own breaker: a failing team lookup must never close the page inbox itself.
_team_breaker = CircuitBreaker(name="profile-team", failure_threshold=5, recovery_timeout=20.0)

#: Page roles that read and answer the page's messages.
PAGE_MESSAGE_ROLES = frozenset({"owner", "admin", "editor", "moderator"})


def _internal_token() -> str:
    now = int(time.time())
    return jwt.encode(
        {"iss": "chat", "aud": "profile-internal", "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )


def _unavailable() -> TaraAPIError:
    return TaraAPIError(
        "Pages are unavailable right now; try again.",
        code="dependency_unavailable",
        http_status_code=503,
    )


def page_access(page_id: str, account_id: str) -> dict | None:
    """``{page_id, handle, name, status, avatar_media_id, role, ...}``, or None
    when the page does not exist (or was deleted). Raises 503 when profile
    cannot answer."""

    def _call() -> dict | None:
        resp = requests.get(
            f"{settings.PROFILE_INTERNAL_URL}/internal/v1/pages/{page_id}/access/",
            params={"account_id": str(account_id)},
            headers={"Authorization": f"Bearer {_internal_token()}"},
            timeout=settings.PROFILE_CALL_TIMEOUT,
        )
        if resp.status_code == 404:
            return None  # an answer, not a failure: the breaker stays closed
        resp.raise_for_status()
        return resp.json().get("data") or {}

    try:
        return _breaker.call(_call)
    except CircuitOpenError as exc:
        raise _unavailable() from exc
    except Exception as exc:  # noqa: BLE001 - any failure fails closed
        logger.warning("profile page access lookup failed")
        raise _unavailable() from exc


def page_team(page_id: str) -> list[str]:
    """Accounts on the page's team that answer its messages (who hears of a new
    one). Empty when the page is gone or profile cannot answer: the message is
    kept either way and the page inbox still shows it."""

    def _call() -> list[str]:
        resp = requests.get(
            f"{settings.PROFILE_INTERNAL_URL}/internal/v1/pages/{page_id}/team/",
            headers={"Authorization": f"Bearer {_internal_token()}"},
            timeout=settings.PROFILE_CALL_TIMEOUT,
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        members = (resp.json().get("data") or {}).get("members") or []
        return [str(m["account_id"]) for m in members if m.get("role") in PAGE_MESSAGE_ROLES]

    try:
        return _team_breaker.call(_call)
    except Exception:  # noqa: BLE001 - the send goes on; only the team notice is lost
        logger.warning("profile page team lookup failed; the page team is not notified")
        return []


def can_answer(access: dict | None) -> bool:
    return bool(access) and access.get("role") in PAGE_MESSAGE_ROLES
