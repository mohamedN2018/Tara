"""Exposure-aware ranking of ``for_you`` first pages (06 sections 5.3, 5.4, 6.2; 07 WP
4b.5 and 4b.7; R3).

Applies **only under a version that carries ``rotation``** (``schema.exposure_ranking``:
``home@2c`` and its arms); every older version ranks exactly as before.

- **Exposure multiplier.** ``m = 1 − (1 − m0[state]) · 2^(−Δt / h[state])``, then
  ``m := m^min(exposures, max_exposures)``, with ``in_visit_m0`` when the item was
  displayed during the current visit. ``score' = score · m`` before the mix and the
  diversity re-ranker. The state comes from the hot ledger (``feed:exp``, folded by
  ``intel.exposure.fold``) and from ``intel_user_item_engagement`` for what the 36 h
  hot window no longer holds. An item that was only **retrieved** (served, never
  displayed) has no state and keeps ``m = 1``: the serve path never writes the
  ledger, so "fetched is not seen".
- **Carry-over.** An item of the previous first page (``feed:head``) that was never
  displayed has no state: it keeps its full score and is offered again first. It is
  counted (``carry_over``), never boosted beyond its own score.
- **Conversation exception** (``rec_new_activity``): at least ``revisit.new_comments``
  distinct, non-suspect commenters (not the author, not the viewer, not restricted,
  not a synthetic actor unless ``INTEL_SYNTHETIC_IN_RANKING``) since the viewer's last
  display lift ``m`` to ``revisit.min_m``.
- **New since your last visit.** Non-recommended items created after ``since`` (the
  previous visit's start) gain ``boost · score`` (``session.new_since.boost``), the
  best ``max_items`` of them (``lapsed_max_items`` for a lapsed visit), reason code
  ``new_since_visit``.
- **Relevance floor.** The first ``rotation.floor_slots`` slots take only items with
  ``score' ≥ rotation.floor ×`` the ``rotation.floor_pct`` percentile of the
  pre-multiplier scores; when too few pass, the best seen items (pre-multiplier score
  above the floor) fill them, never low-quality filler. Applied inside the first
  re-ranked page only, so page membership and the diversity caps do not move.

Every number is a config key (decision 20).
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from .. import exposure, hot
from ..config import SurfaceConfig, schema
from .scorer import Scored

STATE_NAMES = {
    exposure.STATE_DISPLAYED: "displayed",
    exposure.STATE_SKIPPED: "skipped",
    exposure.STATE_VIEWED: "viewed",
    exposure.STATE_CONSUMED: "consumed",
}
NEW_SINCE_REASON = "new_since_visit"
NEW_ACTIVITY_REASON = "rec_new_activity"


def applies(cfg: SurfaceConfig) -> bool:
    return schema.exposure_ranking(cfg.params)


def prefix(post_id) -> bytes:
    return uuid.UUID(str(post_id)).bytes[:8]


# ---- the hot reads of a first page, one round trip -------------------------------------


@dataclass
class HotState:
    """What one pipelined round trip read from redis-hot (None: not asked or unreadable)."""

    visit: dict | None = None  # decoded ``feed:sess`` (``{}`` when absent)
    ledger: bytes | None = None
    head: bytes | None = None
    pools: list | None = None
    ok: bool = True
    # R4: the interest profile cache ``intel:prof`` and the session vector ``feed:si``.
    prof: bytes | None = None
    si: dict | None = None


def prefetch(
    viewer_id,
    cfg: SurfaceConfig,
    *,
    visit: bool,
    ledger: bool,
    head: bool,
    pools: bool,
    prof: bool = False,
    si: bool = False,
) -> HotState:
    """``HGETALL feed:sess``, ``GET feed:exp``, ``GET feed:head:home`` and the pool
    ``ZREVRANGE``s in **one** pipelined round trip (07 "Query and Redis budget")."""
    from .. import discovery, session_ctx

    state = HotState()
    client = hot.raw_client()
    if client is None or not (visit or ledger or head or pools or prof or si):
        state.ok = client is not None
        return state
    backend = hot.hot()
    plan = []
    try:
        pipe = client.pipeline(transaction=False)
        if visit:
            pipe.hgetall(backend.make_key(hot.visit_key(viewer_id)))
            plan.append(("visit", 1))
        if ledger:
            pipe.get(backend.make_key(exposure.ledger_key(viewer_id)))
            plan.append(("ledger", 1))
        if head:
            pipe.get(backend.make_key(hot.head_key("home", viewer_id)))
            plan.append(("head", 1))
        if pools:
            plan.append(("pools", discovery.queue_reads(pipe, cfg)))
        if prof:
            pipe.get(backend.make_key(hot.profile_key(viewer_id)))
            plan.append(("prof", 1))
        if si:
            pipe.hgetall(backend.make_key(hot.session_interest_key(viewer_id)))
            plan.append(("si", 1))
        results = pipe.execute()
    except Exception:  # noqa: BLE001 - redis-hot down: rank without the hot state
        state.ok = False
        return state
    at = 0
    for name, n in plan:
        chunk = results[at : at + n]
        at += n
        if name == "visit":
            state.visit = session_ctx.decode_hash(chunk[0])
        elif name == "ledger":
            state.ledger = chunk[0]
        elif name == "head":
            state.head = chunk[0]
        elif name == "prof":
            state.prof = chunk[0]
        elif name == "si":
            state.si = chunk[0] or {}
        else:
            state.pools = discovery.parse_reads(chunk)
    return state


# ---- the multiplier ------------------------------------------------------------------


@dataclass(frozen=True)
class Exposure:
    """One item's exposure, hot and durable merged."""

    state: int
    minute: int  # epoch minute of the latest display
    exposures: int
    in_visit: bool


