"""Identity client: who answers the support inbox (fix round 3).

A member's message to Tara Support reaches the support team as a notification
(the event's ``team``). The team is everyone holding ``moderation.case.view``,
the same capability that opens the support inbox; identity owns roles and the
capability matrix and lists the holders' ids. The call is signed with
CHAT_IDENTITY_SECRET, which only identity and chat hold.

Failing loses only the notice: the message is kept and the inbox badge still
counts it. The answer is cached briefly (a grant or a revocation reaches the
list within ``CACHE_SECONDS``; the inbox itself checks the token every time).
"""

from __future__ import annotations

import logging

import requests
from django.conf import settings
from django.core.cache import cache

from tara_common.auth import mint_internal_token
from tara_resilience import CircuitBreaker

logger = logging.getLogger("tara.chat.identity_client")
_breaker = CircuitBreaker(name="identity-staff", failure_threshold=5, recovery_timeout=30.0)

ISSUER = "chat"
AUDIENCE = "identity.roles"
SUPPORT_CAPABILITY = "moderation.case.view"
CACHE_KEY = "chat:support-staff:v1"
CACHE_SECONDS = 60


def support_staff() -> list[str]:
    """Ids of the accounts that answer support conversations; [] on any failure."""
    cached = cache.get(CACHE_KEY)
    if isinstance(cached, list):
        return cached

    def _call() -> list[str]:
        token = mint_internal_token(
            issuer=ISSUER, audience=AUDIENCE, secret=settings.CHAT_IDENTITY_SECRET
        )
        resp = requests.get(
            f"{settings.IDENTITY_INTERNAL_URL}/internal/v1/capability-holders/",
            params={"capability": SUPPORT_CAPABILITY},
            headers={"Authorization": f"Bearer {token}"},
            timeout=settings.IDENTITY_CALL_TIMEOUT,
        )
        resp.raise_for_status()
        ids = (resp.json().get("data") or {}).get("account_ids") or []
        return sorted({str(i) for i in ids})

    try:
        staff = _breaker.call(_call)
    except Exception:  # noqa: BLE001 - the send goes on; only the team notice is lost
        logger.warning("identity support staff lookup failed; support staff are not notified")
        return []
    cache.set(CACHE_KEY, staff, CACHE_SECONDS)
    return staff
