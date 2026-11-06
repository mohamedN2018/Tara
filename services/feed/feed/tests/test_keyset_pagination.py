"""WP 4c.8-B3 (08 section 7.3): the chronological modes page with a keyset over
``(post_created_at, id)``. Ties at a page boundary, inserts above the cursor,
deletes anywhere and a hide mid-scroll can neither skip nor repeat a row.
Everything goes through the real view."""

import uuid
from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from feed import views
from feed.models import FeedItem, FollowEdge, RelationshipFlag
from tara_common.pagination import CursorPagination, KeysetCursorPagination

pytestmark = pytest.mark.django_db
CHRONOLOGICAL = ("recent", "following", "friends", "favorites")


@pytest.fixture(autouse=True)
def no_ads(monkeypatch):
    monkeypatch.setattr("feed.ads_client.feed_sponsored", lambda v: None)


def _acct() -> str:
    return str(uuid.uuid4())


def _row(viewer, author, at, *, reason="follow") -> FeedItem:
    post_id = str(uuid.uuid4())
    return FeedItem.objects.create(
        recipient_id=viewer,
        post_id=post_id,
        author_id=author,
        reason=reason,
        snapshot={"post_id": post_id, "author_id": author, "audience": "public", "excerpt": "x"},
        post_created_at=at,
    )


class World:
    """A viewer whose rows all qualify for ``mode``."""

    def __init__(self, mode: str):
        self.viewer, self.author, self.mode = _acct(), _acct(), mode
        self.reason = "friend" if mode == "friends" else "follow"
        now = timezone.now()
        if mode in ("following", "favorites"):
            FollowEdge.objects.create(
                follower_id=self.viewer, target_id=self.author, occurred_at=now
            )
        if mode == "favorites":
            RelationshipFlag.objects.create(
                actor_id=self.viewer, target_id=self.author, kind="favorite", occurred_at=now
            )

    def row(self, at) -> FeedItem:
        return _row(self.viewer, self.author, at, reason=self.reason)


def _page(client, mode, cursor=None, **params):
    params = {"mode": mode, **params}
    if cursor:
        params["cursor"] = cursor
    resp = client.get(reverse("feed:home-feed"), params)
    assert resp.status_code == 200, resp.content
    return resp.json()


def _crawl(client, mode, *, limit, between=None, max_pages=60):
    """Every page until the end. ``between(n, served)`` runs after page ``n``."""
    pages, cursor = [], None
    for n in range(max_pages):
        body = _page(client, mode, cursor, limit=limit)
        pages.append([i["post_id"] for i in body["data"]])
        assert body["page"]["prev_cursor"] is None
        cursor = body["page"]["next_cursor"]
        assert body["page"]["has_more"] is (cursor is not None)
        if not cursor:
            return pages
        if between:
            between(n, [p for page in pages for p in page])
    raise AssertionError("the feed never ended")


def _expected_order(rows):
    return [
        str(r.post_id) for r in sorted(rows, key=lambda r: (r.post_created_at, r.id), reverse=True)
    ]


# ---- (a) ties at a page boundary ------------------------------------------------


def test_five_tied_rows_straddling_a_boundary_are_served_once_each(client_for):
    world = World("recent")
    base = timezone.now() - timedelta(hours=1)
    tied = base.replace(microsecond=123456)
    rows = [world.row(base + timedelta(minutes=m)) for m in (2, 1)]
    rows += [world.row(tied) for _ in range(5)]
    rows += [world.row(base - timedelta(minutes=m)) for m in (1, 2)]
    pages = _crawl(client_for(world.viewer), "recent", limit=3)
    served = [p for page in pages for p in page]
    # The first page ends inside the tie group (rows 2 to 6), and so does the second.
    assert [len(p) for p in pages] == [3, 3, 3]
    assert served == _expected_order(rows)
    assert len(served) == len(set(served)) == 9  # 0 repeated, 0 skipped


def test_a_tied_row_deleted_or_added_between_pages_shifts_nothing(client_for):
    world = World("recent")
    tied = (timezone.now() - timedelta(hours=1)).replace(microsecond=0)
    rows = [world.row(tied) for _ in range(6)]
    client = client_for(world.viewer)
    first = _page(client, "recent", limit=3)
    seen = [i["post_id"] for i in first["data"]]
    # Delete a served tied row and add a newer row: the keyset does not move.
    FeedItem.objects.filter(post_id=seen[0]).delete()
    world.row(timezone.now())
    second = _page(client, "recent", first["page"]["next_cursor"], limit=3)
    seen += [i["post_id"] for i in second["data"]]
    assert seen == _expected_order(rows)


# ---- (b) 15 pages in every chronological mode with inserts, deletes and a hide ----


