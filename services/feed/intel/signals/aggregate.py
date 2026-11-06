"""The engagement aggregator v0 (07 WP 4b.13, pulled forward from WP 6.3).

Every 60 s (beat ``intel.aggregate_engagement``) it fills **only**
``intel_user_item_engagement`` from ``intel_signal_event``: per (viewer, item) the
impressions, opens, completions and ``max_watch_ms``, and the exposure columns of
06 section 13: ``dwell_ms``, ``state``, ``consumed_dwell_only``,
``last_displayed_at`` and ``visits``. It is the durable half of the exposure ledger
(06 section 5.2): once the 36 h ``feed:exp`` record expires, the ranker still knows
that an item was consumed, so it does not come back at ``m = 1``.

**Idempotent by construction.** A run finds the (viewer, item) pairs that received
events in its window and recomputes each pair from *all* its retained events, so
re-running a window, overlapping windows or a lost watermark change nothing. Natural
keys dedupe what a client could repeat: impressions and opens count distinct client
sessions, a ``feed_dwell`` counts once per (session, item) (its longest report), a
completion once per (session, play). ``first_at`` is the pair's first retained event,
so the row key is stable; a row whose ``first_at`` moved (its oldest events aged out)
is replaced, never duplicated.

**What it skips** (fail closed): accounts with ``personalization_off`` (decision 24),
events before the account's ``reset_at`` (when the column exists, 07 WP 8.4-B2),
synthetic and test actors unless ``INTEL_SYNTHETIC_IN_RANKING`` is on (dev only).

States (06 section 5.1, ``intel.exposure``): the highest per pair. A ``feed_dwell`` is
classified with the Home config's ``exposure`` thresholds, its consumed threshold being
the one ingest stored with the row (``duration_ms``: scaled by the excerpt length),
else ``exposure.consumed_dwell_ms``. Likes, comments, shares and saves (bus rows) and
video completions are consumption that is not dwell-only. WP 6.3 later extends this
same job (interests, affinity, post stats) instead of writing a second one: R4's
interest tiers run here (``interests_agg``), after the engagement pass.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import connection, transaction

from .. import exposure
from ..models import EventType, ItemType
from . import partitions

logger = logging.getLogger("tara.intel.aggregate")

WATERMARK_KEY = "intel:agg:engagement:hi"
# A window starts this long before the previous one ended, so a batch whose
# transaction committed late is still seen (re-reading is free: runs are idempotent).
OVERLAP = timedelta(minutes=2)
_SMALLINT = 32_767

KINDS = (ItemType.POST, ItemType.REEL, ItemType.VIDEO)
DISPLAY = (EventType.FEED_IMPRESSION, EventType.VIDEO_START, EventType.VIDEO_PROGRESS)
SKIP = (EventType.VIDEO_SKIP,)
VIEW = (EventType.POST_OPEN, EventType.REEL_VIEW)
CONSUME = (
    EventType.VIDEO_COMPLETE,
    EventType.VIDEO_REWATCH,
    EventType.POST_LIKE,
    EventType.POST_COMMENT,
    EventType.POST_SHARE,
    EventType.POST_SAVE,
)
TYPES = (*DISPLAY, *SKIP, *VIEW, *CONSUME, EventType.FEED_DWELL)
WATCH = (EventType.VIDEO_PROGRESS, EventType.VIDEO_COMPLETE, EventType.VIDEO_SKIP)

_reset_column: bool | None = None


def _has_reset_at() -> bool:
    global _reset_column
    if _reset_column is None:
        with connection.cursor() as cur:
            cur.execute(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'intel_user_preference' AND column_name = 'reset_at')"
            )
            _reset_column = bool(cur.fetchone()[0])
    return _reset_column


def _sql(reset: bool) -> str:
    reset_join = "AND (p.reset_at IS NULL OR e.received_at >= p.reset_at)" if reset else ""
    return f"""
WITH touched AS (
    SELECT DISTINCT e.account_id, e.item_id
    FROM intel_signal_event e
    WHERE e.received_at > %(lo)s AND e.received_at <= %(hi)s
      AND e.item_type = ANY(%(kinds)s) AND e.event_type = ANY(%(types)s)
      AND (%(synthetic)s OR e.data_origin = 'real')
),
ev AS (
    SELECT e.account_id, e.item_id, e.item_type, e.event_type, e.session_id,
           e.play_index, e.watch_ms, e.duration_ms, e.received_at, e.data_origin,
           CASE
             WHEN e.event_type = ANY(%(consume)s) THEN 3
             WHEN e.event_type = ANY(%(view)s) THEN 2
             WHEN e.event_type = ANY(%(skip)s) THEN 1
             WHEN e.event_type = 'feed_dwell' THEN CASE
               WHEN e.watch_ms >= COALESCE(e.duration_ms, %(consumed_ms)s) THEN 3
               WHEN e.watch_ms >= %(viewed_ms)s THEN 2
               WHEN e.watch_ms < %(skip_ms)s THEN 1
               ELSE 0 END
             ELSE 0
           END AS st
    FROM intel_signal_event e
    JOIN touched t ON t.account_id = e.account_id AND t.item_id = e.item_id
    LEFT JOIN intel_user_preference p ON p.account_id = e.account_id
    WHERE e.received_at >= %(oldest)s AND e.received_at <= %(hi)s
      AND e.item_type = ANY(%(kinds)s) AND e.event_type = ANY(%(types)s)
      AND (%(synthetic)s OR e.data_origin = 'real')
      AND NOT COALESCE(p.personalization_off, false)
      {reset_join}
),
dwell AS (
    SELECT account_id, item_id, session_id, max(watch_ms) AS ms
    FROM ev WHERE event_type = 'feed_dwell' AND watch_ms IS NOT NULL
    GROUP BY account_id, item_id, session_id
),
dwell_sum AS (
    SELECT account_id, item_id, sum(ms) AS ms FROM dwell GROUP BY account_id, item_id
)
SELECT ev.account_id, ev.item_id,
       (array_agg(ev.item_type ORDER BY ev.received_at))[1],
       count(DISTINCT ev.session_id) FILTER (WHERE ev.event_type = 'feed_impression'),
       count(DISTINCT ev.session_id) FILTER (WHERE ev.event_type = 'post_open'),
       COALESCE(max(ev.watch_ms) FILTER (WHERE ev.event_type = ANY(%(watch)s)), 0),
       count(DISTINCT (ev.session_id, ev.play_index))
         FILTER (WHERE ev.event_type = 'video_complete'),
       min(ev.received_at), max(ev.received_at), max(ev.data_origin),
       COALESCE(max(ds.ms), 0),
       max(ev.st),
       bool_or(ev.st = 3 AND ev.event_type <> 'feed_dwell'),
       max(ev.received_at) FILTER (WHERE ev.session_id IS NOT NULL),
       count(DISTINCT ev.session_id)
