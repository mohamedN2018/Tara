"""WP 6.3-B2: short (3 d), medium (14 d) and long (45 d) tiers, ``emerging`` at read
time, and the tier each row is listed under (06 section 7)."""

from datetime import timedelta

import pytest
from django.utils import timezone

from intel import config, interests

from . import r4

pytestmark = pytest.mark.django_db


def _block():
    return config.for_surface("home").section("interests")


def test_half_lives_decay_each_tier():
    now = timezone.now()
    row = r4.inferred(r4_acct(), "topic", 1, 8.0, at=now - timedelta(days=3))
    t = interests.tiers(row, now, _block())
    assert t["short"] == pytest.approx(4.0, rel=1e-6)  # one short half-life
    assert t["mid"] == pytest.approx(8.0 * 2 ** (-3 / 14), rel=1e-6)
    assert t["long"] == pytest.approx(8.0 * 2 ** (-3 / 45), rel=1e-6)


def test_a_topic_consumed_only_in_the_last_10_days_ranks_medium_over_long():
    """Backdated fixture (07 WP 6.3-B2): consumption only in the last 10 days, none in
    the last 8, lists the topic as medium: as a rate (value / half-life) the medium tier
    leads the long one, and the short one has decayed below it."""
    now = timezone.now()
    block = _block()
    row = r4.inferred(r4_acct(), "topic", 2, 0.0, at=now)
    row.short_v = row.mid_v = row.long_v = 0.0
    for days in (10, 9.5, 9, 8.5):  # four consumptions, 8.5 to 10 days ago
        _ = now - timedelta(days=days)  # the consumption time (decayed below)
        for tier in ("short", "mid", "long"):
            value = getattr(row, f"{tier}_v")
            setattr(
                row,
                f"{tier}_v",
                value + 2.0 * 2 ** (-(days) / block["half_life_d"][tier]),
            )
            setattr(row, f"{tier}_at", now)
    t = interests.tiers(row, now, block)
    hl = block["half_life_d"]
    rate = {k: t[k] / hl[k] for k in ("short", "mid", "long")}
    assert rate["mid"] > rate["long"] and rate["mid"] > rate["short"]
    assert interests.tier_of(t, 4, block) == "mid"


def test_emerging_needs_ratio_floor_and_events():
    block = _block()
    # As rates (value / half-life): short 3/3 = 1.0 against long 9/45 = 0.2, ratio 5.
    t = {"short": 3.0, "mid": 6.0, "long": 9.0}
    assert interests.is_emerging(t, 4, block) is True
    assert interests.is_emerging(t, 3, block) is False  # fewer than 4 events
    assert interests.is_emerging({**t, "long": 40.0}, 4, block) is False  # ratio 1.1 < 3
    assert interests.is_emerging({**t, "short": 1.4}, 9, block) is False  # below the floor
    assert interests.tier_of(t, 4, block) == "emerging"
    assert interests.tier_of({"short": -2, "mid": -1, "long": -1}, 5, block) == "negative"


def r4_acct():
    from .helpers import acct

    return acct()