def multiplier(e: Exposure | None, now: datetime, block: dict) -> float:
    """``m(item)`` of 06 section 5.3 (1.0 without a state: retrieved only)."""
    if e is None:
        return 1.0
    name = STATE_NAMES[e.state]
    m0 = block["in_visit_m0" if e.in_visit else "m0"][name]
    dt_h = max(now.timestamp() / 60.0 - e.minute, 0.0) / 60.0
    m = 1.0 - (1.0 - m0) * math.pow(2.0, -dt_h / block["half_life_h"][name])
    return math.pow(m, min(max(e.exposures, 1), block["max_exposures"]))


# ---- the durable half and the conversation exception ---------------------------------
# Read by ``features.build(..., exposure=...)`` in its per-post statement (+0 queries).


@dataclass
class Durable:
    state: int | None
    last_at: datetime | None
    visits: int


def durable_of(feats) -> Durable:
    return Durable(feats.exp_state, feats.exp_last_at, feats.exp_visits)


# The conversation exception (06 section 5.3): distinct non-suspect commenters on each
# demoted item since the viewer's latest display of it. One small read, only when
# some item is demoted below ``revisit.min_m``, of at most ``REVISIT_CHECK`` of them
# (the best by pre-multiplier score: only those can return to the first page).
# Suspect (02 section 16): an account younger than ``suspect_account_age_hours`` at
# the comment, or past ``suspect_burst_per_min`` comments in the minute up to it
# (a window count, so the planner never estimates a per-row scan and never JIT-
# compiles this OLTP read); restricted and synthetic actors never count.
REVISIT_CHECK = 60
_NEW_COMMENTERS_SQL = """
WITH d AS (
    SELECT * FROM unnest(%(posts)s::uuid[], %(authors)s::uuid[], %(shown)s::timestamptz[])
         AS d(post_id, author_id, shown_at)),
k AS (
    SELECT n.comment_id, n.post_id, n.author_id, n.occurred_at
    FROM comment_state n JOIN d ON d.post_id = n.post_id
    WHERE n.active AND n.author_id IS NOT NULL AND n.occurred_at > d.shown_at
      AND n.author_id <> %(v)s AND n.author_id IS DISTINCT FROM d.author_id),
w AS (
    SELECT b.comment_id,
           count(*) OVER (PARTITION BY b.author_id ORDER BY b.occurred_at
                          RANGE BETWEEN interval '00:00:59.999999' PRECEDING
                          AND CURRENT ROW) AS burst
    FROM comment_state b WHERE b.author_id IN (SELECT author_id FROM k))
SELECT k.post_id, count(DISTINCT k.author_id)
FROM k
JOIN w ON w.comment_id = k.comment_id
LEFT JOIN author_ref a ON a.account_id = k.author_id
WHERE (%(age_h)s = 0 OR a.registered_at IS NULL
       OR k.occurred_at - a.registered_at >= make_interval(hours => %(age_h)s))
  AND (%(burst)s = 0 OR w.burst <= %(burst)s)
  AND NOT EXISTS (SELECT 1 FROM intel_account_restriction x
                  WHERE x.account_id = k.author_id AND x.active)
  AND (%(synthetic)s OR NOT EXISTS (
        SELECT 1 FROM intel_synthetic_account y WHERE y.account_id = k.author_id))
GROUP BY k.post_id
"""


