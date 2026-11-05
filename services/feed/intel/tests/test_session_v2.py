"""WP 4.10: ranking session v2. Group and pull items survive to page 3, sessions of
two surfaces live side by side, an item deleted or blocked after page 1 is not
returned later, and a 1,050-item Home session fits in 26 KB."""

import pickle
import uuid
from datetime import timedelta

import pytest
from django.core.cache import caches
from django.urls import reverse
from django.utils import timezone

from intel import config, readmodels
from intel.ranking import session
from intel.tests import world as w

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def no_ads(monkeypatch):
    monkeypatch.setattr("feed.ads_client.feed_sponsored", lambda v: None)


@pytest.fixture
def home_v2():
    config.store.activate("home", 2, reason="session v2 test")


def _pages(client, limit=5):
    pages, cursor = [], None
    for _ in range(100):
        params = {"mode": "for_you", "limit": limit}
        if cursor:
            params["cursor"] = cursor
        body = client.get(reverse("feed:home-feed"), params).json()
        assert body["page"]["fallback"] is False
        pages.append(body["data"])
        cursor = body["page"]["next_cursor"]
        if not cursor:
            break
    return pages


def _world(viewer, groups=12, friends=6):
    """Group posts (pulled, no FeedItem) and connection posts, recent."""
    g = w.group(owner=w.uid())
    w.member(viewer, g)
    from feed.models import FeedItem

    from intel.models import ContentRef

    now = timezone.now()
    group_posts = []
    for i in range(groups):
        author = w.uid()
        pid = w.post(author, audience="group", group=g)
        ContentRef.objects.filter(post_id=pid).update(created_at=now - timedelta(minutes=3 * i + 1))
        group_posts.append((pid, author))
    conn = []
    for i in range(friends):
        author = w.uid()
        pid = w.post(author)
        at = now - timedelta(minutes=3 * i + 2)
        ContentRef.objects.filter(post_id=pid).update(created_at=at)
        FeedItem.objects.create(
            recipient_id=viewer,
            post_id=pid,
            author_id=author,
            reason="friend",
            snapshot={"type": "text"},
            post_created_at=at,
        )
        conn.append((pid, author))
    return group_posts, conn


def test_group_items_survive_to_page_3_and_later(client_for, home_v2):
    viewer = w.uid()
    group_posts, conn = _world(viewer)
    pages = _pages(client_for(viewer))
    assert len(pages) >= 3
    seen = [i["post_id"] for p in pages for i in p]
    assert len(seen) == len(set(seen)) == len(group_posts) + len(conn)
    later = [i for p in pages[2:] for i in p]
    assert any(i["source"] == "groups" for i in later)
    for item in later:
        if item["source"] == "groups":
            assert item["reason"] in ("group", "group_notify")
            assert set(item["snapshot"]) <= {
                "post_id",
                "author_id",
                "author_type",
                "type",
                "audience",
                "created_at",
            }
            assert "excerpt" not in item["snapshot"]


def test_a_post_deleted_or_blocked_after_page_1_is_not_returned(client_for, home_v2):
    viewer = w.uid()
    group_posts, conn = _world(viewer)
    client = client_for(viewer)
    first = client.get(reverse("feed:home-feed"), {"mode": "for_you", "limit": 5}).json()
    shown = {i["post_id"] for i in first["data"]}
    later_group = [(p, a) for p, a in group_posts if p not in shown]
    deleted, blocked = later_group[0], later_group[1]
    readmodels.content_deleted(deleted[0], timezone.now() + timedelta(seconds=1))
    readmodels.set_block(viewer, blocked[1], True, timezone.now())
    rest, cursor = [], first["page"]["next_cursor"]
    while cursor:
        body = client.get(
            reverse("feed:home-feed"), {"mode": "for_you", "limit": 5, "cursor": cursor}
        ).json()
        assert body["page"]["fallback"] is False
        rest += [i["post_id"] for i in body["data"]]
        cursor = body["page"]["next_cursor"]
    assert deleted[0] not in rest and blocked[0] not in rest
    assert len(shown) + len(rest) == len(group_posts) + len(conn) - 2


