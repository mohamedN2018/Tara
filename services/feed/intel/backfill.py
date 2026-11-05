"""Backfills of the phase-3 read models from the owners' exports (WP 3.2).

Each owner serves a paged export (``/internal/v1/intel/export/<kind>/``, the
``tara_common.search_export`` shape: ``{as_of, items, next}``). A backfill:

1. reads the pages in primary-key order, at most ``rate`` requests per second
   (default 20, the plan's limit for graph), resumable with ``--after <cursor>``;
2. writes each item through the same newest-wins writer as the events, with the
   page's ``as_of`` (the owner's clock before the read) as its time, so an event
   newer than the read still wins and an older one changes nothing;
3. after a complete scan from the start, sweeps what the owner no longer has:
   rows not written by the scan and older than its start are switched off (a
   friendship, follow, block or membership that ended while its event was lost,
   a post deleted unseen). A resumed or partial scan never sweeps.

Nothing here is sent anywhere but the owner's internal endpoint.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime

import requests
from django.conf import settings
from django.db import connection, transaction

from tara_common.auth import mint_internal_token

from . import ports, readmodels

logger = logging.getLogger("tara.intel.backfill")

MAX_LIMIT = 500  # tara_common.search_export.MAX_LIMIT


@dataclass(frozen=True)
class Source:
    """One owner's export: where it is and the token audience it wants."""

    service: str
    base_url: str
    path: str

    @property
    def audience(self) -> str:
        return f"{self.service}-internal"


def source(kind: str) -> Source:
    graph = settings.GRAPH_INTERNAL_URL
    profile = settings.PROFILE_INTERNAL_URL
    post = settings.POST_INTERNAL_URL
    identity = settings.IDENTITY_INTERNAL_URL
    moderation = settings.MODERATION_INTERNAL_URL
    return {
        "posts": Source("post", post, "intel/export/posts/"),
        "friendships": Source("graph", graph, "intel/export/friendships/"),
        "follows": Source("graph", graph, "intel/export/follows/"),
        "blocks": Source("graph", graph, "intel/export/blocks/"),
        "groups": Source("profile", profile, "intel/export/groups/"),
        "group-members": Source("profile", profile, "intel/export/group-members/"),
        "pages": Source("profile", profile, "intel/export/pages/"),
        "accounts": Source("identity", identity, "intel/export/accounts/"),
        "restrictions": Source("moderation", moderation, "intel/export/restrictions/"),
    }[kind]


@dataclass
class Page:
    as_of: datetime
    items: list[dict]
    next: str | None


def fetch_page(src: Source, *, after: str | None, limit: int, timeout: float) -> Page:
    token = mint_internal_token(issuer="feed", audience=src.audience)
    params = {"limit": min(max(limit, 1), MAX_LIMIT)}
    if after:
        params["after"] = after
    resp = requests.get(
        f"{src.base_url}/internal/v1/{src.path}",
        params=params,
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()["data"]
    return Page(readmodels._ts(data["as_of"]), data["items"], data.get("next"))  # noqa: SLF001


def pages(
    src: Source,
    *,
    after: str | None = None,
    limit: int = 200,
    rate: float = 20.0,
    timeout: float = 10.0,
    fetch: Callable[..., Page] = fetch_page,
) -> Iterator[Page]:
    gap = 1.0 / rate if rate > 0 else 0.0
    cursor = after
    while True:
        started = time.monotonic()
        page = fetch(src, after=cursor, limit=limit, timeout=timeout)
        yield page
        cursor = page.next
        if cursor is None:
            return
        wait = gap - (time.monotonic() - started)
        if wait > 0:
            time.sleep(wait)


@dataclass
class Result:
    kind: str
    items: int = 0
    written: int = 0
    swept: int = 0
    pages: int = 0
    complete: bool = False
    last_cursor: str | None = None
    started: datetime | None = None
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "items": self.items,
            "written": self.written,
            "swept": self.swept,
            "pages": self.pages,
            "complete": self.complete,
            "last_cursor": self.last_cursor,
        }


# ---- per-kind writers: (item id, payload, as_of) -> rows written ----------------------


def _write_post(_id: str, p: dict, when: datetime) -> int:
    return int(readmodels.content_backfill(p, when))


def _write_friendship(_id: str, p: dict, when: datetime) -> int:
    return readmodels.set_friendship(
        p.get("a"),
        p.get("b"),
        True,
        when,
        since=readmodels._ts(p.get("accepted_at")),  # noqa: SLF001
    )


def _write_follow(_id: str, p: dict, when: datetime) -> int:
    follower, target = readmodels.uid(p.get("follower")), readmodels.uid(p.get("target"))
    if follower is None or target is None:
        return 0
    return int(ports.set_follow(follower, target, p.get("target_type") or "user", True, when))


def _write_block(_id: str, p: dict, when: datetime) -> int:
    return int(readmodels.set_block(p.get("blocker_id"), p.get("blocked_id"), True, when))


def _write_group(_id: str, p: dict, when: datetime) -> int:
    return readmodels.set_group(p, when)


def _write_member(_id: str, p: dict, when: datetime) -> int:
    return readmodels.set_membership(p, when, joined_at=readmodels._ts(p.get("joined_at")))  # noqa: SLF001


def _write_page(item_id: str, p: dict, when: datetime) -> int:
    return readmodels.set_page(item_id, p, when)


