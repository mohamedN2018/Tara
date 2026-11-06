"""Stage 2: one ``CandidateFeatures`` row per eligible candidate (02 section 6.2; WP 4.2).

Batched lookups only: ``MAX_QUERIES`` statements for any number of candidates (R3
WP A8: one per-post statement and one viewer x author statement, each joining the
tables below), and **no cross-service call** (no graph ``mutual_count``,
02 section 6.2). Everything comes from ``feed_db``:

====================  ==========================================================
content               ``intel_content_ref`` + ``intel_media_ref`` (first media) +
                      the live original a duplicate points at
engagement            ``post_stats`` (reactions, comments, shares, spam/sexual flags)
reach                 fan-out recipients (``feed_item`` rows per post): the only
                      honest denominator before impressions are aggregated
                      (WP 6.3), which is why the predictor outputs are scores
hides                 ``post_hide`` rows per post
discussion            distinct live commenters per post (``comment_state``)
viewer x author       favorites, ``affinity`` interactions, the viewer's
                      ``dislike_creator`` / ``annoying`` hides, shared active
                      groups, comments exchanged both ways in
                      ``relationship.conversation_days``
====================  ==========================================================

``interest_rel`` is 0 for everyone until the interest profile exists (phase 6):
nothing is inferred before then. Saves, completions and watch time have no
aggregated counts yet either, so the predictor falls back to its configured priors
for them (a cold item scores its prior), never to an invented number.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import connection

from ..config import SurfaceConfig
from ..retrieval.sources import Candidate

MAX_QUERIES = 2


@dataclass(frozen=True)
class CandidateFeatures:
    post_id: str
    author_id: str | None
    source: str
    reason: str
    tie_id: str  # the FeedItem id for a connection row (today's tie-break), else the post id
    created_at: datetime | None
    age_h: float
    type: str
    lang: str
    group_id: str | None
    is_reshare: bool
    # integrity
    duplicate: bool
    bait_score: float | None
    pending_reports: int
    moderation_open: bool
    # media (first video media)
    duration_ms: int | None
    media_quality: float | None
    # engagement
    has_stats: bool
    reactions: int
    comments: int
    shares: int
    flags: int
    stored_score: float | None
    reach: int
    hides: int
    commenters: int
    # viewer x author
    favorite: bool
    affinity: int
    author_dislikes: int
    shared_groups: int
    conversation: float
    # viewer x content (phase 6)
    interest_rel: float = 0.0
    # R3: the durable exposure (``intel_user_item_engagement``); only under a version
    # carrying ``rotation`` (``build(..., exposure=...)``), else the defaults.
    exp_state: int | None = None
    exp_last_at: datetime | None = None
    exp_visits: int = 0

    @property
    def discussion_depth(self) -> float:
        return math.log1p(self.commenters)

    def as_vector(self) -> list[float]:
        """The numeric features in a fixed order (the ML input of phase 11)."""
        return [
            self.age_h,
            float(self.is_reshare),
            float(self.duplicate),
            self.bait_score or 0.0,
            float(self.pending_reports),
            float(self.reactions),
            float(self.comments),
            float(self.shares),
            float(self.flags),
            float(self.reach),
            float(self.hides),
            self.discussion_depth,
            float(self.favorite),
            math.log1p(self.affinity),
            float(self.author_dislikes),
            float(self.shared_groups),
            self.conversation,
            self.interest_rel,
        ]


def _fetch(sql: str, params) -> list[tuple]:
    with connection.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


# Per post, one statement (R3 WP A8: was five): content (+ first media, + the live
# original a duplicate points at), post_stats, fan-out reach, hides and distinct live
# commenters. The aggregates read the same indexes the separate queries did.
_POSTS_SQL = """
WITH p AS (SELECT DISTINCT unnest(%(posts)s::uuid[]) AS post_id)
SELECT p.post_id, c.post_id IS NOT NULL AS has_ref,
       c.type, c.lang, c.group_id, c.shared_post_id, c.bait_score,
       c.pending_reports, c.moderation_open,
       (c.dup_of IS NOT NULL AND o.post_id IS NOT NULL) AS duplicate,
       m.duration_ms, m.quality,
       s.post_id IS NOT NULL AS has_stats, s.reactions, s.comments, s.shares, s.flags,
       coalesce(r.n, 0), coalesce(h.n, 0), coalesce(k.n, 0)