def new_commenters(viewer_id, items: list[tuple[str, str | None, datetime]], cfg) -> dict:
    """``{post_id: distinct non-suspect commenters since shown_at}`` for ``items``
    ``[(post_id, author_id, shown_at)]`` (author and viewer excluded, restricted and
    synthetic actors excluded unless ``INTEL_SYNTHETIC_IN_RANKING``)."""
    from django.conf import settings
    from django.db import connection

    if not items:
        return {}
    integrity = cfg.section("integrity")
    with connection.cursor() as cur:
        cur.execute(
            _NEW_COMMENTERS_SQL,
            {
                "v": str(viewer_id),
                "posts": [p for p, _, _ in items],
                "authors": [a for _, a, _ in items],
                "shown": [t for _, _, t in items],
                "age_h": int(integrity.get("suspect_account_age_hours", 0)),
                "burst": int(integrity.get("suspect_burst_per_min", 0)),
                "synthetic": bool(getattr(settings, "INTEL_SYNTHETIC_IN_RANKING", False)),
            },
        )
        return {str(p): int(n) for p, n in cur.fetchall()}


def hot_minutes(cands, folds: dict) -> dict:
    """``{post_id: epoch minute of the latest hot display}`` for ``features.build``."""
    out = {}
    for c in cands:
        f = folds.get(prefix(c.post_id))
        if f is not None:
            out[c.post_id] = f.minute
    return out


