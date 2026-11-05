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
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .. import eligibility
from ..config import SurfaceConfig
from ..predictions import for_config
from ..retrieval import sources as src
from . import diversity, explain, features
from .scorer import Scored, Scorer

SOURCE_FUNCS = {
    src.CONNECTIONS: lambda viewer, cfg, now: src.connections(viewer, cfg),
    src.FOLLOW_PULL: src.follow_pull,
    src.GROUPS: src.groups,
}


@dataclass
class Ranking:
    items: list[Scored]
    cfg: SurfaceConfig
    # The oldest connection row retrieved when the connections window was full:
    # older rows continue in latest order after the session (``feed/ranking.py``).
    edge: tuple[str, str] | None
    dropped: dict

    def factors(self, s: Scored) -> list[tuple[int, int]]:
        return explain.top(s.contributions)


def inventory(viewer_id, cfg: SurfaceConfig, now: datetime):
    """Candidates of every configured source, connections first, one per post."""
    found, seen = [], set()
    window_full, oldest = False, None
    for name in cfg.get("ranking.sources"):
        rows = SOURCE_FUNCS[name](str(viewer_id), cfg, now)
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


def rank(viewer: eligibility.Viewer, now: datetime, cfg: SurfaceConfig) -> Ranking:
    candidates, edge = inventory(viewer.id, cfg, now)
    allowed = eligibility.filter(viewer, candidates, cfg)
    feats = features.build(viewer.id, allowed.kept, cfg, now)
    preds = for_config(cfg).predict(viewer.id, feats, cfg)
    scorer = Scorer(cfg)
    scored = sorted(
        (scorer.score(f, p) for f, p in zip(feats, preds, strict=True)),
        key=Scored.sort_key,
    )
    block = cfg.section("diversity")
    if block["enabled"] and scored:
        items = [
            diversity.Item(key=s, score=s.value, author=s.feats.author_id or "", type=s.feats.type)
            for s in scored
        ]
        scored = [i.key for i in diversity.rerank(items, block)]
    return Ranking(scored, cfg, edge, dict(allowed.dropped))