FROM p
LEFT JOIN intel_content_ref c ON c.post_id = p.post_id
LEFT JOIN intel_media_ref m ON m.media_id = c.media_ids[1]
LEFT JOIN intel_content_ref o ON o.post_id = c.dup_of AND o.state = 'live'
LEFT JOIN post_stats s ON s.post_id = p.post_id
LEFT JOIN (SELECT post_id, count(*) AS n FROM feed_item
           WHERE post_id = ANY(%(posts)s::uuid[]) GROUP BY post_id) r ON r.post_id = p.post_id
LEFT JOIN (SELECT post_id, count(*) AS n FROM post_hide
           WHERE post_id = ANY(%(posts)s::uuid[]) GROUP BY post_id) h ON h.post_id = p.post_id
LEFT JOIN (SELECT post_id, count(DISTINCT author_id) AS n FROM comment_state
           WHERE active AND author_id IS NOT NULL AND post_id = ANY(%(posts)s::uuid[])
           GROUP BY post_id) k ON k.post_id = p.post_id
"""
# R3 (06 section 5.2, WP 4b.5): the durable half of the exposure ledger rides in the
# same statement (the "seen_before" read: +0 queries): the viewer's engagement state
# in any weekly partition. (The conversation exception's commenter count is a
# separate, small read of the demoted items only: ``exposure_rank.new_commenters``;
# a correlated count here made the planner's estimate large enough to JIT-compile
# the whole statement, about 0.5 s.)
_EXPOSURE_POSTS_SQL = (
    _POSTS_SQL.replace(
        "WITH p AS (SELECT DISTINCT unnest(%(posts)s::uuid[]) AS post_id)",
        """WITH p AS (SELECT DISTINCT unnest(%(posts)s::uuid[]) AS post_id),
e AS (
    SELECT item_id, max(state) AS state, max(last_displayed_at) AS last_at,
           max(visits) AS visits
    FROM intel_user_item_engagement
    WHERE account_id = %(v)s AND item_id = ANY(%(posts)s::uuid[]) AND state IS NOT NULL
    GROUP BY item_id)""",
    )
    .replace(
        "coalesce(r.n, 0), coalesce(h.n, 0), coalesce(k.n, 0)",
        "coalesce(r.n, 0), coalesce(h.n, 0), coalesce(k.n, 0), e.state, e.last_at,"
        " coalesce(e.visits, 0)",
    )
    .replace(
        "LEFT JOIN post_stats s ON s.post_id = p.post_id",
        "LEFT JOIN post_stats s ON s.post_id = p.post_id LEFT JOIN e ON e.item_id = p.post_id",
    )
)
# Viewer x author, one statement (was five): favorites, affinity, the viewer's creator
# dislikes, shared active groups, and comments exchanged each way in the window.
# Rows are (kind, author, x, y).
_AUTHORS_SQL = """
SELECT 'favorite', target_id, 0::bigint, 0::bigint FROM relationship_flag
WHERE actor_id = %(v)s AND kind = 'favorite' AND active AND target_id = ANY(%(a)s::uuid[])
UNION ALL
SELECT 'affinity', author_id, interactions::bigint, 0::bigint FROM affinity
WHERE account_id = %(v)s AND author_id = ANY(%(a)s::uuid[])
UNION ALL
SELECT 'dislike', author_id, count(*), 0::bigint FROM post_hide
WHERE account_id = %(v)s AND author_id = ANY(%(a)s::uuid[]) AND reason = ANY(%(reasons)s)
GROUP BY author_id
UNION ALL
SELECT 'shared', o.account_id, count(*), 0::bigint FROM intel_group_membership v
JOIN intel_group_membership o ON o.group_id = v.group_id AND o.state = 'active'
WHERE v.account_id = %(v)s AND v.state = 'active' AND o.account_id = ANY(%(a)s::uuid[])
GROUP BY o.account_id
UNION ALL
SELECT 'conversation',
       CASE WHEN author_id = %(v)s THEN post_author_id ELSE author_id END,
       count(*) FILTER (WHERE author_id = %(v)s),
       count(*) FILTER (WHERE post_author_id = %(v)s)
