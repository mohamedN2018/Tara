"""Stage 2: one ``CandidateFeatures`` row per eligible candidate (02 section 6.2; WP 4.2).

Batched lookups only: one ``IN`` query per table, at most ``MAX_QUERIES`` for any
number of candidates, and **no cross-service call** (no graph ``mutual_count``,
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

MAX_QUERIES = 10


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


_CONTENT_SQL = """
SELECT c.post_id, c.type, c.lang, c.group_id, c.shared_post_id, c.bait_score,
       c.pending_reports, c.moderation_open,
       (c.dup_of IS NOT NULL AND o.post_id IS NOT NULL) AS duplicate,
       m.duration_ms, m.quality
FROM intel_content_ref c
LEFT JOIN intel_media_ref m ON m.media_id = c.media_ids[1]
LEFT JOIN intel_content_ref o ON o.post_id = c.dup_of AND o.state = 'live'
WHERE c.post_id = ANY(%s::uuid[])
"""
_STATS_SQL = """
SELECT post_id, reactions, comments, shares, flags FROM post_stats
WHERE post_id = ANY(%s::uuid[])
"""
_REACH_SQL = """
SELECT post_id, count(*) FROM feed_item WHERE post_id = ANY(%s::uuid[]) GROUP BY post_id
"""
_HIDES_SQL = """
SELECT post_id, count(*) FROM post_hide WHERE post_id = ANY(%s::uuid[]) GROUP BY post_id
"""
_COMMENTERS_SQL = """
SELECT post_id, count(DISTINCT author_id) FROM comment_state
WHERE active AND author_id IS NOT NULL AND post_id = ANY(%s::uuid[]) GROUP BY post_id
"""
_FAVORITES_SQL = """
SELECT target_id FROM relationship_flag
WHERE actor_id = %s AND kind = 'favorite' AND active AND target_id = ANY(%s::uuid[])
"""
_AFFINITY_SQL = """
SELECT author_id, interactions FROM affinity
WHERE account_id = %s AND author_id = ANY(%s::uuid[])
"""
_DISLIKES_SQL = """
SELECT author_id, count(*) FROM post_hide
WHERE account_id = %s AND author_id = ANY(%s::uuid[]) AND reason = ANY(%s)
GROUP BY author_id
"""
_SHARED_GROUPS_SQL = """
SELECT o.account_id, count(*) FROM intel_group_membership v
JOIN intel_group_membership o ON o.group_id = v.group_id AND o.state = 'active'
WHERE v.account_id = %s AND v.state = 'active' AND o.account_id = ANY(%s::uuid[])
GROUP BY o.account_id
"""
# Comments exchanged within the window, per direction (viewer -> author, author -> viewer).
_CONVERSATION_SQL = """
SELECT CASE WHEN author_id = %(v)s THEN post_author_id ELSE author_id END AS other,
       count(*) FILTER (WHERE author_id = %(v)s) AS mine,
       count(*) FILTER (WHERE post_author_id = %(v)s) AS theirs
FROM comment_state
WHERE active AND occurred_at >= %(since)s AND (
      (author_id = %(v)s AND post_author_id = ANY(%(a)s::uuid[]))
   OR (post_author_id = %(v)s AND author_id = ANY(%(a)s::uuid[])))
GROUP BY 1
"""


def build(
    viewer_id, candidates: Sequence[Candidate], cfg: SurfaceConfig, now: datetime
) -> list[CandidateFeatures]:
    """Features of ``candidates`` for ``viewer_id``, in the same order."""
    from feed import feedback

    if not candidates:
        return []
    viewer = str(viewer_id)
    posts = sorted({c.post_id for c in candidates})
    content = {str(r[0]): r for r in _fetch(_CONTENT_SQL, [posts])}
    # The viewer's own posts are included: today's ranking reads a self-dislike too.
    authors = sorted({c.author_id for c in candidates if c.author_id})
    stats = {str(r[0]): r for r in _fetch(_STATS_SQL, [posts])}
    reach = {str(p): n for p, n in _fetch(_REACH_SQL, [posts])}
    hides = {str(p): n for p, n in _fetch(_HIDES_SQL, [posts])}
    commenters = {str(p): n for p, n in _fetch(_COMMENTERS_SQL, [posts])}
    rel = cfg.section("relationship")
    if authors:
        favorites = {str(r[0]) for r in _fetch(_FAVORITES_SQL, [viewer, authors])}
        affinity = {str(a): n for a, n in _fetch(_AFFINITY_SQL, [viewer, authors])}
        dislikes = {
            str(a): n
            for a, n in _fetch(
                _DISLIKES_SQL,
                [viewer, authors, sorted(str(r) for r in feedback.AUTHOR_DOWNWEIGHT_REASONS)],
            )
        }
        shared = {str(a): n for a, n in _fetch(_SHARED_GROUPS_SQL, [viewer, authors])}
        since = now - timedelta(days=rel["conversation_days"])
        conversation = {
            str(o): math.log1p(min(mine, theirs))
            for o, mine, theirs in _fetch(
                _CONVERSATION_SQL, {"v": viewer, "a": authors, "since": since}
            )
            if o is not None
        }
    else:
        favorites, affinity, dislikes, shared, conversation = set(), {}, {}, {}, {}

    out = []
    for c in candidates:
        ref = content.get(c.post_id)
        st = stats.get(c.post_id)
        author = c.author_id or ""
        created = c.created_at
        age_h = max((now - created).total_seconds() / 3600.0, 0.0) if created else 0.0
        out.append(
            CandidateFeatures(
                post_id=c.post_id,
                author_id=c.author_id,
                source=c.source,
                reason=c.reason,
                tie_id=c.item_id or c.post_id,
                created_at=created,
                age_h=age_h,
                type=(ref[1] if ref and ref[1] else c.type) or "",
                lang=ref[2] if ref else "und",
                group_id=str(ref[3]) if ref and ref[3] else None,
                is_reshare=bool(ref and ref[4]),
                duplicate=bool(ref and ref[8]),
                bait_score=ref[5] if ref else None,
                pending_reports=int(ref[6]) if ref else 0,
                moderation_open=bool(ref and ref[7]),
                duration_ms=ref[9] if ref else None,
                media_quality=ref[10] if ref and ref[9] is not None else None,
                has_stats=st is not None,
                reactions=max(st[1], 0) if st else 0,
                comments=max(st[2], 0) if st else 0,
                shares=max(st[3], 0) if st else 0,
                flags=max(st[4], 0) if st else 0,
                stored_score=c.stored_score,
                reach=int(reach.get(c.post_id, 0)),
                hides=int(hides.get(c.post_id, 0)),
                commenters=int(commenters.get(c.post_id, 0)),
                favorite=author in favorites,
                affinity=int(affinity.get(author, 0)),
                author_dislikes=int(dislikes.get(author, 0)),
                shared_groups=0 if author == viewer else int(shared.get(author, 0)),
                conversation=0.0 if author == viewer else conversation.get(author, 0.0),
            )
        )
    return out
