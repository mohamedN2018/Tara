"""Posting as a page: profile decides who may act for a page.

A page post is stored with ``author_type="page"`` and ``author_id`` set to the
page id, so it shows on the page's timeline (``GET /posts/?author_id=<page>``)
and never on the editor's own. Profile is asked before every write (publishing
and deleting are revocation-critical: an editor removed a moment ago must not
post). The check fails closed: when profile cannot answer, nothing is written
(503).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import requests
from django.conf import settings
from django.core.cache import cache

from tara_common.auth import mint_internal_token
from tara_common.exceptions import TaraAPIError
from tara_resilience import CircuitBreaker

logger = logging.getLogger("tara.post.pages")
_breaker = CircuitBreaker(name="profile-pages", failure_threshold=5, recovery_timeout=20.0)

AUTHOR_TYPE = "page"
# Seconds a page's visibility answer is trusted. A page set back to draft,
# suspended or deleted takes its posts away within this time.
VISIBILITY_TTL = 15
MAX_LOOKUP = 200  # page ids per call (profile's limit)


@dataclass(frozen=True)
class PageAccess:
    page_id: str
    role: str | None
    status: str
    can_post: bool
    can_moderate: bool


def _not_found() -> TaraAPIError:
    return TaraAPIError("Page not found.", code="not_found", http_status_code=404)


def _unavailable() -> TaraAPIError:
    return TaraAPIError(
        "Pages are unavailable; try again.", code="dependency_unavailable", http_status_code=503
    )


_MISSING = object()


def _fetch(page_id: str, account_id: str):
    def _call():
        token = mint_internal_token(issuer="post", audience="profile-internal")
        resp = requests.get(
            f"{settings.PROFILE_INTERNAL_URL}/internal/v1/pages/{page_id}/access/",
            params={"account_id": str(account_id)},
            headers={"Authorization": f"Bearer {token}"},
            timeout=settings.GRAPH_CALL_TIMEOUT,
        )
        if resp.status_code == 404:
            return _MISSING
        resp.raise_for_status()
        return resp.json()["data"]

    try:
        return _breaker.call(_call)
    except Exception as exc:  # noqa: BLE001 - circuit open, timeout, error: fail closed
        logger.warning("page access check failed", exc_info=True)
        raise _unavailable() from exc


def access(page_id: str, account_id: str) -> PageAccess:
    """The account's standing on the page; 404 for no such page, 503 when
    profile cannot answer."""
    data = _fetch(str(page_id), str(account_id))
    if data is _MISSING:
        raise _not_found()
    return PageAccess(
        page_id=str(data["page_id"]),
        role=data.get("role"),
        status=str(data.get("status") or ""),
        can_post=bool(data.get("can_post")),
        can_moderate=bool(data.get("can_moderate")),
    )


def require_poster(page_id: str, account_id: str) -> PageAccess:
    """Owners, admins and editors of a published page. Anyone else is told the
    page does not exist (404) unless they are on its team (403)."""
    acc = access(page_id, account_id)
    if acc.role is None:
        raise _not_found()
    if not acc.can_post:
        raise TaraAPIError(
            "You can't post as this page.", code="permission_denied", http_status_code=403
        )
    return acc


def require_moderator(page_id: str, account_id: str) -> PageAccess:
    """Owners, admins, editors and moderators may delete the page's posts.
    Anyone else sees a 404, as for a post they may not delete."""
    acc = access(page_id, account_id)
    if not acc.can_moderate:
        raise TaraAPIError("Post not found.", code="not_found", http_status_code=404)
    return acc


# ---- reads: may the viewer see this page's posts? ------------------------------------


def _visibility_key(page_id: str, viewer_id: str | None) -> str:
    return f"post:pages:vis:{page_id}:{viewer_id or '-'}"


def _fetch_visibility(page_ids: list[str], viewer_id: str | None) -> set[str] | None:
    """Profile's answer (the visible ids), ``None`` when it could not answer."""

    def _call():
        token = mint_internal_token(issuer="post", audience="profile-internal")
        resp = requests.post(
            f"{settings.PROFILE_INTERNAL_URL}/internal/v1/pages/visibility/",
            json={"page_ids": page_ids, "viewer_id": viewer_id},
            headers={"Authorization": f"Bearer {token}"},
            timeout=settings.GRAPH_CALL_TIMEOUT,
        )
        resp.raise_for_status()
        return {str(i) for i in resp.json()["data"]["visible"]}

    try:
        return _breaker.call(_call)
    except Exception:  # noqa: BLE001 - circuit open, timeout, error: fail closed
        logger.warning("page visibility check failed", exc_info=True)
        return None


def visible_pages(viewer_id: str | None, page_ids) -> set[str]:
    """Which of ``page_ids`` the viewer may see, as profile decides for the page
    itself: published and live, or the viewer is on the page's team; never a
    page whose owner has a block with the viewer. ``viewer_id`` ``None`` means
    anyone (published, live pages only).

    Answers are cached briefly per page and viewer, and unknown ones asked in
    one call. Profile down: the pages not in the cache are hidden (fail closed).
    """
    viewer = str(viewer_id) if viewer_id else None
    ids = sorted({str(p) for p in page_ids})
    if not ids:
        return set()
    keys = {page_id: _visibility_key(page_id, viewer) for page_id in ids}
    cached = cache.get_many(list(keys.values()))
    visible = {p for p in ids if cached.get(keys[p]) is True}
    unknown = [p for p in ids if keys[p] not in cached]
    for start in range(0, len(unknown), MAX_LOOKUP):
        chunk = unknown[start : start + MAX_LOOKUP]
        found = _fetch_visibility(chunk, viewer)
        if found is None:
            continue  # not cached: asked again on the next read
        visible |= found & set(chunk)
        cache.set_many({keys[p]: p in found for p in chunk}, VISIBILITY_TTL)
    return visible


def require_editor(page_id: str, account_id: str) -> PageAccess:
    """Editing a page's post: owners, admins and editors (as for publishing).
    Anyone outside the page's team is told the post does not exist (404), a
    team member without the role 403."""
    acc = access(page_id, account_id)
    if acc.role is None:
        raise TaraAPIError("Post not found.", code="not_found", http_status_code=404)
    if not acc.can_post:
        raise TaraAPIError(
            "You can't edit this page's posts.", code="permission_denied", http_status_code=403
        )
    return acc
