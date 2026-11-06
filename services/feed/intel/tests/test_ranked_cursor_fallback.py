"""R3 WP A7 (4b.12-B3, 08 section 7.3): the ranked cursor and its fallback.

The ``for_you`` cursor carries the ranking session id (``s``), the frozen-list offset
(``o``), the config version (``v``) and the oldest ``(post_created_at, id)`` served
so far (``t``/``i``). When the session is lost (expiry, another tab's first page, or a
first page whose session write redis-hot refused under ``noeviction``), the page says
``fallback: true`` and continues chronologically strictly below ``(t, i)``: 0
duplicates by construction. While the session lives every frozen-list entry is
either served or dropped by a named rule, and short pages are refilled. A reload
during the visit serves the same frozen list again (scenario 5)."""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import timedelta

import pytest
from django.core.cache import caches
from django.utils import timezone
from feed import ranking, services
from feed.models import FeedItem

from intel import metrics
from intel.ranking import session as rank_session
from intel.tests import world as w

pytestmark = pytest.mark.django_db
SIZE = 5


@pytest.fixture(autouse=True)
def _no_ads(monkeypatch):
    monkeypatch.setattr("feed.ads_client.feed_sponsored", lambda v: None)


def _row(viewer, author, minutes_ago):
    post_id = str(uuid.uuid4())
    w_created = timezone.now() - timedelta(minutes=minutes_ago)
    from intel.models import ContentRef

    ContentRef.objects.create(
        post_id=post_id,
        author_id=author,
        author_type="user",
        type="text",
        audience="public",
        created_at=w_created,
        event_at=w_created,
    )
    return FeedItem.objects.create(
        recipient_id=viewer,
        post_id=post_id,
        author_id=author,
        reason="friend",
        snapshot={"post_id": post_id, "author_id": author, "type": "text"},
        post_created_at=w_created,
    )


def _world(n=90):
    viewer = w.uid()
    authors = [w.uid() for _ in range(12)]
    rows = [_row(viewer, authors[i % len(authors)], 3 + i * 7) for i in range(n)]
    return viewer, authors, rows


def _get(client, **params):
    resp = client.get("/api/v1/feed/", {"mode": "for_you", "limit": SIZE, **params})
    assert resp.status_code == 200, resp.content
    return resp.json()


def _crawl(client, viewer, authors, *, between=None, pages=15, first=None):
    """Up to ``pages`` pages; ``between(k)`` mutates the world before page k."""
    body = first or _get(client)
    seen, fallbacks = [i["post_id"] for i in body["data"]], [body["page"]["fallback"]]
    cursor = body["page"]["next_cursor"]
    for k in range(1, pages):
        if not cursor:
            break
        if between:
            between(k)
        body = _get(client, cursor=cursor)
        seen += [i["post_id"] for i in body["data"]]
        fallbacks.append(body["page"]["fallback"])
        cursor = body["page"]["next_cursor"]
    return seen, fallbacks


def _mutations(client, viewer, authors, rows):
    """Scenario 4: inserts, deletes and a hide between pages."""
    victims = iter(rows[::9])

    def between(k):
        _row(viewer, authors[k % len(authors)], -k)  # a new post above everything
        if k % 3 == 0:
            services.remove_post(str(next(victims).post_id))
        if k == 4:
            target = rows[40]
            assert (
                client.post(
                    "/api/v1/feed/hide/",
                    {"post_id": str(target.post_id), "reason": "not_interested"},
                ).status_code
                == 201
            )

    return between


def _no_duplicates(seen):
    dupes = [p for p, n in Counter(seen).items() if n > 1]
    assert not dupes, dupes


def test_a_live_session_serves_15_pages_without_duplicates(client_for):
    viewer, authors, rows = _world()
    client = client_for(viewer)
    seen, fallbacks = _crawl(
        client, viewer, authors, between=_mutations(client, viewer, authors, rows)
    )
    assert len(seen) >= 15 * SIZE - 5
    _no_duplicates(seen)
    assert not any(fallbacks)


@pytest.mark.parametrize("loss", ["expiry", "other_tab", "redis_restart"])
def test_a_lost_session_continues_below_t_min_without_duplicates(client_for, loss):
    viewer, authors, rows = _world()
    client = client_for(viewer)
    mutate = _mutations(client, viewer, authors, rows)
    lost_at = 5

    def between(k):
        mutate(k)
        if k == lost_at:
            if loss == "other_tab":
                other = client_for(viewer)
                _get(other, entry="load")  # replaces the session (a new sid)
            else:
                caches["hot"].delete(ranking._session_key(viewer))

    seen, fallbacks = _crawl(client, viewer, authors, between=between)
    _no_duplicates(seen)
    assert not any(fallbacks[:lost_at]) and fallbacks[lost_at] is True
    assert len(seen) >= 12 * SIZE


