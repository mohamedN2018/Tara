"""``RulePredictor`` (02 section 15): transparent formulas, every coefficient and every
Beta prior read from the config's ``predictor`` block (no literal in this module but
the numerical guard ``_EPS``).

    base_k           = (count_k + a) / (reach + a + b)          Beta(a, b) per type
    score_like       = σ(logit(base_like) + c_aff·log1p(affinity) + c_int·interest_rel
                         + c_reason[reason])
    score_comment / score_share / score_save: the same shape with their counts
    score_meaningful = σ(logit(score_comment) + c_disc·discussion_depth + c_conv·conversation)
    score_complete   = (completions + a_d) / (starts + a_d + b_d)  (video, reel; the
                       prior of the item's duration bucket, so short clips are not favoured)
    score_negative   = σ(logit(base_hide) + c_dis·author_dislikes + c_neg·max(0, −interest_rel))

``reach`` is the fan-out recipient count until impressions are aggregated (WP 6.3):
a recipient is not a viewer, so these are **scores**, not probabilities. Saves,
completions and starts have no aggregated counts yet: they enter as 0, which leaves
the configured prior (a cold item scores exactly its prior).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from .base import Prediction

NAME = "rules@1"
_EPS = 1e-6  # keeps logit finite; not a ranking parameter


def sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def logit(p: float) -> float:
    p = min(max(p, _EPS), 1.0 - _EPS)
    return math.log(p / (1.0 - p))


def beta_mean(count: float, total: float, prior) -> float:
    a, b = float(prior[0]), float(prior[1])
    return (max(count, 0.0) + a) / (max(total, count, 0.0) + a + b)


def _priors(block: dict, kind: str) -> dict:
    priors = block["priors"]
    return {**priors["default"], **priors.get(kind, {})}


def duration_bucket(duration_ms: int | None, buckets: dict) -> str | None:
    """The largest bucket start (seconds) not above the duration."""
    if duration_ms is None or not buckets:
        return None
    seconds = duration_ms / 1000.0
    starts = sorted(int(k) for k in buckets)
    chosen = starts[0]
    for start in starts:
        if seconds >= start:
            chosen = start
    return str(chosen)


class RulePredictor:
    name = NAME

    def predict(self, viewer_id, feats: Sequence, cfg) -> list[Prediction]:
        block = cfg.section("predictor")
        c_reason = block["c_reason"]
        out = []
        for f in feats:
            pri = _priors(block, f.type)
            shift = (
                block["c_aff"] * math.log1p(f.affinity)
                + block["c_int"] * f.interest_rel
                + c_reason.get(f.reason, c_reason.get(f.source, 0.0))
            )

            def score(count, kind, shift=shift, f=f, pri=pri):
                return sigmoid(logit(beta_mean(count, f.reach, pri[kind])) + shift)

            s_like = score(f.reactions, "like")
            s_comment = score(f.comments, "comment")
            s_share = score(f.shares, "share")
            s_save = score(0, "save")  # no aggregated save counts yet (WP 6.3)
            s_meaningful = sigmoid(
                logit(s_comment)
                + block["c_disc"] * f.discussion_depth
                + block["c_conv"] * f.conversation
            )
            s_complete = None
            buckets = pri.get("complete_by_bucket_s") or {}
            bucket = duration_bucket(f.duration_ms, buckets)
            if bucket is not None:
                s_complete = beta_mean(0, 0, buckets[bucket])
            s_negative = sigmoid(
                logit(beta_mean(f.hides, f.reach, pri["hide"]))
                + block["c_dis"] * f.author_dislikes
                + block["c_neg"] * max(0.0, -f.interest_rel)
            )
            out.append(
                Prediction(
                    score_meaningful=s_meaningful,
                    score_like=s_like,
                    score_comment=s_comment,
                    score_share=s_share,
                    score_save=s_save,
                    score_complete=s_complete,
                    score_rewatch=None,
                    exp_watch_s=None,
                    score_negative=s_negative,
                    interest_rel=f.interest_rel,
                    predictor=NAME,
                    calibrated=False,
                )
            )
        return out