@pytest.mark.parametrize("mode", CHRONOLOGICAL)
def test_fifteen_pages_with_churn_have_no_duplicate_and_miss_nothing(client_for, mode):
    world = World(mode)
    client = client_for(world.viewer)
    base = timezone.now() - timedelta(days=1)
    # 80 rows in groups of 3 equal timestamps, so many page boundaries fall in a tie.
    old = [world.row(base - timedelta(minutes=i // 3)) for i in range(80)]
    by_id = {str(r.post_id): r for r in old}
    deleted_unserved: set[str] = set()
    deleted_served: set[str] = set()
    hidden: set[str] = set()
    inserted: set[str] = set()

    def churn(n, served):
        served_set = set(served)
        # Newer rows (above the cursor) arrive on every page.
        inserted.add(str(world.row(timezone.now()).post_id))
        # A served row is deleted ...
        victim = next((p for p in served if p in by_id and p not in deleted_served), None)
        if victim:
            FeedItem.objects.filter(post_id=victim).delete()
            deleted_served.add(victim)
        # ... and one not served yet.
        unserved = [
            p
            for p in by_id
            if p not in served_set and p not in deleted_unserved and p not in hidden
        ]
        if len(unserved) > 2:
            victim = unserved[len(unserved) // 2]
            FeedItem.objects.filter(post_id=victim).delete()
            deleted_unserved.add(victim)
            if n == 6:  # one hide mid-scroll
                target = unserved[0]
                resp = client.post(
                    reverse("feed:hide"), {"post_id": target, "reason": "not_interested"}
                )
                assert resp.status_code == 201, resp.content
                hidden.add(target)

    pages = _crawl(client, mode, limit=4, between=churn)
    served = [p for page in pages for p in page]
    assert len(pages) >= 15
    assert len(deleted_unserved) >= 14 and len(hidden) == 1
    assert len(served) == len(set(served))  # 0 duplicates across pages
    assert not set(served) & inserted  # newer rows wait for the pill, never shift a page
    # Every surviving pre-existing row exactly once, and nothing deleted or hidden
    # before its turn (a row deleted after it was served was served first).
    assert set(served) == set(by_id) - deleted_unserved - hidden
    # In keyset order.
    assert served == [p for p in _expected_order(old) if p in set(served)]


# ---- (c) the end ----------------------------------------------------------------


def test_has_more_is_false_on_the_last_page_and_an_exact_fit_has_no_extra_page(client_for):
    world = World("recent")
    base = timezone.now() - timedelta(hours=2)
    for m in range(6):
        world.row(base - timedelta(minutes=m))
    client = client_for(world.viewer)
    first = _page(client, "recent", limit=3)
    assert first["page"]["has_more"] is True
    last = _page(client, "recent", first["page"]["next_cursor"], limit=3)
    assert len(last["data"]) == 3
    assert last["page"] == {"next_cursor": None, "prev_cursor": None, "has_more": False}


def test_an_unreadable_cursor_is_404(client_for):
    world = World("recent")
    world.row(timezone.now())
    client = client_for(world.viewer)
    for bad in ("garbage", "eyJrIjoidCIsInQiOiJ4IiwiaSI6InkifQ"):  # 2nd: {"k":"t","t":"x","i":"y"}
        resp = client.get(reverse("feed:home-feed"), {"mode": "recent", "cursor": bad})
        assert resp.status_code == 404, bad


# ---- (d) no more queries than today; legacy cursors ------------------------------


class _Legacy(CursorPagination):
    """Today's paginator (before WP 4c.8-B3), for the query budget and in-flight cursors."""

    ordering = "-post_created_at"


def test_a_next_page_costs_no_more_queries_than_today(client_for, monkeypatch):
    world = World("recent")
    base = timezone.now() - timedelta(hours=3)
    for m in range(30):
        world.row(base - timedelta(minutes=m // 2))
    client = client_for(world.viewer)

    def next_page_queries():
        first = _page(client, "recent", limit=10)
        with CaptureQueriesContext(connection) as ctx:
            _page(client, "recent", first["page"]["next_cursor"], limit=10)
        return len(ctx.captured_queries)

    monkeypatch.setattr(views.HomeFeedView, "pagination_class", _Legacy)
    today = next_page_queries()
    monkeypatch.undo()
    assert views.HomeFeedView.pagination_class is views.FeedCursorPagination
    assert next_page_queries() <= today


def test_a_next_page_range_scans_the_index_from_the_cursor(client_for):
    """The page query bounds ``post_created_at <= t`` as well as the keyset OR, so
    the index starts at the cursor instead of filtering every row above it (deep
    pages cost the same as page 2)."""
    world = World("recent")
    base = timezone.now() - timedelta(hours=3)
    for m in range(12):
        world.row(base - timedelta(minutes=m))
    client = client_for(world.viewer)
    first = _page(client, "recent", limit=5)
    with CaptureQueriesContext(connection) as ctx:
        _page(client, "recent", first["page"]["next_cursor"], limit=5)
    page_sql = [q["sql"] for q in ctx.captured_queries if 'FROM "feed_item"' in q["sql"]]
    assert any('"feed_item"."post_created_at" <= ' in sql for sql in page_sql), page_sql


def test_a_cursor_issued_before_the_switch_continues_without_repeats(client_for, monkeypatch):
    world = World("recent")
    tied = (timezone.now() - timedelta(hours=1)).replace(microsecond=0)
    rows = [world.row(tied - timedelta(minutes=m // 4)) for m in range(12)]
    client = client_for(world.viewer)
    monkeypatch.setattr(views.HomeFeedView, "pagination_class", _Legacy)
    old = _page(client, "recent", limit=5)  # an open tab, before the deploy
    monkeypatch.undo()
    served = [i["post_id"] for i in old["data"]]
    body = _page(client, "recent", old["page"]["next_cursor"], limit=5)
    served += [i["post_id"] for i in body["data"]]
    # The next cursor of that page is a keyset one.
    assert KeysetCursorPagination._read_keyset(body["page"]["next_cursor"]) is not None
    served += [p for page in _crawl_from(client, body["page"]["next_cursor"]) for p in page]
    assert served == _expected_order(rows)


def _crawl_from(client, cursor):
    pages = []
    while cursor:
        body = _page(client, "recent", cursor, limit=5)
        pages.append([i["post_id"] for i in body["data"]])
        cursor = body["page"]["next_cursor"]
    return pages
