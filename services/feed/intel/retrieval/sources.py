"""Candidate sources (02 section 6.1; WP 3.4).

Each source returns ids with a ``source`` and a ``reason``, newest first, capped by
its ``window.<source>`` config. Sources only find content; they never decide who may
see it: every candidate still passes ``intel.eligibility`` (fail closed), and post's
hydration re-checks it again (WP 3.6).

- ``connections``: the viewer's own fan-out rows (audience-checked at fan-out).
- ``follow_pull``: (a) posts whose fan-out was cut at ``FANOUT_MAX_RECIPIENTS``
  (``intel_fanout_capped``, D2) by authors the viewer follows or is friends with;
  (b) the last ``retrieval.new_follow_days`` of posts by authors followed (or
  friended) in the last ``retrieval.new_follow_hours`` (D3).
- ``groups``: approved posts of the groups the viewer is an active member of (D1).
- ``reels`` / ``video``: public reels or videos of the last ``pools.window_days``
  (the precomputed discovery pools of WP 9.1 replace these scans).

**No pulled item duplicates a feed row the viewer already has**: every non-connection
source excludes the viewer's ``feed_item`` post ids in the same query.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from django.db import connection

from .. import ports
from ..config import SurfaceConfig

CONNECTIONS = "connections"
FOLLOW_PULL = "follow_pull"
GROUPS = "groups"
REELS = "reels"
VIDEO = "video"


@dataclass(frozen=True)
class Candidate:
    post_id: str
    author_id: str | None
    source: str
    reason: str
    created_at: datetime | None
    type: str = ""
    # Connections only: the viewer's ``FeedItem`` (its id breaks ranking ties exactly
    # as ``feed/ranking.py`` did, its stored score is the engagement fallback).
    item_id: str | None = None
    stored_score: float | None = None


def _rows(sql: str, params: dict) -> list[tuple]:
    with connection.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def _candidates(rows, source: str) -> list[Candidate]:
    return [
        Candidate(str(pid), str(author) if author else None, source, reason, created, kind or "")
        for pid, author, created, kind, reason in rows
    ]


# Every query below excludes the viewer's own fan-out rows (``NOT EXISTS feed_item``):
# a pulled item never duplicates one, hidden or not.


def connections(viewer_id, cfg: SurfaceConfig, types: tuple[str, ...] | None = None):
    limit = cfg.get(f"window.{CONNECTIONS}" if types is None else f"window.{cfg.surface}")
    return [
        Candidate(
            r["post_id"],
            r["author_id"],
            CONNECTIONS,
            r["reason"],
            r["post_created_at"],
            r["type"],
            item_id=r.get("id"),
            stored_score=r.get("score"),
        )
        for r in ports.connection_rows(viewer_id, limit, types)
    ]


_CAPPED_SQL = """
SELECT f.post_id, f.author_id, f.created_at, c.type, 'capped'
FROM intel_fanout_capped f LEFT JOIN intel_content_ref c ON c.post_id = f.post_id
WHERE f.author_id = ANY(%(authors)s::uuid[]) AND f.created_at >= %(since)s
  AND f.author_id <> %(viewer)s
  AND NOT EXISTS (SELECT 1 FROM feed_item i
                  WHERE i.recipient_id = %(viewer)s AND i.post_id = f.post_id)
ORDER BY f.created_at DESC, f.post_id LIMIT %(limit)s
"""

_NEW_FOLLOW_SQL = """
SELECT c.post_id, c.author_id, c.created_at, c.type, 'new_follow'
FROM intel_content_ref c
WHERE c.author_id = ANY(%(authors)s::uuid[]) AND c.state = 'live'
  AND c.created_at >= %(since)s
  AND NOT EXISTS (SELECT 1 FROM feed_item i
                  WHERE i.recipient_id = %(viewer)s AND i.post_id = c.post_id)
ORDER BY c.created_at DESC, c.post_id LIMIT %(limit)s
"""


# R3 WP A8: the whole follow pull in one statement (was five: follows, friends, the
# capped posts, then recent follows and friends and their posts). Capped rows come
# first so the dedupe below keeps their reason, as before.
_FOLLOW_PULL_SQL = f"""
WITH conn AS (
    SELECT target_id AS id, occurred_at AS at FROM follow_edge
    WHERE follower_id = %(viewer)s AND active
    UNION ALL
    SELECT friend_id, since FROM intel_friend_edge WHERE account_id = %(viewer)s AND active),
