"""The Home ranker (FeedRankingService for ``for_you``; 02 section 6; WP 4.3).

``rank(viewer, now, cfg)`` runs the four stages on the active home config:

1. **inventory**: the sources named in ``ranking.sources`` (``home@1``: connections
   only, today's candidates; ``home@2``: connections, follow pull and joined groups);
2. **eligibility**: ``intel.eligibility.filter`` (fail closed) before any scoring;
3. **features and predictions**: ``features.build`` (batched) and the config's
   predictor (``RulePredictor``);
4. **value model** (``scorer``) and, when ``diversity.enabled``, the diversity
   re-ranker.

``feed/ranking.py::rank_items`` always delegates here; ``home@1`` reproduces
today's order exactly (``tests/test_home_v1_parity.py``).

**Recommended items** (07 WP 4b.6; ``home@2b`` and its arms). When the version names
the ``discovery`` source, the popular / fresh pools (``intel.discovery``) join the
inventory: their ids come from one pipelined Redis read, and everything else they
need (author, time, type, whether the viewer already has a feed row for them) comes
from the eligibility read that runs anyway, so pools add **no SQL query**. Pool
items pass every DISCOVERY rule with the viewer's claims. The mix is per viewer:
the variant's ``mix.recommended`` share, or at least ``mix.thin_inventory.share``
when the viewer's eligible connection candidates are below
``mix.thin_inventory.below_candidates`` (decisions 4 and 23). Recommended items take
the slots where the running share would fall below that share; when the connection
items end and the variant recommends anything (``continuation.pools``), the session
goes on into pool items (at most ``continuation.max_items``) and ``caught_up`` marks
the first of them. At every recommended slot the best remaining pool item that keeps
the diversity block's author, gap and format rules on the merged list is taken, so
the rules hold across both kinds without moving the share.

**Exposure and rotation** (R3; only under a version carrying ``rotation``, ``home@2c``):
``exposure_rank.apply`` multiplies every score by the viewer's exposure multiplier
and adds the new-since boost before the mix and the re-ranker, and
``exposure_rank.floor`` keeps the first slots above the relevance floor. ``ctx`` (the
ledger fold, the previous head, ``since``) comes from the first page's one pipelined
redis-hot read, as do the pool ids (``pools``).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from .. import discovery, eligibility
from ..config import SurfaceConfig
from ..predictions import for_config
from ..retrieval import sources as src
from ..retrieval.sources import Candidate
from . import diversity, explain, exposure_rank, features
from .scorer import Scored, Scorer

DISCOVERY = discovery.SOURCE
SOURCE_FUNCS = {
    src.CONNECTIONS: lambda viewer, cfg, now: src.connections(viewer, cfg),
    src.FOLLOW_PULL: src.follow_pull,
    src.GROUPS: src.groups,
    # Ids only, from redis-hot; the eligibility read supplies the rest (WP 4b.6).
    DISCOVERY: lambda viewer, cfg, now: discovery.read(cfg) if discovery.retrieves(cfg) else [],
}
# A numerical guard for the share arithmetic (0.15 * 20 is 3.0000000000000004).
_EPS = 1e-9


@dataclass
class Ranking:
    items: list[Scored]
    cfg: SurfaceConfig
    # The oldest connection row retrieved when the connections window was full:
    # older rows continue in latest order after the session (``feed/ranking.py``).
    edge: tuple[str, str] | None
    dropped: dict
    # WP 4b.6: the session index of the first item after the connection inventory
    # ran out (continuation into pools), else None; and what the mix used.
    caught_up: int | None = None
    content: dict = field(default_factory=dict)  # eligibility's content rows
    connection_candidates: int = 0
    share: float = 0.0
    # R3: what the exposure pass changed (None when the version has no ``rotation``).
    exposure: exposure_rank.Stats | None = None

    def factors(self, s: Scored) -> list[tuple[int, int]]:
        return explain.top(s.contributions)


@dataclass
class Inventory:
    """Eligible candidates of one viewer, split by kind (the harness's selection)."""

    connections: list[Candidate]
    pools: list[Candidate]
    content: dict
    dropped: dict
    edge: tuple[str, str] | None


def inventory(viewer_id, cfg: SurfaceConfig, now: datetime, pools: list | None = None):
    """Candidates of every configured source, connections first, one per post.
    ``pools``: the pool ids already read (the first page's pipelined read), if any."""
    found, seen = [], set()
    window_full, oldest = False, None
    for name in cfg.get("ranking.sources"):
        if name == DISCOVERY and pools is not None:
            rows = pools if discovery.retrieves(cfg) else []
        else:
            rows = SOURCE_FUNCS[name](str(viewer_id), cfg, now)
        if name == DISCOVERY:
            for c in rows:
                if c.post_id not in seen:
                    seen.add(c.post_id)
                    found.append(c)
            continue
        if name == src.CONNECTIONS:
            window_full = len(rows) >= cfg.get(f"window.{src.CONNECTIONS}")
            if rows:
                last = min(rows, key=lambda c: (c.created_at, c.item_id or ""))
                oldest = (last.created_at.isoformat(), last.item_id)
        for c in rows:
            if c.post_id not in seen:
                seen.add(c.post_id)
                found.append(c)
    return found, (oldest if window_full else None)


def eligible_inventory(
    viewer: eligibility.Viewer, cfg: SurfaceConfig, now, pools: list | None = None
) -> Inventory:
    """Stage 1 and 1b: every source, then the eligibility filter (fail closed). Pool
    items the viewer already has a feed row for, or past their bucket's window, are
    left out (they are not recommendations)."""
    candidates, edge = inventory(viewer.id, cfg, now, pools)
    allowed = eligibility.filter(viewer, candidates, cfg)
    conn, pools = [], []
    for c in allowed.kept:
        if c.source != DISCOVERY:
            conn.append(c)
            continue
        ref = allowed.content.get(c.post_id) or {}
        if ref.get("in_feed") or not ref.get("author_id"):
            continue
        if not discovery.in_window(c.reason, ref.get("created_at"), cfg, now):
            continue
        pools.append(
            Candidate(
                c.post_id,
                str(ref["author_id"]),
                DISCOVERY,
                c.reason,
                ref["created_at"],
                ref.get("type") or "",
            )
        )
    return Inventory(conn, pools, allowed.content, dict(allowed.dropped), edge)


def _score(
    viewer_id, cands: list[Candidate], cfg: SurfaceConfig, now, exposure: dict | None = None
) -> list[Scored]:
    feats = features.build(viewer_id, cands, cfg, now, exposure)
    preds = for_config(cfg).predict(viewer_id, feats, cfg)
    scorer = Scorer(cfg)
    return sorted(
        (scorer.score(f, p) for f, p in zip(feats, preds, strict=True)),
        key=Scored.sort_key,
    )


def _items(scored: list[Scored], scores=None) -> list[diversity.Item]:
    return [
        diversity.Item(
            key=s,
            score=s.value if scores is None else scores[i],
            author=s.feats.author_id or "",
            type=s.feats.type,
        )
        for i, s in enumerate(scored)
    ]


Fits = Callable[[list, object], bool]


def mix(
    conn: list, recs: list, share: float, tail: int, fits: Fits | None = None
) -> tuple[list, int | None]:
    """Recommended items in the slots where the running share would fall below
    ``share`` (so every prefix holds ``floor(k * share)`` of them, exactly), then up to
    ``tail`` more after the connection items end. At each slot the best remaining
    recommendation that ``fits`` the list so far (the diversity rules) is taken, else
    the best remaining one: the share never moves. Returns the list and the index of
    the first item after the connection items (only when a tail follows)."""
    out: list = []
    left = list(recs)

    def take():
        index = next((i for i, r in enumerate(left) if fits is None or fits(out, r)), 0)
        return left.pop(index)

    ci = placed = 0
    while ci < len(conn):
        if left and placed < math.floor((len(out) + 1) * share + _EPS):
            out.append(take())
            placed += 1
        else:
            out.append(conn[ci])
            ci += 1
    head = len(out)
    for _ in range(min(max(tail, 0), len(left))):
        out.append(take())
    return out, (head if len(out) > head else None)


def _mix_diverse(
    conn: list[Scored],
    recs: list[Scored],
    share: float,
    tail: int,
    block: dict,
    demoted: frozenset = frozenset(),
) -> tuple[list[Scored], int | None]:
    """``mix`` inside the diversity re-ranker: the recommended slots are claimed as
    the pages are built, so pages keep their size and the connection items are
    diversified around the recommendations (same rules, same share). ``demoted``: the
    post ids the exposure pass pushed below ``revisit.min_m`` (R3; empty otherwise)."""
    left = [
        diversity.Item(key=s, score=s.value, author=s.feats.author_id or "", type=s.feats.type)
        for s in recs
    ]
    placed = [0]

    def insert(position: int, page) -> diversity.Item | None:
        if not left or placed[0] >= math.floor((position + 1) * share + _EPS):
            return None
        index = next(
            (i for i, it in enumerate(left) if page.ok_author(it) and page.ok_format(it)), 0
        )
        placed[0] += 1
        return left.pop(index)

    def relief(position: int, page, names) -> diversity.Item | None:
        # No connection item keeps the diversity rules ``names`` at this slot: in a
        # variant that continues into pools (``tail``), a pool item that keeps them
        # takes it, and the connection item waits for a later page (07 WP 4b.10, "at
        # most 2 per author per page when alternatives exist"). It counts toward the
        # share, so the share is a floor here, never doubled. The control (no tail)
        # keeps its decision-23 cap: no relief.
        keeps = page.predicate(names)  # the same rules, the page state read once
        index = next((i for i, it in enumerate(left) if keeps(it)), None)
        if index is None:
            return None
        placed[0] += 1
        return left.pop(index)

    def contest(position: int, page, picked) -> diversity.Item | None:
        # R3 verifier (06 section 5.4, scenario C): when the pick is a connection item
        # the viewer already saw (``m < revisit.min_m``), a pool item that keeps every
        # rule and scores higher after the multiplier takes the slot: rotation by
        # ``score · m``, not a seen item ahead of a better unseen one because the
        # unseen connection items all belong to one capped author. Like ``relief``,
        # it counts toward the share (a floor here) and only in a continuing variant.
        if picked.key.feats.post_id not in demoted:
            return None
        keeps = None
        for i, it in enumerate(left):
            if it.score <= picked.score:
                return None  # ``left`` is best first: nothing further scores higher
            keeps = keeps or page.predicate(diversity.RELAX_ORDER)
            if keeps(it):
                placed[0] += 1
                return left.pop(i)
        return None

    merged = [
        i.key
        for i in diversity.rerank(
            _items(conn),
            block,
            insert=insert,
            relief=relief if tail > 0 else None,
            contest=contest if tail > 0 and demoted else None,
        )
    ]
    head = len(merged)
    fits = _fits(block)
    rest = [i.key for i in left]
    for _ in range(min(max(tail, 0), len(rest))):
        index = next((i for i, s in enumerate(rest) if fits(merged, s)), 0)
        merged.append(rest.pop(index))
    return merged, (head if len(merged) > head else None)


def _fits(block: dict) -> Fits:
    """The re-ranker's author and format rules, read on the merged list as it grows:
    at most ``max_per_author_page`` per page, ``author_gap`` slots between two items of
    one author, no run longer than ``max_same_format_run``."""
    size, cap = block["page_size"], block["max_per_author_page"]
    gap, run = block["author_gap"], block["max_same_format_run"]

    def fits(out: list, s: Scored) -> bool:
        author, kind = s.feats.author_id or "", s.feats.type
        page = out[len(out) - len(out) % size :]
        if sum(1 for p in page if (p.feats.author_id or "") == author) >= cap:
            return False
        if gap and any((p.feats.author_id or "") == author for p in out[-gap:]):
            return False
        tail = out[-run:]
        return not (len(tail) == run and all(p.feats.type == kind for p in tail))

    return fits


def rank(
    viewer: eligibility.Viewer,
    now: datetime,
    cfg: SurfaceConfig,
    ctx: exposure_rank.Context | None = None,
    pools: list | None = None,
) -> Ranking:
    inv = eligible_inventory(viewer, cfg, now, pools)
    share = discovery.share_for(cfg, len(inv.connections)) if inv.pools else 0.0
    # One feature pass for both kinds: pools add no query (the same IN reads).
    cands = inv.connections + (inv.pools if share > 0 else [])
    exposed = ctx is not None and exposure_rank.applies(cfg)
    # R3: the durable exposure is read in the same per-post statement (+0 queries).
    hot_min = exposure_rank.hot_minutes(cands, ctx.folds) if exposed else None
    everything = _score(viewer.id, cands, cfg, now, hot_min)
    stats = None
    if exposed:
        # score' = score x m (+ the new-since boost), before the mix and diversity.
        stats = exposure_rank.apply(viewer.id, everything, ctx, cfg, exclude_source=DISCOVERY)
    conn = [s for s in everything if s.feats.source != DISCOVERY]
    recs = [s for s in everything if s.feats.source == DISCOVERY]
    block = cfg.section("diversity")
    scored = conn
    if block["enabled"] and conn and share <= 0:
        scored = [i.key for i in diversity.rerank(_items(conn), block)]
    caught_up = None
    if share > 0:
        tail = cfg.get("continuation.max_items") if discovery.continues(cfg) else 0
        if block["enabled"]:
            demoted = frozenset()
            if stats is not None:
                floor_m = cfg.get("revisit.min_m")
                demoted = frozenset(p for p, m in stats.m.items() if m < floor_m)
            scored, caught_up = _mix_diverse(conn, recs, share, tail, block, demoted)
        else:
            scored, caught_up = mix(scored, recs, share, tail)
        if inv.edge is not None:
            # The connections window was full: older connection rows still follow the
            # session in latest order, so the inventory has not run out yet.
            caught_up = None
    if stats is not None:
        scored = exposure_rank.floor(scored, stats, cfg, block["page_size"])
    return Ranking(
        scored,
        cfg,
        inv.edge,
        inv.dropped,
        caught_up=caught_up,
        content=inv.content,
        connection_candidates=len(inv.connections),
        share=share,
        exposure=stats,
    )
