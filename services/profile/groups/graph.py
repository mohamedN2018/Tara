"""The account's friends, from graph, in one call (invites and suggestions).

Graph's fan-out endpoint already leaves out accounts blocked either way. A
failure returns ``None``: invites then refuse with 503, suggestions fall back
to no friend signal.
"""

from __future__ import annotations

import logging

import requests
from django.conf import settings

from tara_common.auth import mint_internal_token
from tara_resilience import CircuitBreaker

logger = logging.getLogger("tara.profile.groups.graph")
_breaker = CircuitBreaker(name="graph-friends", failure_threshold=5, recovery_timeout=20.0)


def friend_ids(account_id: str) -> set[str] | None:
    """The account's friends, or ``None`` when graph could not answer."""

    def _call() -> set[str]:
        token = mint_internal_token(issuer="profile", audience="graph-internal")
        resp = requests.get(
            f"{settings.GRAPH_INTERNAL_URL}/internal/v1/fanout/{account_id}/",
            headers={"Authorization": f"Bearer {token}"},
            timeout=settings.GRAPH_CALL_TIMEOUT,
        )
        resp.raise_for_status()
        return {str(f) for f in resp.json().get("data", {}).get("friends", [])}

    try:
        return _breaker.call(_call)
    except Exception:  # noqa: BLE001 - circuit open, timeout, error: the caller decides
        logger.warning("graph friends lookup failed", exc_info=True)
        return None