FROM comment_state
WHERE active AND occurred_at >= %(since)s AND (
      (author_id = %(v)s AND post_author_id = ANY(%(a)s::uuid[]))
   OR (post_author_id = %(v)s AND author_id = ANY(%(a)s::uuid[])))
GROUP BY 2
"""


def build(
    viewer_id,
    candidates: Sequence[Candidate],
    cfg: SurfaceConfig,
    now: datetime,
    exposure: dict | None = None,
) -> list[CandidateFeatures]:
    """Features of ``candidates`` for ``viewer_id``, in the same order. Two queries.

    ``exposure`` (R3, a version carrying ``rotation``): any dict (the hot-ledger minutes
    by post); the durable exposure columns are then read in the same per-post
    statement."""
    from feed import feedback

    if not candidates:
        return []
    viewer = str(viewer_id)
    posts = sorted({c.post_id for c in candidates})
    if exposure is None:
        rows = _fetch(_POSTS_SQL, {"posts": posts})
    else:
        rows = _fetch(_EXPOSURE_POSTS_SQL, {"v": viewer, "posts": posts})
    per_post = {str(r[0]): r for r in rows}
    # The viewer's own posts are included: today's ranking reads a self-dislike too.
    authors = sorted({c.author_id for c in candidates if c.author_id})
    rel = cfg.section("relationship")
    favorites: set[str] = set()
    affinity: dict[str, int] = {}
    dislikes: dict[str, int] = {}
    shared: dict[str, int] = {}
    conversation: dict[str, float] = {}
    if authors:
        for kind, author, x, y in _fetch(
            _AUTHORS_SQL,
            {
                "v": viewer,
                "a": authors,
                "reasons": sorted(str(r) for r in feedback.AUTHOR_DOWNWEIGHT_REASONS),
                "since": now - timedelta(days=rel["conversation_days"]),
            },
        ):
            if author is None:
                continue
            key = str(author)
            if kind == "favorite":
                favorites.add(key)
            elif kind == "affinity":
                affinity[key] = int(x)
            elif kind == "dislike":
                dislikes[key] = int(x)
            elif kind == "shared":
                shared[key] = int(x)
            else:
                conversation[key] = math.log1p(min(int(x), int(y)))

    out = []
    for c in candidates:
        row = per_post.get(c.post_id)
        ref = row if row is not None and row[1] else None
        has_stats = bool(row is not None and row[12])
        author = c.author_id or ""
        created = c.created_at
        age_h = max((now - created).total_seconds() / 3600.0, 0.0) if created else 0.0
        extra = {}
        if exposure is not None and row is not None:
            extra = {
                "exp_state": None if row[20] is None else int(row[20]),
                "exp_last_at": row[21],
                "exp_visits": int(row[22] or 0),
            }
        out.append(
            CandidateFeatures(
                post_id=c.post_id,
                author_id=c.author_id,
                source=c.source,
                reason=c.reason,
                tie_id=c.item_id or c.post_id,
                created_at=created,
                age_h=age_h,
                type=(ref[2] if ref and ref[2] else c.type) or "",
                lang=ref[3] if ref else "und",
                group_id=str(ref[4]) if ref and ref[4] else None,
                is_reshare=bool(ref and ref[5]),
                duplicate=bool(ref and ref[9]),
                bait_score=ref[6] if ref else None,
                pending_reports=int(ref[7]) if ref else 0,
                moderation_open=bool(ref and ref[8]),
                duration_ms=ref[10] if ref else None,
                media_quality=ref[11] if ref and ref[10] is not None else None,
                has_stats=has_stats,
                reactions=max(row[13], 0) if has_stats else 0,
                comments=max(row[14], 0) if has_stats else 0,
                shares=max(row[15], 0) if has_stats else 0,
                flags=max(row[16], 0) if has_stats else 0,
                stored_score=c.stored_score,
                reach=int(row[17]) if row is not None else 0,
                hides=int(row[18]) if row is not None else 0,
                commenters=int(row[19]) if row is not None else 0,
                favorite=author in favorites,
                affinity=int(affinity.get(author, 0)),
                author_dislikes=int(dislikes.get(author, 0)),
                shared_groups=0 if author == viewer else int(shared.get(author, 0)),
                conversation=0.0 if author == viewer else conversation.get(author, 0.0),
                **extra,
            )
        )
    return out
