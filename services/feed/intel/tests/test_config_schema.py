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
