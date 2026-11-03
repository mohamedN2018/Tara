"""The viewer's friends, from graph, in one call (for list filters and invites).

Graph's fan-out endpoint already leaves out accounts blocked either way. A
failure returns ``None``: list filters then treat the viewer as having no
friends (fail closed), and invites refuse with 503.
"""

from __future__ import annotations

import logging
import time

import jwt
import requests
from django.conf import settings

from tara_resilience import CircuitBreaker

logger = logging.getLogger("tara.post.gatherings.graph")
_breaker = CircuitBreaker(name="graph-friends", failure_threshold=5, recovery_timeout=20.0)


def _internal_token() -> str:
    now = int(time.time())
    return jwt.encode(
        {"iss": "post", "aud": "graph-internal", "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )


def friend_ids(account_id: str) -> set[str] | None:
    """The account's friends, or ``None`` when graph could not answer."""

    def _call() -> set[str]:
        resp = requests.get(
            f"{settings.GRAPH_INTERNAL_URL}/internal/v1/fanout/{account_id}/",
            headers={"Authorization": f"Bearer {_internal_token()}"},
            timeout=settings.GRAPH_CALL_TIMEOUT,
        )
        resp.raise_for_status()
        return {str(f) for f in resp.json().get("data", {}).get("friends", [])}

    try:
        return _breaker.call(_call)
    except Exception:  # noqa: BLE001 - circuit open, timeout, error: the caller fails closed
        logger.warning("graph friends lookup failed", exc_info=True)
        return None
