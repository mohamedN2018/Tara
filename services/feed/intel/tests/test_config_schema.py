"""WP 4.1: the ranking config schema rejects invalid params (02 section 8.2)."""

import copy

import pytest

from intel.config import schema, store


def _home():
    return store.defaults("home")


@pytest.mark.parametrize("surface", schema.SURFACES)
def test_every_shipped_default_is_valid(surface):
    assert schema.validate(surface, store.defaults(surface)) == []


def test_home_v2_is_valid():
    assert schema.validate("home", store.defaults("home", 2)) == []


def _problems(mutate):
    params = _home()
    mutate(params)
    return schema.validate("home", params)


def test_an_unknown_section_is_rejected():
    assert _problems(lambda p: p.update({"wieghts": {}})) == ["wieghts: unknown section"]


def test_an_unknown_key_is_rejected():
    problems = _problems(lambda p: p["weights"].update({"freshnes": 1.0}))
    assert problems == ["weights.freshnes: unknown key"]


@pytest.mark.parametrize("value", [10.5, -10.01, "3", None, True, float("nan")])
def test_a_weight_outside_minus_10_to_10_or_not_a_number_is_rejected(value):
    problems = _problems(lambda p: p["weights"].update({"freshness": value}))
    assert len(problems) == 1 and problems[0].startswith("weights.freshness")


@pytest.mark.parametrize("value", [0, -1, 0.0])
def test_a_half_life_must_be_positive(value):
    problems = _problems(lambda p: p["freshness"].update({"half_life_hours": value}))
    assert len(problems) == 1 and "freshness.half_life_hours" in problems[0]


def test_ratios_must_sum_to_one():
    problems = _problems(lambda p: p["diversity"]["sim_weights"].update({"author": 0.7}))
    assert problems == ["diversity.sim_weights: author + topics + type must sum to 1 (is 1.1)"]


def test_a_missing_required_block_is_rejected():
    problems = _problems(lambda p: p.pop("predictor"))
    assert problems == ["predictor: required"]


def test_a_multiplier_is_a_demotion_never_a_removal_or_a_boost():
    assert _problems(lambda p: p["integrity"].update({"duplicate_multiplier": 0}))
    assert _problems(lambda p: p["integrity"].update({"bait_multiplier": 1.2}))


def test_a_beta_prior_needs_two_positive_counts():
    assert _problems(lambda p: p["predictor"]["priors"]["default"].update({"like": [0, 20]}))
    assert _problems(lambda p: p["predictor"]["priors"]["default"].update({"like": [1]}))


def test_an_unknown_reason_or_source_is_rejected():
    assert _problems(lambda p: p["relationship"]["reason_prior"].update({"stranger": 1.0}))
    assert _problems(lambda p: p["ranking"].update({"sources": ["connections", "everything"]}))


def test_the_surface_must_match():
    params = _home()
    params["surface"] = "reels"
    assert "surface: must be one of" not in " ".join(schema.validate("home", params))
    assert any(p.startswith("surface:") for p in schema.validate("home", params))


def test_check_raises_with_every_problem():
    params = copy.deepcopy(_home())
    params["weights"]["freshness"] = 99
    params["freshness"]["half_life_hours"] = 0
    with pytest.raises(schema.ConfigInvalid) as exc:
        schema.check("home", params)
    assert len(exc.value.problems) == 2


def test_switches_that_are_not_built_yet_only_take_their_built_value():
    """No fake toggle: a value the code does not implement is rejected, not ignored."""
    from intel.config import schema as sch
    from intel.ranking import home as home_ranker

    for section, key, value in (
        ("modes", "recent_includes_groups", True),
        ("ads", "first_page_only", False),
    ):
        params = store.defaults("home")
        params.setdefault(section, {})[key] = value
        assert any(f"{section}.{key}" in p for p in sch.validate("home", params)), key
    params = store.defaults("home")
    params["ranking"]["sources"] = ["connections", "reels"]  # no home retriever for reels
    assert any("ranking.sources" in p for p in sch.validate("home", params))
    assert set(sch.HOME_SOURCES) == set(home_ranker.SOURCE_FUNCS)


# ---- schema version 2 (07 WP 4b.6, 4b.11) ---------------------------------------------


def _v2b():
    import json

    with (store.DEFAULTS_DIR / "home.v2b.json").open(encoding="utf-8") as fh:
        return json.load(fh)


def _v2b_problems(mutate):
    params = _v2b()
    mutate(params)
    return schema.validate("home", params)


