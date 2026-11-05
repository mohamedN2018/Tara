"""Stage 4a: the value model (02 section 6.4; WP 4.3).

    value = w_fresh · 2^(−age_h / half_life)
          + w_rel · relationship            reason prior + favorite + log1p(affinity)
                                            − dislikes (capped) + shared groups + conversation
          + w_eng · engagement              today's log1p(r·R + c·C + s·S) − f·log1p(flags)
          + Σ_k w_k · score_k               meaningful, like, comment, share, save, complete
          + w_int · interest_rel
          + w_qual · media quality + w_orig · originality
          − w_neg · score_negative
    score = value × Π integrity multipliers (pending reports, duplicate, bait, spam flags)

Every weight, prior, cap and multiplier is read from the config (``SurfaceConfig``);
a weight of 0 turns its term off. ``home@1`` is today's ``feed/ranking.py`` formula
exactly: freshness 3, relationship 1 (self 0.3, friend 1.0, follow 0.6, favorite 1.5,
affinity 0.25, dislike 0.75 capped at 3), engagement 0.5, every other term 0 and
every multiplier 1. Terms are added in that fixed order, so ``home@1`` reproduces
today's floating-point sums bit for bit (``test_home_v1_parity.py``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .. import integrity
from ..config import SurfaceConfig
from ..predictions.base import Prediction
from .features import CandidateFeatures

ENGAGEMENT_DIGITS = 6  # today's stored engagement score is rounded to 6 digits


@dataclass
class Scored:
    feats: CandidateFeatures
    pred: Prediction
    value: float
    contributions: list[tuple[str, float]] = field(default_factory=list)

    def sort_key(self):
        """Best first; ties by newer post, then by id (today's ``ranking._sort_key``)."""
        created = self.feats.created_at.timestamp() if self.feats.created_at else 0.0
        return (-self.value, -created, self.feats.tie_id)


def engagement(f: CandidateFeatures, block: dict) -> float:
    if not f.has_stats:
        return f.stored_score or 0.0
    raw = block["reaction"] * f.reactions + block["comment"] * f.comments
    raw += block["share"] * f.shares
    return round(math.log1p(raw) - block["flag_weight"] * math.log1p(f.flags), ENGAGEMENT_DIGITS)


class Scorer:
    """Reads its blocks once per request, then scores every candidate."""

    def __init__(self, cfg: SurfaceConfig):
        self.w = cfg.section("weights")
        self.rel = cfg.section("relationship")
        self.eng = cfg.section("engagement")
        self.half_life = cfg.get("freshness.half_life_hours")
        self.orig = cfg.section("originality")
        self.integrity = cfg.section("integrity")

    def score(self, f: CandidateFeatures, p: Prediction) -> Scored:
        w, rel = self.w, self.rel
        terms: list[tuple[str, float]] = []

        def add(name: str, amount: float) -> None:
            terms.append((name, amount))

        add("freshness", w["freshness"] * math.pow(2.0, -f.age_h / self.half_life))
        w_rel = w["relationship"]
        add("reason", w_rel * rel["reason_prior"].get(f.reason, 0.0))
        if f.favorite:
            add("favorite", (w_rel * rel["favorite_bonus"]))
        add("affinity", (w_rel * rel["affinity_weight"]) * math.log1p(f.affinity))
        add(
            "dislike",
            -((w_rel * rel["dislike_weight"]) * min(f.author_dislikes, rel["dislike_cap"])),
        )
        add("shared_groups", (w_rel * rel["shared_group_weight"]) * math.log1p(f.shared_groups))
        add("conversation", (w_rel * rel["conversation_weight"]) * f.conversation)
        add("engagement", w["engagement"] * engagement(f, self.eng))
        add("s_meaningful", w["s_meaningful"] * p.score_meaningful)
        add("s_like", w["s_like"] * p.score_like)
        add("s_comment", w["s_comment"] * p.score_comment)
        add("s_share", w["s_share"] * p.score_share)
        add("s_save", w["s_save"] * p.score_save)
        if p.score_complete is not None:
            add("s_complete", w["s_complete"] * p.score_complete)
        add("interest", w["interest"] * p.interest_rel)
        if f.media_quality is not None:
            add("quality", w["quality"] * f.media_quality)
        add("originality", w["originality"] * self.orig["reshare" if f.is_reshare else "original"])
        add("negative", -(w["negative"] * p.score_negative))

        value = 0.0
        for i, (_, amount) in enumerate(terms):
            # Same accumulation as today's ``value = a; value += b; value -= c``: a
            # dislike is subtracted, so its float rounding matches.
            if i == 0:
                value = amount
            elif terms[i][0] in ("dislike", "negative"):
                value -= -amount
            else:
                value += amount
        for name, mult in self._multipliers(f):
            terms.append((name, value * (mult - 1.0)))
            value *= mult
        return Scored(f, p, value, terms)

    def _multipliers(self, f: CandidateFeatures) -> list[tuple[str, float]]:
        b = self.integrity
        out = []
        if f.moderation_open or f.pending_reports >= b["pending_report_min_reporters"]:
            out.append(("pending_reports", b["pending_report_multiplier"]))
        if f.duplicate:
            out.append(("duplicate", b["duplicate_multiplier"]))
        if integrity.is_bait(f.bait_score, b):
            out.append(("bait", b["bait_multiplier"]))
        if (
            f.flags >= b["spam_flag_min_flags"]
            and f.flags / max(f.reach, 1) > b["spam_flag_rate_threshold"]
        ):
            out.append(("spam_flags", b["spam_flag_multiplier"]))
        return [(n, m) for n, m in out if m != 1.0]
