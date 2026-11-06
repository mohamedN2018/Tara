"""WP 4b.1: the repetition harness's maths on fixtures (Jaccard, spreads, arrival, gaps,
diversity), and the harness's refusal to touch the live redis-hot database."""

import pytest
from django.core.management.base import CommandError

from intel import repetition
from intel.management.commands import intel_measure_repetition as cmd


def test_jaccard():
    assert repetition.jaccard([1, 2, 3], [1, 2, 3]) == 1.0
    assert repetition.jaccard([1, 2], [3, 4]) == 0.0
    assert repetition.jaccard([1, 2, 3, 4], [3, 4, 5, 6]) == pytest.approx(2 / 6)
    assert repetition.jaccard([], []) == 1.0  # two empty pages are the same page
    assert repetition.jaccard([1, 1, 2], [2]) == 0.5  # sets, not lists


def test_open_overlap_is_open_one_against_every_later_open():
    opens = [["a", "b"], ["a", "b"], ["a", "c"], ["d", "e"]]
    assert repetition.open_overlap(opens) == [1.0, pytest.approx(1 / 3), 0.0]
    assert repetition.open_overlap([["a"]]) == []


def test_percentiles_and_spread():
    vals = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert repetition.percentile(vals, 0.5) == 5.5
    assert repetition.percentile(vals, 0.1) == pytest.approx(1.9)
    assert repetition.percentile(vals, 0.9) == pytest.approx(9.1)
    assert repetition.percentile([], 0.5) is None
    assert repetition.percentile([7], 0.9) == 7.0
    s = repetition.spread(vals)
    assert (s["n"], s["min"], s["max"]) == (10, 1, 10)
    assert repetition.spread([]) == {
        "n": 0,
        "min": None,
        "p10": None,
        "p50": None,
        "p90": None,
        "max": None,
    }


def test_arrival_per_day_counts_recipient_days_and_daily_means():
    rows = [
        ("r1", "2026-11-03", 10),
        ("r1", "2026-11-04", 20),
        ("r2", "2026-11-05", 300),
        ("r3", "2026-11-05", 1),
    ]
    out = repetition.arrival_per_day(rows)
    assert out["recipients"] == 3
    assert out["recipient_days"]["n"] == 4
    assert out["recipient_days"]["p50"] == 15.0
    # r1's mean is 15/day, r2 300, r3 1.
    assert out["recipient_daily_mean"]["p50"] == 15.0
    assert out["recipient_daily_mean"]["max"] == 300.0


def test_visit_gaps_per_account():
    gaps = repetition.gaps_seconds({"a": [30, 10, 0], "b": [5], "c": [100, 160]})
    assert sorted(gaps) == [10, 20, 60]


def test_page_diversity():
    out = repetition.page_diversity(
        ["a", "a", "b", "a", "c"], ["text", "text", "text", "image", "image"]
    )
    assert out == {
        "items": 5,
        "distinct_authors": 3,
        "max_per_author": 3,
        "longest_format_run": 3,
    }
    assert repetition.longest_run([]) == 0
    assert repetition.share(3, 20) == 0.15 and repetition.share(1, 0) is None


def test_the_harness_never_uses_the_live_redis_hot(settings):
    settings.CACHES = {
        **settings.CACHES,
        "hot": {**settings.CACHES["hot"], "LOCATION": "redis://redis-hot:6379/0"},
    }
    assert cmd._hot_url(None) == "redis://redis-hot:6379/9"
    with pytest.raises(CommandError):
        cmd._hot_url("redis://redis-hot:6379/0")
    assert cmd._hot_url("redis://redis-hot:6379/11") == "redis://redis-hot:6379/11"


def test_the_selection_order_is_stable():
    ids = ["c", "a", "b"]
    assert cmd.stable_order(ids) == cmd.stable_order(list(reversed(ids)))


# ---- R3 WP A9: the simulated-display scenario ---------------------------------------


def test_repeat_rate():
    assert repetition.repeat_rate(["a", "b", "c", "d"], {"b", "d", "x"}) == 0.5
    assert repetition.repeat_rate([], {"a"}) is None


@pytest.mark.django_db
def test_an_invalid_override_is_refused():
    from intel.config import schema
    from intel.models import RankingConfig

    v = RankingConfig.objects.get(surface="home", note="home@2c").version
    with pytest.raises(schema.ConfigInvalid):
        cmd._variant_patch(f"home@{v}", {"exposure": {"m0": {"displayed": 7}}})
    with pytest.raises(CommandError):
        cmd._variant_patch(None, {"rotation": {"floor": 0.5}})


@pytest.mark.django_db
def test_the_simulation_rotates_page_one_and_leaves_no_row(settings):
    import io
    import json
    import os
    from datetime import timedelta

    from django.core.management import call_command
    from django.utils import timezone

    from intel.models import FeedSession, RankingConfig

    from . import world as w

    url = os.getenv("REDIS_URL", "")
    if not url.startswith("redis://"):
        pytest.skip("needs Redis (REDIS_URL)")
    base = url.rsplit("/", 1)[0]
    # The command swaps the hot cache's LOCATION for --hot-url: a Redis backend here.
    settings.CACHES = {
        **settings.CACHES,
        "hot": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": base + "/12",
            "KEY_PREFIX": "feed-test-harness",
        },
    }
    viewer = w.uid()
    for i in range(80):
        friend = w.uid()
        age = w.NOW - (timezone.now() - timedelta(hours=1, minutes=7 * i))
        w.feed_row(viewer, w.post(friend, age=age), friend)
    v = RankingConfig.objects.get(surface="home", note="home@2c").version
    out = io.StringIO()
    call_command(
        "intel_measure_repetition",
        "--variant",
        f"home@{v}",
        "--simulate-display",
        "--users",
        "1",
        "--modes",
        "",
        "--scan",
        "50",
        "--c-visits",
        "3",
        "--hot-url",
        base + "/13",
        stdout=out,
    )
    text = out.getvalue()
    result = json.loads(text[text.index("{") :])
    sim = result["simulate_display"]
    assert sim["users"] == 1
    assert sim["refresh_60s_jaccard"]["p50"] >= 0.9  # fetched is not seen
    assert sim["page1_jaccard_45min"]["p50"] <= 0.30  # rotation with 80 candidates
    assert sim["dwelled_from_a_in_b_45min"]["max"] <= 1
    assert sim["pre_score_ratio_45min_mean"] >= 0.8
    assert sim["first_page_writes"].get("2") is not None  # new visits wrote 2 rows
    assert result["residual_rows"] == {"intel_feed_session": 0, "intel_signal_event": 0}
    assert not FeedSession.objects.filter(account_id=viewer).exists()
    assert viewer not in text  # no account id in the output
