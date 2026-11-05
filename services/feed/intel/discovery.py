"""Home discovery pools, minimal (07 WP 4b.6, pulled forward from WP 9.1).

Two sorted sets per (surface, lang) in ``redis-hot``, under the ``pool_key`` shape
the deletion path already removes members from (``intel.hot``):

- ``intel:pool:home:{lang}:popular``: public posts of the last ``pools.popular.window_d``
  days by **smoothed engagement per hour**,

      (r·R + c·C + s·S − f·F + prior_engagement) / (age_h + prior_hours)

  where R counts only **non-suspect** reactions (02 section 16: the reactor's account
  older than ``integrity.suspect_account_age_hours`` at the time, fewer than
  ``integrity.suspect_burst_per_min`` reactions in the minute before, not flagged
  ``suspect`` at ingest, not a synthetic actor unless ``INTEL_SYNTHETIC_IN_RANKING``),
  C and S are ``post_stats`` comments and shares, F its spam / sexual flags, the
  weights are the config's ``engagement`` block, and a post needs at least
  ``pools.popular.min_engagement``;
- ``intel:pool:home:{lang}:fresh``: public posts of the last ``pools.fresh.max_age_h``
  hours by ``2^(−age_h / freshness.half_life_hours)`` times the integrity multipliers
  (bait, duplicate), kept at or above ``pools.fresh.min_score``.

Rebuilds (``intel.rebuild_pools``, every ``pools.rebuild_s``) apply the content and
author rules that do not depend on a viewer: E1, E1b, E1c, E2, E6, E6b, E7, E11 and
E9b (the author's age class), through the eligibility rule functions themselves.
Authors registered as synthetic or test accounts are left out unless
``INTEL_SYNTHETIC_IN_RANKING`` (dev only). Each set keeps the best ``pools.cap``.
At serve time every pool item goes through the full eligibility filter again with
the viewer's claims (E4, E5, E8, E9, E10 included), so a pool never decides who may
see what. ``redis-hot`` is ``noeviction``: a refused write is counted
(``intel_hot_write_failed_total{key="pool"}``) and the old set stays.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.db import connection
from django.utils import timezone

from . import config, eligibility, hot, metrics
from .config import SurfaceConfig
from .retrieval.sources import Candidate
from .topics.language import LANGS

logger = logging.getLogger("tara.intel.discovery")

SURFACE = "home"
SOURCE = "discovery"
POPULAR, FRESH = "popular", "fresh"
BUCKETS = (POPULAR, FRESH)
REASONS = {POPULAR: "rec_popular", FRESH: "rec_fresh"}
BUCKET_OF = {v: k for k, v in REASONS.items()}
# The rules a rebuild can decide without a viewer (07 WP 4b.6).
POOL_RULES = frozenset({"E1", "E1b", "E1c", "E2", "E6", "E6b", "E7", "E11", "E9b"})
# When the last rebuild ran (not under ``intel:pool:*``: the deletion path ZREMs those).
STAMP = "intel:poolmeta:home"


def has_pools(cfg: SurfaceConfig) -> bool:
    """The version carries the WP 4b.6 blocks (schema version 2)."""
    pools = cfg.params.get("pools") or {}
    return all(k in pools for k in ("popular", "fresh", "max_members", "cap")) and (
        "mix" in cfg.params
    )


def retrieves(cfg: SurfaceConfig) -> bool:
    """The variant reads pools: it names the source and can recommend anything."""
    if not has_pools(cfg) or SOURCE not in cfg.get("ranking.sources"):
        return False
    return cfg.get("mix.recommended") > 0 or cfg.get("mix.thin_inventory.share") > 0


def share_for(cfg: SurfaceConfig, connection_candidates: int) -> float:
    """The recommended share for one viewer (decisions 4 and 23)."""
    if not has_pools(cfg):
        return 0.0
    share = float(cfg.get("mix.recommended"))
    thin = cfg.section("mix")["thin_inventory"]
    if connection_candidates < thin["below_candidates"]:
        share = max(share, float(thin["share"]))
    return share


def continues(cfg: SurfaceConfig) -> bool:
    """The session goes on into pool items after the connection inventory ends."""
    return (
        has_pools(cfg)
        and "continuation" in cfg.params
        and bool(cfg.get("continuation.pools"))
        and cfg.get("mix.recommended") > 0
    )


# ---- rebuild ----------------------------------------------------------------------------

_CANDIDATES_SQL = """
SELECT c.post_id, c.author_id, c.lang, c.type, c.created_at, c.bait_score,
       (c.dup_of IS NOT NULL AND o.post_id IS NOT NULL) AS duplicate,
       coalesce(s.comments, 0), coalesce(s.shares, 0), coalesce(s.flags, 0)
FROM intel_content_ref c
LEFT JOIN intel_content_ref o ON o.post_id = c.dup_of AND o.state = 'live'
LEFT JOIN post_stats s ON s.post_id = c.post_id
WHERE c.audience = 'public' AND c.group_id IS NULL AND c.state = 'live'
  AND c.author_id IS NOT NULL AND c.created_at >= %(since)s AND c.created_at <= %(now)s
  AND (%(synthetic)s OR NOT EXISTS (
        SELECT 1 FROM intel_synthetic_account x WHERE x.account_id = c.author_id))
