"""Follow state and follower counts of pages, from graph, in one call.

Graph owns follows; the page header and the Pages manager show "Following"
and the follower count. The call fails open: when graph cannot answer, the
counts are ``None`` and the web app hides them (it never shows a made-up 0).
"""

from __future__ import annotations

import logging

import requests
from django.conf import settings

from tara_common.auth import mint_internal_token
from tara_resilience import CircuitBreaker

logger = logging.getLogger("tara.profile.page_graph")
_breaker = CircuitBreaker(name="graph-page-stats", failure_threshold=5, recovery_timeout=20.0)

MAX_BATCH = 50  # graph's own cap per call


def page_stats(viewer_id: str, page_ids: list) -> dict[str, dict]:
    """``{page_id: {"following": bool, "followers_count": int}}``; ``{}`` when
    graph is down (each page then reads as unknown)."""
    ids = list(dict.fromkeys(str(p) for p in page_ids))[:MAX_BATCH]
    if not ids:
        return {}

    def _call() -> dict[str, dict]:
        token = mint_internal_token(issuer="profile", audience="graph-internal")
        resp = requests.post(
            f"{settings.GRAPH_INTERNAL_URL}/internal/v1/relationships/batch/",
            json={"viewer_id": str(viewer_id), "users": [], "pages": ids},
            headers={"Authorization": f"Bearer {token}"},
            timeout=settings.GRAPH_CALL_TIMEOUT,
        )
        resp.raise_for_status()
        results = resp.json().get("data", {}).get("results", {})
        return {
            str(k): {
                "following": bool(v.get("following")),
                "followers_count": int(v.get("followers_count") or 0),
            }
            for k, v in results.items()
            if isinstance(v, dict)
        }

    try:
        return _breaker.call(_call)
    except Exception:  # noqa: BLE001 - circuit open, timeout, error: counts unknown
        logger.warning("graph page stats lookup failed", exc_info=True)
        return {}