def test_an_oom_session_write_serves_the_head_and_falls_back(client_for, monkeypatch):
    viewer, authors, rows = _world()
    client = client_for(viewer)
    counted = []
    monkeypatch.setattr(metrics, "rank_session_oom", lambda: counted.append(1))
    hot = caches["hot"]
    real_set = hot.set

    def refuse(key, *a, **k):
        if key.startswith("feed:rank:"):
            raise RuntimeError("OOM command not allowed when used memory > 'maxmemory'.")
        return real_set(key, *a, **k)

    monkeypatch.setattr(hot, "set", refuse)
    first = _get(client, entry="load")
    assert counted == [1]
    assert first["page"]["fallback"] is True and len(first["data"]) == SIZE
    ranked_head = [i["post_id"] for i in first["data"]]
    seen, fallbacks = _crawl(
        client, viewer, authors, first=first, between=_mutations(client, viewer, authors, rows)
    )
    assert seen[:SIZE] == ranked_head
    _no_duplicates(seen)
    by_post = {str(r.post_id): r for r in rows}
    t_min = min((by_post[p].post_created_at, str(by_post[p].id)) for p in ranked_head)
    later = [by_post[p] for p in seen[SIZE:] if p in by_post]
    assert all((r.post_created_at, str(r.id)) < t_min for r in later)


def test_every_frozen_entry_is_served_or_dropped_by_a_named_rule(client_for):
    viewer, authors, rows = _world(40)
    client = client_for(viewer)
    first = _get(client, entry="load")
    session = rank_session.current("home", viewer, caches["hot"])
    total = session["n"]
    # Before page 2: hide 3 rows, delete 2, and block an author (E4).
    for r in rows[6:9]:
        client.post("/api/v1/feed/hide/", {"post_id": str(r.post_id), "reason": "not_interested"})
    for r in rows[12:14]:
        services.remove_post(str(r.post_id))
    w.block(viewer, authors[3])
    served = len(first["data"])
    dropped: Counter = Counter()
    cursor = first["page"]["next_cursor"]
    sid = session["sid"]
    while cursor:
        data = ranking.decode_cursor(cursor)
        if data["k"] != "r":
            break
        page = ranking.next_page(viewer, cursor, SIZE)
        assert page.sid == sid and not page.fallback
        served += len(page.items)
        dropped.update(page.dropped)
        # Refilled: a page is short only at the end of the list.
        assert len(page.items) == SIZE or page.next_cursor is None
        cursor = page.next_cursor
    assert served + sum(dropped.values()) == total
    # Hidden, deleted and blocked rows leave the viewer's visible rows ("visible"; the
    # block is also rule E4 for the rows that still reach the re-check).
    assert set(dropped) <= {"visible", "E1", "E4", "E5"}
    assert sum(dropped.values()) >= 6


def test_a_reload_during_the_visit_reuses_the_frozen_list(client_for, monkeypatch):
    viewer, authors, rows = _world(30)
    client = client_for(viewer)
    a = _get(client, entry="load")
    session = rank_session.current("home", viewer, caches["hot"])
    _row(viewer, authors[0], -1)  # new content: never enters a frozen list
    b = _get(client, entry="reload")
    assert [i["post_id"] for i in b["data"]] == [i["post_id"] for i in a["data"]]
    assert rank_session.current("home", viewer, caches["hot"])["sid"] == session["sid"]
    assert ranking.decode_cursor(b["page"]["next_cursor"])["s"] == session["sid"]
    # A pull re-ranks: a new session, and the new post can come in.
    c = _get(client, entry="pull")
    assert rank_session.current("home", viewer, caches["hot"])["sid"] != session["sid"]
    assert ranking.decode_cursor(c["page"]["next_cursor"])["s"] != session["sid"]


def test_the_cursor_names_version_and_t_min(client_for):
    viewer, authors, rows = _world(20)
    body = _get(client_for(viewer))
    data = ranking.decode_cursor(body["page"]["next_cursor"])
    assert data["k"] == "r" and data["v"].startswith("home@") and data["t"] and data["i"]
    assert viewer not in body["page"]["next_cursor"]
