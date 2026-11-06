"""WP 6.3 / 6.3-B2: the interest tiers in the 60 s aggregator (``interests_agg``).

An impression adds 0; a like adds its weight x the topic confidence on each topic,
and its weight on the creator, format and language; a skip is weak and negative;
decay follows the half-lives; an ineligible (flagged) row is ignored; every row is
applied exactly once (a tick run twice, a watermark kept in SQL); group join raises
``group_cat``; personalization_off, rows before ``reset_at`` and synthetic actors
are skipped."""

from datetime import timedelta

import pytest
from django.utils import timezone

from intel import config
from intel.models import SignalFlag, SyntheticAccount, UserInterest, UserPreference
from intel.signals import interests_agg, store

from . import r4
from . import world as w

pytestmark = pytest.mark.django_db
OVERLAP = timedelta(minutes=2)


class Clock:
    """Rows at ``t`` and ticks 3 minutes later, always after the last tick's window."""

    def __init__(self):
        self.t = timezone.now() - timedelta(hours=2)

    def step(self, minutes=5):
        self.t += timedelta(minutes=minutes)
        return self.t


CLOCK = Clock()


def _row(account, event_type, item, *, item_type="post", author=None, at=None, **kw):
    at = at or CLOCK.step()
    store.insert_row(
        store.SignalRow(
            account_id=account,
            event_type=event_type,
            item_type=item_type,
            item_id=item,
            author_id=author,
            source="bus",
            data_origin=kw.pop("origin", "real"),
            occurred_at=at,
            received_at=at,
            **kw,
        )
    )


def _run(now=None):
    now = now or CLOCK.t + timedelta(minutes=3)
    return interests_agg.aggregate(now, OVERLAP, config.for_surface("home"))


def _value(account, dim, key, tier="long_v"):
    row = UserInterest.objects.filter(
        account_id=account, dim=dim, key=str(key), source="inferred"
    ).first()
    return None if row is None else getattr(row, tier)


@pytest.fixture
def ids():
    return r4.seed()


def test_impression_adds_nothing_a_like_adds_its_weight(ids):
    viewer, author = w.uid(), w.uid()
    p = w.post(author, type="image", lang="ar")
    r4.tag(p, (ids["cooking"], 0.9), (ids["food"], 0.6))
    _row(viewer, "feed_impression", p, author=author)
    _run()
    assert not UserInterest.objects.filter(account_id=viewer).exists()
    _row(viewer, "post_like", p, author=author)
    _run()
    assert _value(viewer, "topic", ids["cooking"]) == pytest.approx(0.9, rel=1e-3)
    assert _value(viewer, "topic", ids["food"]) == pytest.approx(0.6, rel=1e-3)
    assert _value(viewer, "creator", author) == pytest.approx(1.0, rel=1e-3)
    assert _value(viewer, "format", "image") == pytest.approx(1.0, rel=1e-3)
    assert _value(viewer, "lang", "ar") == pytest.approx(1.0, rel=1e-3)
    row = UserInterest.objects.get(account_id=viewer, dim="topic", key=str(ids["cooking"]))
    assert row.counts == {"post_like": 1} and row.events_n == 1  # counts, never ids


def test_skip_is_weak_and_negative_and_decay_follows_half_lives(ids):
    viewer, author = w.uid(), w.uid()
    p = w.post(author, type="video")
    r4.tag(p, (ids["gaming"], 1.0))
    then = CLOCK.step()
    _row(viewer, "video_skip", p, item_type="video", author=author, at=then)
    _run(then + timedelta(days=3))
    CLOCK.t = then + timedelta(days=3)
    assert _value(viewer, "topic", ids["gaming"], "short_v") == pytest.approx(-0.15, rel=1e-2)
    assert _value(viewer, "topic", ids["gaming"], "long_v") == pytest.approx(
        -0.3 * 2 ** (-3 / 45), rel=1e-2
    )


def test_exactly_once_and_ineligible_rows_are_ignored(ids):
    viewer, author = w.uid(), w.uid()
    p = w.post(author)
    r4.tag(p, (ids["history"], 1.0))
    _row(viewer, "post_comment", p, author=author)
    _row(viewer, "post_comment", w.post(author), author=author, flags=SignalFlag.INELIGIBLE_ITEM)
    now = CLOCK.t + timedelta(minutes=3)
    first = _run(now)
    again = _run(now)
    assert first["events"] == 1 and again["events"] == 0
    assert _value(viewer, "topic", ids["history"]) == pytest.approx(2.0, rel=1e-3)
    assert _value(viewer, "creator", author) == pytest.approx(2.0, rel=1e-3)  # one comment


def test_a_late_row_inside_the_overlap_is_read_on_the_next_tick(ids):
    viewer, author = w.uid(), w.uid()
    p = w.post(author)
    r4.tag(p, (ids["travel"], 1.0))
    at = CLOCK.step()
    _row(viewer, "post_share", p, author=author, at=at)
    assert _run(at + timedelta(seconds=30))["events"] == 0  # still inside the overlap
    assert _run(at + timedelta(minutes=3))["events"] == 1


def test_group_join_raises_group_cat_and_its_topic(ids):
    viewer = w.uid()
    group = w.group()
    from intel.models import GroupRef

    GroupRef.objects.filter(group_id=group).update(category="sports")
    _row(viewer, "group_join", group, item_type="group")
    _run()
    assert _value(viewer, "group_cat", "sports") == pytest.approx(2.0, rel=1e-3)
    assert _value(viewer, "topic", ids["sports"]) == pytest.approx(2.0, rel=1e-3)
    _row(viewer, "group_leave", group, item_type="group")
    _run()
    assert _value(viewer, "group_cat", "sports") == pytest.approx(1.0, rel=1e-2)


def test_skips_personalization_off_reset_and_synthetic(ids):
    off, reset, seed, author = w.uid(), w.uid(), w.uid(), w.uid()
    p = w.post(author)
    r4.tag(p, (ids["music"], 1.0))
    UserPreference.objects.create(account_id=off, personalization_off=True)
    before = CLOCK.step()
    UserPreference.objects.create(account_id=reset, reset_at=before + timedelta(minutes=2))
    SyntheticAccount.objects.create(account_id=seed, label="seed-r4")
    for account in (off, reset):
        _row(account, "post_like", p, author=author, at=before)
    _row(seed, "post_like", p, author=author, origin="synthetic", at=before)
    _run(before + timedelta(minutes=3))
    assert not UserInterest.objects.filter(account_id__in=[off, reset, seed]).exists()
    # After its reset_at, the reset account's rows count again.
    _row(reset, "post_like", p, author=author)
    _run()
    assert _value(reset, "topic", ids["music"]) == pytest.approx(1.0, rel=1e-2)


def test_feedback_rows_are_not_counted_twice(ids):
    viewer, author = w.uid(), w.uid()
    p = w.post(author)
    r4.tag(p, (ids["books"], 1.0))
    _row(viewer, "not_interested", p, author=author)  # the feedback service applied it
    _run()
    assert not UserInterest.objects.filter(account_id=viewer).exists()
