"""WP 4.2: ``RulePredictor``: priors, monotonicity, a cold item scores its prior, and
every coefficient comes from the config's ``predictor`` block."""

import dataclasses
import math

import pytest

from intel import config
from intel.predictions import RulePredictor, for_config
from intel.predictions.rules import beta_mean, sigmoid
from intel.ranking.features import CandidateFeatures

BASE = CandidateFeatures(
    post_id="p",
    author_id="a",
    source="connections",
    reason="self",
    tie_id="p",
    created_at=None,
    age_h=1.0,
    type="text",
    lang="en",
    group_id=None,
    is_reshare=False,
    duplicate=False,
    bait_score=0.0,
    pending_reports=0,
    moderation_open=False,
    duration_ms=None,
    media_quality=None,
    has_stats=False,
    reactions=0,
    comments=0,
    shares=0,
    flags=0,
    stored_score=None,
    reach=0,
    hides=0,
    commenters=0,
    favorite=False,
    affinity=0,
    author_dislikes=0,
    shared_groups=0,
    conversation=0.0,
)


def _cfg(**predictor):
    cfg = config.from_params("home", {})
    if predictor:
        cfg = config.SurfaceConfig(
            "home",
            cfg.version,
            {**cfg.params, "predictor": {**cfg.params["predictor"], **predictor}},
        )
    return cfg


def _one(f, cfg=None):
    return RulePredictor().predict("v", [f], cfg or _cfg())[0]


def test_a_cold_item_scores_exactly_its_prior():
    cfg = _cfg()
    priors = cfg.get("predictor.priors.default")
    p = _one(BASE, cfg)  # reason self: c_reason 0, no affinity, no interest
    for kind, score in (
        ("like", p.score_like),
        ("comment", p.score_comment),
        ("share", p.score_share),
        ("save", p.score_save),
    ):
        a, b = priors[kind]
        assert score == pytest.approx(a / (a + b), abs=1e-9), kind
    assert p.score_negative == pytest.approx(priors["hide"][0] / sum(priors["hide"]), abs=1e-9)
    assert p.predictor == "rules@1" and p.calibrated is False
    assert p.score_complete is None  # not a video


def test_type_priors_override_the_default():
    image = _one(dataclasses.replace(BASE, type="image"))
    a, b = _cfg().get("predictor.priors.image.like")
    assert image.score_like == pytest.approx(a / (a + b), abs=1e-9)


@pytest.mark.parametrize(
    "field,score",
    [
        ("reactions", "score_like"),
        ("comments", "score_comment"),
        ("shares", "score_share"),
        ("affinity", "score_like"),
        ("commenters", "score_meaningful"),
        ("conversation", "score_meaningful"),
        ("hides", "score_negative"),
        ("author_dislikes", "score_negative"),
    ],
)
def test_more_evidence_moves_its_score_up(field, score):
    values = []
    for n in (0, 1, 5, 20):
        f = dataclasses.replace(BASE, reach=100, **{field: n})
        values.append(getattr(_one(f), score))
    assert values == sorted(values) and values[0] < values[-1], values


def test_more_reach_without_more_likes_moves_the_like_score_down():
    low = _one(dataclasses.replace(BASE, reactions=5, reach=10)).score_like
    high = _one(dataclasses.replace(BASE, reactions=5, reach=500)).score_like
    assert high < low


def test_every_score_is_in_0_1():
    f = dataclasses.replace(BASE, reactions=10_000, reach=10, affinity=10**6, hides=10**4)
    p = _one(f)
    for value in (p.score_like, p.score_comment, p.score_negative, p.score_meaningful):
        assert 0.0 <= value <= 1.0


def test_every_coefficient_is_read_from_the_config():
    f = dataclasses.replace(
        BASE,
        reason="friend",
        affinity=4,
        reach=50,
        reactions=5,
        commenters=2,
        conversation=1.0,
        author_dislikes=2,
        hides=1,
    )
    base = _one(f)
    for key, field in (
        ("c_aff", "score_like"),
        ("c_disc", "score_meaningful"),
        ("c_conv", "score_meaningful"),
        ("c_dis", "score_negative"),
    ):
        moved = _one(f, _cfg(**{key: 3.0}))
        assert getattr(moved, field) != getattr(base, field), key
    reasons = {**_cfg().get("predictor.c_reason"), "friend": 2.0}
    assert _one(f, _cfg(c_reason=reasons)).score_like > base.score_like
    priors = _cfg().get("predictor.priors")
    priors = {**priors, "default": {**priors["default"], "like": [10, 10]}}
    assert _one(f, _cfg(priors=priors)).score_like > base.score_like


def test_the_formula_is_the_documented_one():
    cfg = _cfg()
    f = dataclasses.replace(BASE, reason="friend", affinity=3, reach=40, reactions=4)
    a, b = cfg.get("predictor.priors.default.like")
    base = beta_mean(4, 40, (a, b))
    shift = cfg.get("predictor.c_aff") * math.log1p(3) + cfg.get("predictor.c_reason.friend")
    expected = sigmoid(math.log(base / (1 - base)) + shift)
    assert _one(f, cfg).score_like == pytest.approx(expected, rel=1e-12)


def test_video_completion_uses_the_duration_bucket_prior():
    cfg = _cfg()
    short = _one(dataclasses.replace(BASE, type="video", duration_ms=5_000), cfg)
    long = _one(dataclasses.replace(BASE, type="video", duration_ms=120_000), cfg)
    a0, b0 = cfg.get("predictor.priors.video.complete_by_bucket_s")["0"]
    a9, b9 = cfg.get("predictor.priors.video.complete_by_bucket_s")["90"]
    assert short.score_complete == pytest.approx(a0 / (a0 + b0))
    assert long.score_complete == pytest.approx(a9 / (a9 + b9))


def test_the_predictor_is_chosen_by_the_config():
    assert isinstance(for_config(_cfg()), RulePredictor)
