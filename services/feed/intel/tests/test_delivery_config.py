"""WP 4c.2-B3 (08 sections 7.2 and 15.1): the ``delivery`` block of the central
config. Typed and strict like every block; it arrives with schema version 3, and a
version stored before it gets the block from the package defaults (``store.merge``),
so ``home@1`` stays active and unchanged while gaining ``delivery``."""

import copy

import pytest

from intel import config
from intel.config import schema, store
from intel.models import RankingConfig

pytestmark = pytest.mark.django_db

KEYS = {
    "first_page_size",
    "page_size",
    "prefetch_remaining_items",
    "prefetch_root_margin_vp",
    "media_warm_items",
    "media_resolve_window_ms",
    "virtualize_after_items",
    "keep_mounted_vp",
    "next_page_retries",
    "next_page_backoff_ms",
    "defer_rails_until_first_post",
    "defer_rails_max_ms",
    "reload_window_min",
    "reload_max_pages",
    "video",
    "impression",
}


def _problems(surface, mutate):
    params = store.defaults(surface)
    mutate(params["delivery"])
    return schema.validate(surface, params)


def test_schema_version_3_and_every_delivery_default_is_valid():
    assert schema.SCHEMA_VERSION >= 3  # 4 since R3 (exposure, rotation, revisit)
    for surface in schema.DELIVERY_SURFACES:
        params = store.defaults(surface)
        # Home is schema 4 since R3 (exposure, rotation, revisit); the others stay 3.
        assert params["schema_version"] == (4 if surface == "home" else 3)
        assert set(params["delivery"]) == KEYS, surface
        assert schema.validate(surface, params) == [], surface


def test_the_planned_values():
    home = store.defaults("home")["delivery"]
    assert (home["first_page_size"], home["page_size"]) == (10, 20)
    assert (home["prefetch_remaining_items"], home["prefetch_root_margin_vp"]) == (5, 2.5)
    assert (home["media_warm_items"], home["media_resolve_window_ms"]) == (6, 20)
    assert (home["virtualize_after_items"], home["keep_mounted_vp"]) == (40, 3)
    assert (home["next_page_retries"], home["next_page_backoff_ms"]) == (3, 1000)
    assert home["defer_rails_until_first_post"] is True and home["defer_rails_max_ms"] == 1500
    # Reload position (08 section 7.6): 30 minutes, at most 3 pages.
    assert (home["reload_window_min"], home["reload_max_pages"]) == (30, 3)
    assert home["video"] == {
        "autoplay": "muted_single",
        "min_visible": 0.6,
        "min_visible_ms": 300,
        "pause_below": 0.25,
        "load_margin_vp": 1.0,
        "unmount_beyond_vp": 3,
        "respect_save_data": True,
        "respect_reduced_motion": True,
    }
    assert home["impression"] == {
        "min_card_visible": 0.5,
        "min_viewport_cover": 0.5,
        "min_ms": 1000,
        "def_version": 2,
    }
    reels = store.defaults("reels")["delivery"]
    # page_size: the post reels pager's own page (``reels/views.py`` ReelPagination, 10).
    assert (reels["first_page_size"], reels["page_size"]) == (5, 10)
    video = store.defaults("video")["delivery"]
    # Recorded deviation: 20 + 20 keeps R1's "video pages full 20 + 20".
    assert (video["first_page_size"], video["page_size"]) == (20, 20)
    assert "delivery" not in store.defaults("groups")