def test_a_hidden_connection_item_between_pages_is_dropped(client_for, home_v2):
    viewer = w.uid()
    _, conn = _world(viewer, groups=10, friends=8)
    client = client_for(viewer)
    first = client.get(reverse("feed:home-feed"), {"mode": "for_you", "limit": 5}).json()
    shown = {i["post_id"] for i in first["data"]}
    later = next(p for p, _ in conn if p not in shown)
    client.post(reverse("feed:hide"), {"post_id": later, "reason": "other"})
    rest = [i["post_id"] for p in _pages_from(client, first["page"]["next_cursor"]) for i in p]
    assert later not in rest


def _pages_from(client, cursor):
    out = []
    while cursor:
        body = client.get(
            reverse("feed:home-feed"), {"mode": "for_you", "limit": 5, "cursor": cursor}
        ).json()
        out.append(body["data"])
        cursor = body["page"]["next_cursor"]
    return out


def test_two_surfaces_keep_their_own_sessions(client_for):
    viewer = w.uid()
    _world(viewer, groups=0, friends=8)
    client = client_for(viewer)
    first = client.get(reverse("feed:home-feed"), {"mode": "for_you", "limit": 3}).json()
    home_key = session.key("home", viewer)
    stored = caches["hot"].get(home_key)
    assert stored and stored["v"] == 2 and stored["surface"] == "home"
    # A reels session (phase 5) for the same viewer lives under its own key.
    reels = {"sid": uuid.uuid4().hex, "items": session.pack([]), "n": 0, "edge": None}
    assert session.save("reels", viewer, reels, 60)
    assert caches["hot"].get(home_key) == stored  # opening reels left Home alone
    assert session.key("reels", viewer) != home_key
    body = client.get(
        reverse("feed:home-feed"),
        {"mode": "for_you", "limit": 3, "cursor": first["page"]["next_cursor"]},
    ).json()
    assert body["page"]["fallback"] is False and len(body["data"]) == 3


def test_a_cursor_of_another_surface_is_refused(client_for):
    from feed import ranking

    viewer = w.uid()
    token = ranking.encode_cursor({"k": "r", "s": "x", "o": 0, "a": "", "f": "reels"})
    resp = client_for(viewer).get(reverse("feed:home-feed"), {"mode": "for_you", "cursor": token})
    assert resp.status_code == 404


def test_packing_round_trips_and_takes_24_bytes_per_item():
    entries = [
        session.Entry(str(uuid.uuid4()), src, reason, ((1, 30), (2, -5), (8, 127)))
        for src, reason in [
            ("connections", "friend"),
            ("groups", "group_notify"),
            ("follow_pull", "capped"),
        ]
    ]
    raw = session.pack(entries)
    assert len(raw) == 3 * session.ITEM_BYTES == 72
    assert session.unpack(raw) == entries
    assert session.unpack(raw, 1, 2) == entries[1:2]
    # An unknown source or reason is stored as none, never guessed.
    odd = session.unpack(session.pack([session.Entry(entries[0].post_id, "elsewhere", "weird")]))
    assert (odd[0].source, odd[0].reason) == ("", "")


def test_a_1050_item_home_session_is_at_most_26_kb():
    entries = [
        session.Entry(str(uuid.uuid4()), "connections", "friend", ((1, 25), (2, 10), (8, 4)))
        for _ in range(1050)
    ]
    stored = {
        "sid": uuid.uuid4().hex,
        "surface": "home",
        "cfg": "home@2",
        "items": session.pack(entries),
        "n": 1050,
        "edge": [timezone.now().isoformat(), str(uuid.uuid4())],
        "v": session.VERSION,
    }
    size = len(pickle.dumps(stored, pickle.HIGHEST_PROTOCOL))  # what the Redis cache stores
    print("home session bytes", len(stored["items"]), "pickled", size)
    assert len(stored["items"]) == 25_200
    assert size <= 26 * 1024