"""
# Non-suspect reactions per post (02 section 16), as of each reaction's own time.
_REACTIONS_SQL = """
SELECT r.post_id, count(*)
FROM reaction_state r
LEFT JOIN author_ref a ON a.account_id = r.reactor_id
WHERE r.active AND NOT r.suspect AND r.post_id = ANY(%(posts)s::uuid[])
  AND (%(age_h)s = 0 OR a.registered_at IS NULL
       OR r.occurred_at - a.registered_at >= make_interval(hours => %(age_h)s))
  AND (%(burst)s = 0 OR (
        SELECT count(*) FROM reaction_state b
        WHERE b.reactor_id = r.reactor_id
          AND b.occurred_at > r.occurred_at - interval '1 minute'
          AND b.occurred_at <= r.occurred_at) <= %(burst)s)
  AND (%(synthetic)s OR NOT EXISTS (
        SELECT 1 FROM intel_synthetic_account x WHERE x.account_id = r.reactor_id))
GROUP BY r.post_id
"""


@dataclass(frozen=True)
class _Row:
    post_id: str
    author_id: str
    lang: str
    type: str
    created_at: datetime
    bait_score: float | None
    duplicate: bool
    comments: int
    shares: int
    flags: int


def _rows(sql: str, params) -> list[tuple]:
    with connection.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def _pool_eligible(rows: list[_Row], cfg: SurfaceConfig) -> list[_Row]:
    """The viewer-independent rules, run by the eligibility functions themselves."""
    if not rows:
        return []
    neutral = eligibility.Viewer(id="00000000-0000-0000-0000-000000000000")
    cands = [Candidate(r.post_id, r.author_id, SOURCE, "", r.created_at, r.type) for r in rows]
    ctx = eligibility.load_context(neutral, cands, cfg)
    keep = set()
    dropped: dict[str, int] = {}
    for c in cands:
        failed = next(
            (
                name
                for name, applies, rule in eligibility.RULES
                if name in POOL_RULES and c.source in applies and not rule(c, ctx)
            ),
            None,
        )
        if failed is None:
            keep.add(c.post_id)
        else:
            dropped[failed] = dropped.get(failed, 0) + 1
    for rule, n in dropped.items():
        metrics.eligibility_dropped(rule, n)
    return [r for r in rows if r.post_id in keep]


def _scores(rows: list[_Row], cfg: SurfaceConfig, now: datetime) -> dict[str, dict]:
    pools = cfg.section("pools")
    pop, fresh = pools["popular"], pools["fresh"]
    integrity = cfg.section("integrity")
    weights = cfg.section("engagement")
    half_life = cfg.get("freshness.half_life_hours")
    reactions = {
        str(post_id): n
        for post_id, n in _rows(
            _REACTIONS_SQL,
            {
                "posts": [r.post_id for r in rows],
                "age_h": int(integrity["suspect_account_age_hours"]),
                "burst": int(integrity["suspect_burst_per_min"]),
                "synthetic": bool(settings.INTEL_SYNTHETIC_IN_RANKING),
            },
        )
    }
    out: dict[str, dict] = {POPULAR: {}, FRESH: {}}
    popular_since = now - timedelta(days=pop["window_d"])
    for r in rows:
        age_h = max((now - r.created_at).total_seconds() / 3600.0, 0.0)
        engagement = (
            weights["reaction"] * int(reactions.get(r.post_id, 0) or 0)
            + weights["comment"] * max(r.comments, 0)
            + weights["share"] * max(r.shares, 0)
            - weights["flag_weight"] * max(r.flags, 0)
        )
        if r.created_at >= popular_since and engagement >= pop["min_engagement"]:
            out[POPULAR][r.post_id] = (engagement + pop["prior_engagement"]) / (
                age_h + pop["prior_hours"]
            )
        if age_h <= fresh["max_age_h"]:
            score = 2.0 ** (-age_h / half_life)
            if r.bait_score is not None and r.bait_score >= integrity["bait_min_score"]:
                score *= integrity["bait_multiplier"]
            if r.duplicate:
                score *= integrity["duplicate_multiplier"]
            if score >= fresh["min_score"]:
                out[FRESH][r.post_id] = score
    return out


def rebuild(cfg: SurfaceConfig | None = None, now: datetime | None = None) -> dict | None:
    """Rebuild every (lang, bucket) set from ``cfg`` (default: the active home version).
    Returns member counts, or None when the version has no pools (schema version 1)."""
    cfg = cfg or config.for_surface(SURFACE)
    if not has_pools(cfg):
        metrics.pool_rebuilt("skipped")
        return None
    now = now or timezone.now()
    pools = cfg.section("pools")
    window_h = max(pools["popular"]["window_d"] * 24, pools["fresh"]["max_age_h"])
    found = [
        _Row(str(p), str(a), lang or "und", kind or "", created, bait, bool(dup), c, s, f)
        for p, a, lang, kind, created, bait, dup, c, s, f in _rows(
            _CANDIDATES_SQL,
            {
                "since": now - timedelta(hours=window_h),
                "now": now,
                "synthetic": bool(settings.INTEL_SYNTHETIC_IN_RANKING),
            },
        )
    ]
    kept = _pool_eligible(found, cfg)
    scores = _scores(kept, cfg, now)
    lang_of = {r.post_id: r.lang if r.lang in LANGS else "und" for r in kept}
    client = hot.raw_client()
    counts = {"candidates": len(found), "eligible": len(kept), "sets": {}}
    if client is None:
        metrics.pool_rebuilt("no_redis")
        return counts
    cache = hot.hot()
    try:
        pipe = client.pipeline(transaction=True)
        for bucket in BUCKETS:
            for lang in LANGS:
                members = {p: s for p, s in scores[bucket].items() if lang_of[p] == lang}
                best = dict(sorted(members.items(), key=lambda kv: (-kv[1], kv[0]))[: pools["cap"]])
                key = cache.make_key(hot.pool_key(SURFACE, lang, bucket))
                pipe.delete(key)
                if best:
                    pipe.zadd(key, best)
                counts["sets"][f"{lang}:{bucket}"] = len(best)
        pipe.set(cache.make_key(STAMP), str(int(time.time())).encode())
        pipe.execute()
    except Exception:  # noqa: BLE001 - noeviction refusal or redis down: keep the old sets
        metrics.hot_write_failed("pool")
        metrics.pool_rebuilt("failed")
        logger.warning("discovery pools not rebuilt", exc_info=True)
        return counts
    metrics.pool_rebuilt("ok")
    return counts


def due(cfg: SurfaceConfig) -> bool:
    """A rebuild is due: ``pools.rebuild_s`` since the last one (or none yet)."""
    if not has_pools(cfg):
        return False
    stamp = hot.raw_get(STAMP)
    try:
        last = int(stamp) if stamp else 0
    except ValueError:
        last = 0
    return time.time() - last >= cfg.get("pools.rebuild_s")


# ---- serving ---------------------------------------------------------------------------


def read(cfg: SurfaceConfig) -> list[Candidate]:
    """Pool candidates for one first page: the best ``pools.max_members`` of each set,
    popular before fresh, one pipelined round trip. Ids only: author, time and type
    come from the eligibility read that follows. Empty when redis-hot is down."""
    client = hot.raw_client()
    if client is None:
        return []
    cache = hot.hot()
    n = cfg.get("pools.max_members")
    order = [(bucket, lang) for bucket in BUCKETS for lang in LANGS]
    try:
        pipe = client.pipeline(transaction=False)
        for bucket, lang in order:
            pipe.zrevrange(cache.make_key(hot.pool_key(SURFACE, lang, bucket)), 0, n - 1)
        results = pipe.execute()
    except Exception:  # noqa: BLE001 - no pools is today's feed, never an error
        logger.warning("discovery pools unreadable", exc_info=True)
        return []
    out, seen = [], set()
    for (bucket, _lang), members in zip(order, results, strict=True):
        for raw in members or ():
            post_id = raw.decode() if isinstance(raw, bytes) else str(raw)
            if post_id not in seen:
                seen.add(post_id)
                out.append(Candidate(post_id, None, SOURCE, REASONS[bucket], None))
    return out


def in_window(reason: str, created_at: datetime | None, cfg: SurfaceConfig, now) -> bool:
    """A stale set (rebuild stopped) never serves a post past its bucket's window."""
    if created_at is None:
        return False
    pools = cfg.section("pools")
    if BUCKET_OF.get(reason) == POPULAR:
        return created_at >= now - timedelta(days=pools["popular"]["window_d"])
    return created_at >= now - timedelta(hours=pools["fresh"]["max_age_h"])


def viewer_pool_ids(viewer: eligibility.Viewer, cfg: SurfaceConfig, now) -> list[str]:
    """The pool items this viewer may be served (the harness's "pool items remain")."""
    found = read(cfg) if has_pools(cfg) else []
    if not found:
        return []
    result = eligibility.filter(viewer, found, cfg)
    out = []
    for c in result.kept:
        ref = result.content.get(c.post_id) or {}
        if ref.get("in_feed") or not in_window(c.reason, ref.get("created_at"), cfg, now):
            continue
        out.append(c.post_id)
    return out


def reason_of(post_id: str, lang: str | None) -> str | None:
    """Which pool holds ``post_id`` now (why-this, when only a serve token proves it)."""
    client = hot.raw_client()
    if client is None:
        return None
    cache = hot.hot()
    lang = lang if lang in LANGS else "und"
    try:
        pipe = client.pipeline(transaction=False)
        for bucket in BUCKETS:
            pipe.zscore(cache.make_key(hot.pool_key(SURFACE, lang, bucket)), post_id)
        found = pipe.execute()
    except Exception:  # noqa: BLE001
        return None
    for bucket, score in zip(BUCKETS, found, strict=True):
        if score is not None:
            return REASONS[bucket]
    return None
