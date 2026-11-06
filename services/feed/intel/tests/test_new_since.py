"""R3 WP A5 (07 WP 4b.7, 06 section 6.2): "New since your last visit" and caught-up.

``recent`` (the default mode): the order is unchanged; after a +3 day jump with K new
eligible connected rows, ``meta.visit.anchor_index`` is K exactly and the caught-up
marker sits at the first row older than ``since``; a second open 45 minutes later
with no new rows gives ``new_count = 0`` (no divider); a row from a blocked author
changes neither ``new_count`` nor the ids. ``for_you`` under home@2c: every position
``i < min(new_count, 30)`` holds a new-since item or an item scored above the lowest
new-since item."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from feed import handlers
from feed.models import FeedItem, RelationshipFlag

from intel import config
from intel.eligibility import Viewer
from intel.models import RankingConfig
from intel.ranking import exposure_rank, home
from intel.tests import world as w
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _no_ads(monkeypatch):
    monkeypatch.setattr("feed.ads_client.feed_sponsored", lambda v: None)


class Clock:
    def __init__(self, monkeypatch, start):
        self.now = start
        monkeypatch.setattr("feed.views.clock.request_now", lambda request, account: self.now)

    def move(self, **kw):
        self.now += timedelta(**kw)


def _row(viewer, author, at, reason="friend"):
    post_id = str(uuid.uuid4())
    return FeedItem.objects.create(
        recipient_id=viewer,
        post_id=post_id,
        author_id=author,
        reason=reason,
        snapshot={"post_id": post_id, "author_id": author, "type": "text"},
        post_created_at=at,
    )


def _ids(body):
    return [i["post_id"] for i in body["data"]]


def test_recent_divider_sits_after_exactly_the_new_rows(client_for, redis_hot, monkeypatch):
    viewer, friend, other = w.uid(), w.uid(), w.uid()
    start = datetime.now(UTC).replace(microsecond=0)
    old = [_row(viewer, friend, start - timedelta(hours=h)) for h in range(1, 9)]
    clock = Clock(monkeypatch, start)
    client = client_for(viewer)
    a = client.get("/api/v1/feed/", {"mode": "recent"}).json()
    assert a["meta"]["visit"]["kind"] == "new" and a["meta"]["visit"]["new_count"] == 0
    golden = _ids(a)

    k = 4
    new = [
        _row(viewer, friend if i % 2 else other, start + timedelta(days=1, hours=i))
        for i in range(k)
    ]
    # A blocked author's row created after ``since`` (a fan-out racing the block).
    blocked = w.uid()
    w.block(viewer, blocked)
    _row(viewer, blocked, start + timedelta(days=2))

    clock.move(days=3)
    b = client.get("/api/v1/feed/", {"mode": "recent"}).json()
    visit = b["meta"]["visit"]
    assert visit["kind"] == "returning"
    assert visit["since"] == start.isoformat()
    assert visit["new_count"] == k and visit["anchor_index"] == k
    assert b["meta"]["caught_up_index"] == k
    ids = _ids(b)
    newest_first = sorted(new, key=lambda r: r.post_created_at, reverse=True)
    assert ids[:k] == [str(r.post_id) for r in newest_first]
    # Order unchanged: the old rows follow exactly as before.
    assert ids[k:] == golden[: len(ids) - k]
    assert all(str(r.post_id) in golden for r in old[: len(ids) - k])

    clock.move(minutes=45)
    c = client.get("/api/v1/feed/", {"mode": "recent"}).json()
    assert c["meta"]["visit"]["kind"] == "new"
    assert c["meta"]["visit"]["new_count"] == 0 and c["meta"]["visit"]["anchor_index"] is None
    assert c["meta"]["caught_up_index"] is None


def test_a_block_after_since_changes_neither_count_nor_ids(client_for, redis_hot, monkeypatch):
    viewer, friend, foe = w.uid(), w.uid(), w.uid()
    start = datetime.now(UTC).replace(microsecond=0)
    for h in range(1, 4):
        _row(viewer, friend, start - timedelta(hours=h))
    clock = Clock(monkeypatch, start)
    client = client_for(viewer)
    client.get("/api/v1/feed/", {"mode": "recent"})
    _row(viewer, friend, start + timedelta(hours=5))
    foe_row = _row(viewer, foe, start + timedelta(hours=6))
    clock.move(days=2)
    with_foe = client.get("/api/v1/feed/", {"mode": "recent"}).json()
    assert with_foe["meta"]["visit"]["new_count"] == 2
    handlers.on_user_blocked(
        EventEnvelope(
            event_type="user.blocked",
            subject_id=foe,
            payload={"blocker_id": viewer, "blocked_id": foe},
            producer="graph",
        )
    )
    w.block(viewer, foe)
    racing = _row(viewer, foe, start + timedelta(days=2, hours=1))  # a fan-out racing it
    clock.move(hours=26)
    after = client.get("/api/v1/feed/", {"mode": "recent"}).json()
    assert str(foe_row.post_id) not in _ids(after)
    assert str(racing.post_id) not in _ids(after)
    assert foe not in {i["author_id"] for i in after["data"]}
    # since = the previous visit's start (start + 2 d): only the blocked author posted
    # after it, so nothing new is counted.
    assert after["meta"]["visit"]["new_count"] == 0


@pytest.mark.parametrize("mode", ["following", "friends", "favorites"])
def test_every_chronological_mode_counts_its_own_rows(client_for, redis_hot, monkeypatch, mode):
    viewer, friend = w.uid(), w.uid()
    start = datetime.now(UTC).replace(microsecond=0)
    reason = "friend" if mode == "friends" else "follow"
    RelationshipFlag.objects.create(
        actor_id=viewer, target_id=friend, kind="favorite", active=True, occurred_at=start
    )
    _row(viewer, friend, start - timedelta(hours=1), reason)
    clock = Clock(monkeypatch, start)
    client = client_for(viewer)
    client.get("/api/v1/feed/", {"mode": mode})
    for i in range(3):
        _row(viewer, friend, start + timedelta(hours=1 + i), reason)
    clock.move(days=1, hours=1)
    body = client.get("/api/v1/feed/", {"mode": mode}).json()
    assert body["meta"]["visit"]["new_count"] == len(body["data"]) - 1 == 3


def _v2c():
    row = RankingConfig.objects.get(surface="home", note="home@2c")
    return config.for_version("home", row.version)


def test_for_you_new_since_block_leads_the_first_page():
    viewer = w.uid()
    since = w.NOW - timedelta(days=3)
    favorite = w.uid()
    RelationshipFlag.objects.create(
        actor_id=viewer, target_id=favorite, kind="favorite", active=True, occurred_at=w.NOW
    )
    for i in range(15):  # strong, older rows (a favorite author)
        w.feed_row(viewer, w.post(favorite, age=timedelta(days=3, hours=1 + i)), favorite)
    fresh = []
    for i in range(12):
        friend = w.uid()
        p = w.post(friend, age=timedelta(days=2, hours=i))
        w.feed_row(viewer, p, friend)
        fresh.append(p)
    cfg = _v2c()
    ctx = exposure_rank.Context(now=w.NOW, since=since)
    ranking = home.rank(Viewer(viewer), w.NOW, cfg, ctx)
    items = ranking.items
    new_ids = {s.feats.post_id for s in items if s.feats.created_at > since}
    assert new_ids == set(fresh)
    lowest = min(s.value for s in items if s.feats.post_id in new_ids)
    for i in range(min(len(new_ids), cfg.get("session.new_since.max_items"))):
        s = items[i]
        assert s.feats.post_id in new_ids or s.value > lowest, i
    assert ranking.exposure.new_since == len(fresh)
    assert all(
        any(name == exposure_rank.NEW_SINCE_REASON for name, _ in s.contributions)
        for s in items
        if s.feats.post_id in new_ids
    )
