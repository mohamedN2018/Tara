"""Internal reads made by search (short-lived HS256 tokens, timeout, circuit breaker).

- graph: the viewer's relationship with the people and pages on a result page.
  Decoration only: when graph is down the results still come back, without
  relationship, mutual friend or follower data (never with guessed values).
- post: an event's current indexable state (the ``gathering.*`` payloads carry
  ids, enums and times only, never the title or place).
- profile, post, marketplace: paged export endpoints for the backfill.
"""

from __future__ import annotations

import logging

import requests
from django.conf import settings

from tara_common.auth import mint_internal_token
from tara_resilience import CircuitBreaker, CircuitOpenError

logger = logging.getLogger("tara.search.clients")

_graph = CircuitBreaker(name="search-graph", failure_threshold=5, recovery_timeout=20.0)
_post = CircuitBreaker(name="search-post", failure_threshold=5, recovery_timeout=20.0)

MAX_RELATIONSHIP_TARGETS = 50


class Unavailable(Exception):
    """An owner service could not answer; the caller retries or degrades."""


def _headers(audience: str) -> dict:
    token = mint_internal_token(issuer="search", audience=audience)
    return {"Authorization": f"Bearer {token}"}


def relationships(viewer_id: str, users: list[str], pages: list[str]) -> dict[str, dict]:
    """``{target_id: {...}}`` from graph's batch endpoint; ``{}`` when graph is unavailable."""
    users, pages = users[:MAX_RELATIONSHIP_TARGETS], pages[:MAX_RELATIONSHIP_TARGETS]
    if not users and not pages:
        return {}

    def _call() -> dict:
        resp = requests.post(
            f"{settings.GRAPH_INTERNAL_URL}/internal/v1/relationships/batch/",
            json={"viewer_id": str(viewer_id), "users": users, "pages": pages},
            headers=_headers("graph-internal"),
            timeout=settings.SEARCH_INTERNAL_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json().get("data", {}).get("results", {})

    try:
        return _graph.call(_call)
    except CircuitOpenError:
        logger.warning("graph circuit open; results without relationships")
    except Exception:  # noqa: BLE001 - decoration only: degrade, never fail the search
        logger.warning("graph relationship batch failed", exc_info=True)
    return {}


def gathering_state(gathering_id: str) -> dict | None:
    """Post's indexable view of one event; ``None`` when it no longer exists.

    Raises ``Unavailable`` so the consumer retries instead of guessing.
    """

    def _call():
        resp = requests.get(
            f"{settings.POST_INTERNAL_URL}/internal/v1/search/gatherings/{gathering_id}/",
            headers=_headers("post-internal"),
            timeout=settings.SEARCH_INTERNAL_TIMEOUT,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()["data"]

    try:
        return _post.call(_call)
    except Exception as exc:  # noqa: BLE001 - the event is retried
        raise Unavailable(f"post unavailable: {exc}") from exc


EXPORTS = {
    # kind: (base url setting, audience)
    "people": ("PROFILE_INTERNAL_URL", "profile-internal"),
    "pages": ("PROFILE_INTERNAL_URL", "profile-internal"),
    "groups": ("PROFILE_INTERNAL_URL", "profile-internal"),
    "posts": ("POST_INTERNAL_URL", "post-internal"),
    "gatherings": ("POST_INTERNAL_URL", "post-internal"),
    "listings": ("MARKETPLACE_INTERNAL_URL", "marketplace-internal"),
}


def export_page(kind: str, after: str | None, limit: int = 200) -> dict:
    """One page of an owner's export: ``{"as_of", "items", "next"}``."""
    setting, audience = EXPORTS[kind]
    try:
        resp = requests.get(
            f"{getattr(settings, setting)}/internal/v1/search/export/{kind}/",
            params={"after": after or "", "limit": limit},
            headers=_headers(audience),
            timeout=max(settings.SEARCH_INTERNAL_TIMEOUT, 10.0),
        )
        resp.raise_for_status()
        return resp.json()["data"]
    except Exception as exc:  # noqa: BLE001
        raise Unavailable(f"{kind} export unavailable: {exc}") from exc