capped AS ({_CAPPED_SQL.replace("ANY(%(authors)s::uuid[])", "ANY(ARRAY(SELECT id FROM conn))")}),
fresh AS ({
    _NEW_FOLLOW_SQL.replace(
        "ANY(%(authors)s::uuid[])",
        "ANY(ARRAY(SELECT id FROM conn WHERE at >= %(recent)s AND id <> %(viewer)s))",
    ).replace("%(since)s", "%(new_since)s")
})
SELECT *, 1 FROM capped
UNION ALL
SELECT *, 2 FROM fresh
ORDER BY 6
"""  # noqa: S608 - built from the constants above; every value is a bound parameter


def follow_pull(viewer_id, cfg: SurfaceConfig, now: datetime) -> list[Candidate]:
    limit = cfg.get(f"window.{FOLLOW_PULL}")
    r = cfg.section("retrieval")
    rows = _rows(
        _FOLLOW_PULL_SQL,
        {
            "viewer": str(viewer_id),
            "since": now - timedelta(days=r["capped_days"]),
            "recent": now - timedelta(hours=r["new_follow_hours"]),
            "new_since": now - timedelta(days=r["new_follow_days"]),
            "limit": limit,
        },
    )
    out = _candidates([row[:5] for row in rows], FOLLOW_PULL)
    return _newest(_dedupe(out), limit)


_GROUPS_SQL = """
SELECT c.post_id, c.author_id, c.created_at, c.type,
       CASE WHEN m.notify_posts THEN 'group_notify' ELSE 'group' END
FROM intel_group_membership m
JOIN intel_content_ref c ON c.group_id = m.group_id
WHERE m.account_id = %(viewer)s AND m.state = 'active'
  AND c.state = 'live' AND c.approval_state = 'approved' AND c.created_at >= %(since)s
 
  AND NOT EXISTS (SELECT 1 FROM feed_item i
                  WHERE i.recipient_id = %(viewer)s AND i.post_id = c.post_id)
ORDER BY c.created_at DESC, c.post_id LIMIT %(limit)s
"""


def groups(viewer_id, cfg: SurfaceConfig, now: datetime) -> list[Candidate]:
    return _candidates(
        _rows(
            _GROUPS_SQL,
            {
                "viewer": str(viewer_id),
                "since": now - timedelta(days=cfg.get("retrieval.groups_days")),
                "limit": cfg.get(f"window.{GROUPS}"),
            },
        ),
        GROUPS,
    )


# Public, non-group items of one type (``intel_cref_public_idx``). A reel's first
# media must fit the reels format when ``intel_media_ref`` knows it; an unknown
# media is left to post (reels are length-checked at upload).
_PUBLIC_SQL = """
SELECT c.post_id, c.author_id, c.created_at, c.type, 'public'
FROM intel_content_ref c
LEFT JOIN intel_media_ref m ON m.media_id = c.media_ids[1]
WHERE c.type = %(type)s AND c.audience = 'public' AND c.group_id IS NULL
  AND c.state = 'live' AND c.created_at >= %(since)s AND c.author_id <> %(viewer)s
 
  AND NOT EXISTS (SELECT 1 FROM feed_item i
                  WHERE i.recipient_id = %(viewer)s AND i.post_id = c.post_id)
  AND (m.media_id IS NULL OR (
        (%(max_ms)s::int IS NULL OR m.duration_ms IS NULL OR m.duration_ms <= %(max_ms)s::int)
    AND (NOT %(portrait)s OR m.width IS NULL OR m.height IS NULL OR m.height >= m.width)))
ORDER BY c.created_at DESC, c.post_id LIMIT %(limit)s
"""


def public_pool(
    viewer_id, cfg: SurfaceConfig, now: datetime, kind: str, limit: int
) -> list[Candidate]:
    retrieval = cfg.section("retrieval") if kind == "reel" else {}
    return _candidates(
        _rows(
            _PUBLIC_SQL,
            {
                "type": kind,
                "since": now - timedelta(days=cfg.get("pools.window_days")),
                "viewer": str(viewer_id),
                "limit": max(limit, 0),
                "max_ms": retrieval.get("max_duration_ms"),
                "portrait": bool(retrieval.get("require_portrait", False)),
            },
        ),
        REELS if kind == "reel" else VIDEO,
    )


def _dedupe(items: list[Candidate]) -> list[Candidate]:
    seen: set[str] = set()
    out = []
    for c in items:
        if c.post_id not in seen:
            seen.add(c.post_id)
            out.append(c)
    return out


def _newest(items: list[Candidate], limit: int) -> list[Candidate]:
    epoch = datetime.min.replace(tzinfo=UTC)
    return sorted(items, key=lambda c: (c.created_at or epoch, c.post_id), reverse=True)[:limit]
