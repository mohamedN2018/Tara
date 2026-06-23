"""Graph client for fan-out audience (followers/friends of an author)."""

from __future__ import annotations

import time

import jwt
import requests
from django.conf import settings

from tara_resilience import CircuitBreaker, CircuitOpenError

_breaker = CircuitBreaker(name="graph-fanout", failure_threshold=5, recovery_timeout=20.0)


class GraphUnavailable(Exception):
    """Raised when the audience can't be resolved — the consumer should retry."""


def _internal_token() -> str:
    now = int(time.time())
    return jwt.encode(
        {"iss": "feed", "aud": "graph-internal", "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )


def fanout_audience(author_id: str) -> dict:
    """Return {followers, friends, recipients} for an author. Raises on failure."""
    url = f"{settings.GRAPH_INTERNAL_URL}/internal/v1/fanout/{author_id}/"

    def _call() -> dict:
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {_internal_token()}"},
            timeout=settings.GRAPH_CALL_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json().get("data", {})

    try:
        return _breaker.call(_call)
    except CircuitOpenError as exc:
        raise GraphUnavailable("graph circuit open") from exc
    except Exception as exc:  # noqa: BLE001
        raise GraphUnavailable(str(exc)) from exc
