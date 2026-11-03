"""Graph client: fan-out audience and pairwise relationship for an author."""

from __future__ import annotations

import time
from dataclasses import dataclass

import jwt
import requests
from django.conf import settings

from tara_resilience import CircuitBreaker, CircuitOpenError

_breaker = CircuitBreaker(name="graph-fanout", failure_threshold=5, recovery_timeout=20.0)
_relationship_breaker = CircuitBreaker(
    name="graph-relationship", failure_threshold=5, recovery_timeout=20.0
)


class GraphUnavailable(Exception):
    """Raised when the audience can't be resolved — the consumer should retry."""


@dataclass(frozen=True)
class Relationship:
    """Graph's view of two accounts, ``a`` and ``b``."""

    are_friends: bool = False
    a_follows_b: bool = False
    b_follows_a: bool = False
    blocked_either_way: bool = False


def _internal_token() -> str:
    now = int(time.time())
    return jwt.encode(
        {"iss": "feed", "aud": "graph-internal", "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )


def _get(breaker: CircuitBreaker, path: str, params: dict | None = None) -> dict:
    url = f"{settings.GRAPH_INTERNAL_URL}/internal/v1/{path}"

    def _call() -> dict:
        resp = requests.get(
            url,
            params=params,
            headers={"Authorization": f"Bearer {_internal_token()}"},
            timeout=settings.GRAPH_CALL_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json().get("data", {})

    try:
        return breaker.call(_call)
    except CircuitOpenError as exc:
        raise GraphUnavailable(f"circuit '{breaker.name}' open") from exc
    except Exception as exc:  # noqa: BLE001
        raise GraphUnavailable(str(exc)) from exc


def fanout_audience(author_id: str) -> dict:
    """Return {followers, friends, recipients} for an author. Raises on failure."""
    return _get(_breaker, f"fanout/{author_id}/")


def relationship(a: str, b: str) -> Relationship:
    """Current relationship between ``a`` and ``b``. Raises GraphUnavailable on failure."""
    d = _get(_relationship_breaker, "relationship/", {"a": str(a), "b": str(b)})
    return Relationship(
        are_friends=bool(d.get("are_friends")),
        a_follows_b=bool(d.get("a_follows_b")),
        b_follows_a=bool(d.get("b_follows_a")),
        blocked_either_way=bool(d.get("blocked_either_way")),
    )
