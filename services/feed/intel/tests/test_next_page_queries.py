"""WP 4.10: a ranked next page takes at most 5 queries (session read is Redis), with
connection and pulled items mixed on the page, whatever their number."""

from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from feed import ranking
from feed.models import FeedItem

from intel import config
from intel.models import ContentRef
from intel.tests import world as w

pytestmark = pytest.mark.django_db


def _world(viewer, n):
    g = w.group(owner=w.uid())
    w.member(viewer, g)
    now = timezone.now()
    for i in range(n):
        author = w.uid()
        if i % 2:
            pid = w.post(author, audience="group", group=g)
            ContentRef.objects.filter(post_id=pid).update(created_at=now - timedelta(minutes=i))
        else:
            pid = w.post(author)
            at = now - timedelta(minutes=i)
            ContentRef.objects.filter(post_id=pid).update(created_at=at)
            FeedItem.objects.create(
                recipient_id=viewer,
                post_id=pid,
                author_id=author,
                reason="friend",
                snapshot={"type": "text"},
                post_created_at=at,
            )


@pytest.mark.parametrize("size", [5, 40])
def test_next_page_takes_at_most_5_queries(size):
    config.store.activate("home", 2, reason="queries")
    viewer = w.uid()
    _world(viewer, 3 * size)
    first = ranking.first_page(viewer, size, timezone.now())
    assert first.next_cursor and not first.fallback
    config.for_surface("home")  # the config pointer is cached in steady state
    with CaptureQueriesContext(connection) as ctx:
        page = ranking.next_page(viewer, first.next_cursor, size)
    print("next page queries", size, len(ctx.captured_queries))
    assert len(ctx.captured_queries) <= 5
    assert len(page.items) == size
    assert {"connections", "groups"} <= set(page.sources)


def test_home_v1_next_page_is_within_the_budget_too():
    viewer = w.uid()
    _world(viewer, 30)
    first = ranking.first_page(viewer, 5, timezone.now())
    config.for_surface("home")
    with CaptureQueriesContext(connection) as ctx:
        page = ranking.next_page(viewer, first.next_cursor, 5)
    assert len(ctx.captured_queries) <= 5 and len(page.items) == 5