def merge(fold, durable: Durable | None) -> Exposure | None:
    """The hot fold and the durable row as one exposure (highest state, latest time)."""
    have_durable = durable is not None and durable.state is not None and durable.last_at
    if fold is None and not have_durable:
        return None
    if fold is None:
        return Exposure(
            durable.state, int(durable.last_at.timestamp() // 60), max(durable.visits, 1), False
        )
    if not have_durable:
        return Exposure(fold.state, fold.minute, fold.exposures, fold.in_visit)
    return Exposure(
        max(fold.state, durable.state),
        max(fold.minute, int(durable.last_at.timestamp() // 60)),
        max(fold.exposures, durable.visits),
        fold.in_visit,
    )


# ---- applying it --------------------------------------------------------------------


@dataclass
class Context:
    """The viewer's exposure context for one first page."""

    now: datetime
    folds: dict = field(default_factory=dict)  # bytes8 -> exposure.Fold
    previous_head: frozenset = frozenset()  # post ids of the previous first page
    since: datetime | None = None
    lapsed: bool = False


@dataclass
class Stats:
    demoted: int = 0
    carry_over: int = 0
    new_activity: int = 0
    new_since: int = 0
    floor_moved: int = 0
    pre: dict = field(default_factory=dict)  # post_id -> pre-multiplier score
    m: dict = field(default_factory=dict)  # post_id -> multiplier
    new_ids: list = field(default_factory=list)  # boosted new-since items, best first


def _minute_at(minute: int) -> datetime:
    from datetime import UTC

    return datetime.fromtimestamp(minute * 60, tz=UTC)


def _reweight(s: Scored, factor: float, extra: float, name: str) -> None:
    new = s.value * factor + extra
    s.contributions.append((name, new - s.value))
    s.value = new


def apply(
    viewer_id,
    scored: list[Scored],
    ctx: Context,
    cfg: SurfaceConfig,
    *,
    exclude_source: str,
) -> Stats:
    """Multiply every candidate's score in place (exposure, new activity, new since),
    then sort best first. Returns what changed, for the meta and the harness."""
    stats = Stats()
    if not scored:
        return stats
    block = cfg.section("exposure")
    min_m = cfg.get("revisit.min_m")
    needed = cfg.get("revisit.new_comments")
    new_since = cfg.section("session")["new_since"]
    cap = new_since["lapsed_max_items" if ctx.lapsed else "max_items"]
    fresh = []
    demoted: list[tuple[Scored, Exposure, float]] = []
    for s in scored:
        pid = s.feats.post_id
        stats.pre[pid] = s.value
        e = merge(ctx.folds.get(prefix(pid)), durable_of(s.feats))
        m = multiplier(e, ctx.now, block)
        if e is None and pid in ctx.previous_head:
            stats.carry_over += 1  # retrieved before, never displayed: full score
        if m < min_m:
            demoted.append((s, e, m))
        stats.m[pid] = m
        if (
            ctx.since is not None
            and s.feats.source != exclude_source
            and s.feats.created_at is not None
            and s.feats.created_at > ctx.since
        ):
            fresh.append(s)
    if demoted:
        demoted.sort(key=lambda t: stats.pre[t[0].feats.post_id], reverse=True)
        check = demoted[:REVISIT_CHECK]
        shown = [(t[0].feats.post_id, t[0].feats.author_id, _minute_at(t[1].minute)) for t in check]
        counts = new_commenters(viewer_id, shown, cfg)
        for s, _e, _m in check:
            if counts.get(s.feats.post_id, 0) >= needed:
                stats.m[s.feats.post_id] = max(stats.m[s.feats.post_id], min_m)
                stats.new_activity += 1
                s.contributions.append((NEW_ACTIVITY_REASON, 0.0))
    for s in scored:
        m = stats.m[s.feats.post_id]
        if m < 1.0:
            stats.demoted += 1
            _reweight(s, m, 0.0, "exposure")
    fresh.sort(key=lambda x: stats.pre[x.feats.post_id], reverse=True)
    for s in fresh[: max(int(cap), 0)]:
        _reweight(s, 1.0, new_since["boost"] * stats.pre[s.feats.post_id], NEW_SINCE_REASON)
        stats.new_ids.append(s.feats.post_id)
    stats.new_since = len(stats.new_ids)
    scored.sort(key=Scored.sort_key)
    return stats


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = (len(ordered) - 1) * pct / 100.0
    lo, hi = math.floor(rank), math.ceil(rank)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (rank - lo)


def floor(ranked: list[Scored], stats: Stats, cfg: SurfaceConfig, page_size: int) -> list[Scored]:
    """The relevance floor of 06 section 5.4 on the first re-ranked page."""
    rot = cfg.section("rotation")
    slots = min(int(rot["floor_slots"]), page_size, len(ranked))
    if slots <= 0 or not stats.pre:
        return ranked
    threshold = rot["floor"] * _percentile(list(stats.pre.values()), rot["floor_pct"])
    page = ranked[:page_size]
    passing = [s for s in page if s.value >= threshold]
    seen = [s for s in page if s.value < threshold and stats.pre[s.feats.post_id] >= threshold]
    seen.sort(key=lambda s: s.value, reverse=True)
    head = (passing + seen)[:slots]
    chosen = {id(s) for s in head}
    rest = [s for s in page if id(s) not in chosen]
    out = head + rest
    stats.floor_moved = sum(1 for a, b in zip(out, page, strict=True) if a is not b)
    return out + ranked[page_size:]