def test_home_v2b_is_valid_and_carries_the_planned_values():
    params = _v2b()
    assert schema.SCHEMA_VERSION == 2
    assert schema.validate("home", params) == []
    assert params["schema_version"] == 2
    assert params["mix"] == {
        "recommended": 0.0,
        "thin_inventory": {"below_candidates": 60, "share": 0.1},
    }
    assert params["pools"]["popular"]["window_d"] == 7
    assert params["pools"]["fresh"]["max_age_h"] == 48
    assert (params["pools"]["rebuild_s"], params["pools"]["cap"]) == (300, 128)
    assert params["head"]["ttl_s"] == 8 * 24 * 3600
    # WP 4b.10: the diversity block of home@2 (max 2 per author, runs of 2 at most).
    assert params["diversity"] == store.defaults("home", 2)["diversity"]
    assert params["diversity"]["max_same_format_run"] == 2
    assert params["diversity"]["max_per_author_page"] == 2


def test_version_1_params_stay_valid_and_cannot_carry_version_2_blocks():
    assert schema.validate("home", store.defaults("home")) == []
    assert schema.validate("home", store.defaults("home", 2)) == []
    v1 = store.defaults("home", 2)
    v1["mix"] = _v2b()["mix"]
    v1["head"] = {"ttl_s": 3600}
    v1["pools"]["cap"] = 10
    assert schema.validate("home", v1) == [
        "mix: needs schema_version 2",
        "head: needs schema_version 2",
        "pools.cap: needs schema_version 2",
    ]


@pytest.mark.parametrize(
    ("mutate", "problem"),
    [
        (lambda p: p["mix"].update(recommended=1.5), "mix.recommended: 1.5 out of range"),
        (lambda p: p["mix"].update(recommended=-0.1), "mix.recommended: -0.1 out of range"),
        (
            lambda p: p["mix"]["thin_inventory"].update(share="0.1"),
            "mix.thin_inventory.share: a number is required",
        ),
        (lambda p: p["pools"].update(cap=129), "pools.cap: 129 out of range"),
        (lambda p: p["pools"].update(max_members=0), "pools.max_members: 0 out of range"),
        (lambda p: p["pools"].update(rebuild_s=10), "pools.rebuild_s: 10 out of range"),
        (
            lambda p: p["pools"]["popular"].update(prior_hours=0),
            "pools.popular.prior_hours: 0 out of range",
        ),
        (
            lambda p: p["pools"]["fresh"].update(min_score=2),
            "pools.fresh.min_score: 2 out of range",
        ),
        (lambda p: p["continuation"].update(pools="yes"), "continuation.pools: true or false"),
        (lambda p: p["head"].update(ttl_s=10), "head.ttl_s: 10 out of range"),
    ],
)
def test_version_2_bounds(mutate, problem):
    problems = _v2b_problems(mutate)
    assert any(x.startswith(problem) for x in problems), problems


def test_version_2_still_rejects_unknown_keys():
    assert _v2b_problems(lambda p: p["mix"].update(recomended=0.1)) == [
        "mix.recomended: unknown key"
    ]
    assert _v2b_problems(lambda p: p["pools"]["popular"].update(windowd=7)) == [
        "pools.popular.windowd: unknown key"
    ]
    assert _v2b_problems(lambda p: p.update(trending={})) == ["trending: unknown section"]


def test_the_discovery_source_needs_its_retriever_blocks():
    def drop(p):
        del p["mix"]
        del p["pools"]["popular"]

    problems = _v2b_problems(drop)
    assert "pools.popular: required with the discovery source" in problems
    assert "mix: required with the discovery source" in problems
    # Without the source, the blocks are optional (the pools are simply not read).
    params = _v2b()
    params["ranking"]["sources"].remove("discovery")
    del params["mix"]
    assert schema.validate("home", params) == []


def test_rec_reasons_are_known():
    assert {"rec_popular", "rec_fresh"} <= set(schema.REASONS)
    assert _v2b_problems(lambda p: p["predictor"]["c_reason"].update(rec_trending=0.1)) == [
        "predictor.c_reason.rec_trending: unknown key"
    ]


@pytest.mark.django_db
def test_the_migration_stored_the_three_variants_as_drafts():
    from intel.models import RankingConfig, RankingConfigChange

    rows = {
        r.note: r
        for r in RankingConfig.objects.filter(
            surface="home", note__in=["home@2b", "home@2b-r15", "home@2b-r30"]
        )
    }
    assert set(rows) == {"home@2b", "home@2b-r15", "home@2b-r30"}
    assert sorted(r.version for r in rows.values()) == [3, 4, 5]
    assert {r.status for r in rows.values()} == {"draft"}
    shares = {
        k: (r.params["mix"]["recommended"], r.params["continuation"]["pools"])
        for k, r in rows.items()
    }
    assert shares == {
        "home@2b": (0.0, False),
        "home@2b-r15": (0.15, True),
        "home@2b-r30": (0.3, True),
    }
    for r in rows.values():
        assert schema.validate("home", r.params) == []
        assert RankingConfigChange.objects.filter(
            surface="home", to_version=r.version, action="created"
        ).exists()
    # Nothing was activated: home@1 is still today's feed.
    assert RankingConfig.objects.get(surface="home", status="active").version == 1