@pytest.mark.parametrize(
    ("mutate", "problem"),
    [
        (lambda d: d.update(extra=1), "delivery.extra: unknown key"),
        (lambda d: d["video"].update(extra=1), "delivery.video.extra: unknown key"),
        (lambda d: d["impression"].update(extra=1), "delivery.impression.extra: unknown key"),
        (lambda d: d.update(first_page_size=0), "delivery.first_page_size: 0 out of range"),
        (lambda d: d.update(page_size=101), "delivery.page_size: 101 out of range"),
        (lambda d: d.update(page_size=2.5), "delivery.page_size: an integer is required"),
        (lambda d: d.update(keep_mounted_vp=0.5), "delivery.keep_mounted_vp: 0.5 out of range"),
        (lambda d: d.update(media_resolve_window_ms=201), "media_resolve_window_ms: 201"),
        (lambda d: d.update(defer_rails_max_ms=10_001), "defer_rails_max_ms: 10001"),
        (lambda d: d.update(reload_window_min=1_441), "reload_window_min: 1441"),
        (lambda d: d.update(reload_max_pages=11), "reload_max_pages: 11"),
        (lambda d: d.pop("reload_max_pages"), "delivery.reload_max_pages: required"),
        (lambda d: d.update(defer_rails_until_first_post=1), "true or false is required"),
        (lambda d: d["video"].update(autoplay="always"), "must be one of muted_single, click"),
        (lambda d: d["video"].update(min_visible=1.5), "delivery.video.min_visible: 1.5"),
        (lambda d: d["impression"].update(def_version=3), "def_version: 3 out of range"),
        (lambda d: d["impression"].update(min_ms=50), "min_ms: 50 out of range"),
        (lambda d: d.pop("impression"), "delivery.impression: required"),
        (lambda d: d["video"].pop("autoplay"), "delivery.video.autoplay: required"),
    ],
)
def test_unknown_keys_and_out_of_bounds_values_are_rejected(mutate, problem):
    problems = _problems("home", mutate)
    assert any(problem in p for p in problems), problems


def test_a_version_below_3_cannot_carry_delivery():
    params = store.defaults("home", 2)  # schema version 1, no delivery
    assert schema.validate("home", params) == []
    params["delivery"] = store.defaults("home")["delivery"]
    assert schema.validate("home", params) == ["delivery: needs schema_version 3"]
    with pytest.raises(schema.ConfigInvalid):
        store.create("home", params)
    params["schema_version"] = 3
    assert schema.validate("home", params) == []


def test_groups_has_no_delivery_block():
    params = store.defaults("groups")
    params["delivery"] = store.defaults("home")["delivery"]
    params["schema_version"] = 3
    assert "delivery: unknown section" in schema.validate("groups", params)


def test_a_stored_version_from_before_gets_the_block_from_the_defaults():
    """No new version is created or activated: an older stored version (here a
    draft without ``delivery``) resolves with the package block."""
    stored = store.defaults("home", 2)
    assert "delivery" not in stored
    draft = store.create("home", stored)
    row = RankingConfig.objects.get(surface="home", version=draft)
    assert "delivery" not in row.params
    assert (
        config.for_version("home", draft).section("delivery")
        == (store.defaults("home")["delivery"])
    )
    # The stored drafts of R1 (home@2b and its arms) too.
    for row in RankingConfig.objects.filter(surface="home"):
        merged = store.load("home", row.version)
        assert merged["delivery"] == row.params.get("delivery", store.defaults("home")["delivery"])


def test_the_active_versions_resolve_with_delivery_and_home_1_stays_active():
    store.clear_cache()
    assert config.for_surface("home").version == "home@1"
    assert config.delivery_for("home")["first_page_size"] == 10
    assert config.delivery_for("reels")["first_page_size"] == 5
    assert config.delivery_for("video")["page_size"] == 20


def test_delivery_for_is_the_validated_block_and_a_copy():
    block = config.delivery_for("home")
    assert block == store.defaults("home")["delivery"]
    assert set(block) == KEYS  # no server-only key to strip
    block["first_page_size"] = 99
    assert config.delivery_for("home")["first_page_size"] == 10


def test_the_home_ranking_blocks_are_untouched():
    """Adding ``delivery`` changed no ranking key of home@1 (the parity test runs the
    scorer; this checks the params)."""
    before = copy.deepcopy(store.defaults("home"))
    before.pop("delivery")
    before.pop("schema_version")
    stored = RankingConfig.objects.get(surface="home", version=1).params
    stored = {k: v for k, v in stored.items() if k not in ("delivery", "schema_version")}
    assert stored == before