def _write_account(item_id: str, p: dict, when: datetime) -> int:
    """identity lists only accounts that are not active (rule E6)."""
    account_id = readmodels.uid(p.get("account_id") or item_id)
    if account_id is None:
        return 0
    return sum(
        int(ports.set_author_lifecycle(account_id, flag, bool(p.get(flag)), when))
        for flag in ("deactivated", "suspended")
    )


def _write_restriction(_id: str, p: dict, when: datetime) -> int:
    """moderation lists every standing user ``restrict`` / ``shadow`` (rule E11)."""
    action = p.get("action")
    if action not in readmodels.RESTRICTIONS:
        return 0
    return int(
        readmodels.set_restriction(p.get("account_id"), action, p.get("case_id"), True, when)
    )


WRITERS: dict[str, Callable[[str, dict, datetime], int]] = {
    "posts": _write_post,
    "friendships": _write_friendship,
    "follows": _write_follow,
    "blocks": _write_block,
    "groups": _write_group,
    "group-members": _write_member,
    "pages": _write_page,
    "accounts": _write_account,
    "restrictions": _write_restriction,
}

# What the owner no longer has: rows older than the scan's start that it did not write.
SWEEPS: dict[str, str] = {
    "posts": (
        "UPDATE intel_content_ref SET state = 'deleted', event_at = %(t)s "
        "WHERE state <> 'deleted' AND event_at < %(t)s"
    ),
    "friendships": (
        "UPDATE intel_friend_edge SET active = false, event_at = %(t)s "
        "WHERE active AND event_at < %(t)s"
    ),
    "follows": (
        "UPDATE follow_edge SET active = false, occurred_at = %(t)s "
        "WHERE active AND occurred_at < %(t)s"
    ),
    "blocks": (
        "UPDATE intel_block_pair SET "
        "low_blocks = low_blocks AND COALESCE(low_at >= %(t)s, false), "
        "high_blocks = high_blocks AND COALESCE(high_at >= %(t)s, false), "
        "low_at = CASE WHEN low_blocks AND COALESCE(low_at < %(t)s, true) THEN %(t)s "
        "ELSE low_at END, "
        "high_at = CASE WHEN high_blocks AND COALESCE(high_at < %(t)s, true) THEN %(t)s "
        "ELSE high_at END "
        "WHERE (low_blocks AND COALESCE(low_at < %(t)s, true)) "
        "OR (high_blocks AND COALESCE(high_at < %(t)s, true))"
    ),
    "groups": (
        "UPDATE intel_group_ref SET status = 'deleted', event_at = %(t)s "
        "WHERE status <> 'deleted' AND event_at < %(t)s"
    ),
    "group-members": (
        "UPDATE intel_group_membership SET state = 'none', role = '', notify_posts = false, "
        "joined_at = NULL, event_at = %(t)s WHERE state <> 'none' AND event_at < %(t)s"
    ),
    "pages": (
        "UPDATE intel_page_ref SET deleted = true, event_at = %(t)s "
        "WHERE NOT deleted AND event_at < %(t)s"
    ),
    # An author identity no longer lists is active again (its reactivation or
    # unsuspension was lost); a flag set at or after the scan's start stays.
    "accounts": (
        "UPDATE author_ref SET "
        "deactivated = deactivated AND COALESCE(deactivated_at >= %(t)s, false), "
        "suspended = suspended AND COALESCE(suspended_at >= %(t)s, false), "
        "deactivated_at = CASE WHEN deactivated AND COALESCE(deactivated_at < %(t)s, true) "
        "THEN %(t)s ELSE deactivated_at END, "
        "suspended_at = CASE WHEN suspended AND COALESCE(suspended_at < %(t)s, true) "
        "THEN %(t)s ELSE suspended_at END, "
        "active = NOT ((deactivated AND COALESCE(deactivated_at >= %(t)s, false)) "
        "OR (suspended AND COALESCE(suspended_at >= %(t)s, false))) "
        "WHERE NOT active AND ((deactivated AND COALESCE(deactivated_at < %(t)s, true)) "
        "OR (suspended AND COALESCE(suspended_at < %(t)s, true)))"
    ),
    # No restriction stands any more on an account moderation no longer lists
    # (its ``reinstate`` was lost).
    "restrictions": (
        "UPDATE intel_account_restriction SET active = false, event_at = %(t)s "
        "WHERE active AND event_at < %(t)s"
    ),
}

KINDS = tuple(WRITERS)


def run(
    kind: str,
    *,
    after: str | None = None,
    limit: int = 200,
    rate: float = 20.0,
    sweep: bool = True,
    fetch: Callable[..., Page] = fetch_page,
    progress: Callable[[Result], None] | None = None,
) -> Result:
    """Backfill one kind. ``sweep`` applies only to a complete scan from the start."""
    writer = WRITERS[kind]
    result = Result(kind)
    for page in pages(source(kind), after=after, limit=limit, rate=rate, fetch=fetch):
        if result.started is None:
            result.started = page.as_of
        with transaction.atomic():
            for item in page.items:
                result.items += 1
                result.written += writer(item["id"], item["payload"], page.as_of)
        result.pages += 1
        result.last_cursor = page.next
        if progress is not None:
            progress(result)
    result.complete = True
    if sweep and after is None and result.started is not None:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute(SWEEPS[kind], {"t": result.started})
            result.swept = cur.rowcount
    return result