FROM ev LEFT JOIN dwell_sum ds ON ds.account_id = ev.account_id AND ds.item_id = ev.item_id
GROUP BY ev.account_id, ev.item_id
"""  # noqa: S608 - only the fixed reset clause is interpolated


_UPSERT = """
INSERT INTO intel_user_item_engagement (
    account_id, item_id, item_type, impressions, opens, max_watch_ms, completions,
    first_at, last_at, data_origin, dwell_ms, state, consumed_dwell_only,
    last_displayed_at, visits)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (account_id, item_id, first_at) DO UPDATE SET
    item_type = EXCLUDED.item_type, impressions = EXCLUDED.impressions,
    opens = EXCLUDED.opens, max_watch_ms = EXCLUDED.max_watch_ms,
    completions = EXCLUDED.completions, last_at = EXCLUDED.last_at,
    data_origin = EXCLUDED.data_origin, dwell_ms = EXCLUDED.dwell_ms,
    state = EXCLUDED.state, consumed_dwell_only = EXCLUDED.consumed_dwell_only,
    last_displayed_at = EXCLUDED.last_displayed_at, visits = EXCLUDED.visits
"""


def _small(n) -> int:
    return min(int(n or 0), _SMALLINT)


def aggregate(lo: datetime, hi: datetime, *, cfg=None) -> dict:
    """Recompute every (viewer, item) pair with events received in ``(lo, hi]``."""
    th = exposure.thresholds(cfg)
    oldest = max(
        partitions.oldest_kept(partitions.SIGNALS, hi),
        partitions.oldest_kept(partitions.ENGAGEMENT, hi),
    )
    params = {
        "lo": lo,
        "hi": hi,
        "oldest": oldest,
        "kinds": [str(k) for k in KINDS],
        "types": [str(t) for t in TYPES],
        "consume": [str(t) for t in CONSUME],
        "view": [str(t) for t in VIEW],
        "skip": [str(t) for t in SKIP],
        "watch": [str(t) for t in WATCH],
        "consumed_ms": th.consumed_dwell_ms,
        "viewed_ms": th.viewed_dwell_ms,
        "skip_ms": th.skip_dwell_ms,
        "synthetic": bool(settings.INTEL_SYNTHETIC_IN_RANKING),
    }
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute(_sql(_has_reset_at()), params)
        rows = cur.fetchall()
        for day in {r[7].astimezone(UTC).date() for r in rows}:
            partitions.ensure(partitions.ENGAGEMENT, day)
        for r in rows:
            (account, item, kind, imps, opens, watch, completes, first, last, origin,
             dwell_ms, state, other_consumed, displayed_at, visits) = r  # fmt: skip
            # A pair keeps one row: drop it where its first event moved (aged out).
            cur.execute(
                "DELETE FROM intel_user_item_engagement "
                "WHERE account_id = %s AND item_id = %s AND first_at <> %s",
                [account, item, first],
            )
            cur.execute(
                _UPSERT,
                [
                    account,
                    item,
                    kind,
                    _small(imps),
                    _small(opens),
                    int(watch or 0),
                    _small(completes),
                    first,
                    last,
                    origin,
                    min(int(dwell_ms or 0), 2**31 - 1),
                    state,
                    state == exposure.STATE_CONSUMED and not other_consumed,
                    displayed_at,
                    _small(visits),
                ],
            )
    return {"pairs": len(rows), "lo": lo.isoformat(), "hi": hi.isoformat()}


def run(now: datetime | None = None, *, cfg=None) -> dict:
    """One beat tick: the window since the last run (minus the overlap). With no
    watermark (first run, cache flushed) the whole retained range: still idempotent."""
    hi = now or datetime.now(UTC)
    stored = cache.get(WATERMARK_KEY)
    if isinstance(stored, (int, float)):
        lo = datetime.fromtimestamp(stored, UTC) - OVERLAP
    else:
        lo = partitions.oldest_kept(partitions.SIGNALS, hi)
    out = aggregate(lo, hi, cfg=cfg)
    cache.set(WATERMARK_KEY, hi.timestamp(), timeout=None)
    # R4 WP 6.3: the interest tiers, in the same job (exactly once, own watermark).
    from .. import config
    from . import interests_agg

    out.update(interests_agg.aggregate(hi, OVERLAP, cfg or config.for_surface("home")))
    return out
