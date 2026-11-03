"""Social Graph client for audience/visibility resolution (circuit-breaker + degrade)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import jwt
import requests
from django.conf import settings

from tara_resilience import CircuitBreaker, CircuitOpenError

logger = logging.getLogger("tara.post.graph_client")
_breaker = CircuitBreaker(name="graph", failure_threshold=5, recovery_timeout=20.0)


@dataclass(frozen=True)
class Relationship:
    are_friends: bool = False
    a_follows_b: bool = False
    b_follows_a: bool = False
    blocked_either_way: bool = False
    degraded: bool = False

    @classmethod
    def unknown(cls) -> Relationship:
        return cls(degraded=True)


def _internal_token() -> str:
    now = int(time.time())
    return jwt.encode(
        {"iss": "post", "aud": "graph-internal", "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )


def get_relationship(viewer_id: str, author_id: str) -> Relationship:
    if str(viewer_id) == str(author_id):
        return Relationship(are_friends=True, a_follows_b=True)
    url = f"{settings.GRAPH_INTERNAL_URL}/internal/v1/relationship/"

    def _call() -> Relationship:
        resp = requests.get(
            url,
            params={"a": viewer_id, "b": author_id},
            headers={"Authorization": f"Bearer {_internal_token()}"},
            timeout=settings.GRAPH_CALL_TIMEOUT,
        )
        resp.raise_for_status()
        d = resp.json().get("data", {})
        return Relationship(
            are_friends=bool(d.get("are_friends")),
            a_follows_b=bool(d.get("a_follows_b")),
            b_follows_a=bool(d.get("b_follows_a")),
            blocked_either_way=bool(d.get("blocked_either_way")),
        )

    try:
        return _breaker.call(_call)
    except CircuitOpenError:
        logger.warning("graph circuit open; defaulting to no-relationship")
        return Relationship.unknown()
    except Exception:  # noqa: BLE001
        logger.warning("graph relationship lookup failed; defaulting", exc_info=True)
        return Relationship.unknown()


def resolve_handles(handles: list[str]) -> dict[str, str]:
    """``{handle: account_id}`` from Profile. Raises when Profile is down, so the
    consumer retries instead of dropping the mention."""
    now = int(time.time())
    token = jwt.encode(
        {"iss": "post", "aud": "profile-internal", "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )
    resp = requests.post(
        f"{settings.PROFILE_INTERNAL_URL}/internal/v1/profiles/by-handle/",
        json={"handles": handles},
        headers={"Authorization": f"Bearer {token}"},
        timeout=settings.GRAPH_CALL_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json().get("data", {})
