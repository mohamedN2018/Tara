"""WP 3.1: ``fan_out_post`` records a truncated fan-out for ``follow_pull`` (WP 3.4)."""

import uuid
from datetime import UTC, datetime

import pytest
from feed import services
from feed.models import FeedItem

from intel.models import FanoutCapped

from .helpers import acct

pytestmark = pytest.mark.django_db
T0 = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


@pytest.fixture
def followers(monkeypatch):
    people = [acct() for _ in range(6)]
    monkeypatch.setattr(
        services, "fanout_audience", lambda author, **kw: {"friends": [], "followers": people}
    )
    return people


def _post(author):
    return {
        "post_id": str(uuid.uuid4()),
        "author_id": author,
        "author_type": "user",
        "type": "text",
        "audience": "public",
        "excerpt": "hi",
        "media_ids": [],
        "created_at": T0.isoformat(),
    }


def test_a_truncated_fan_out_writes_one_row(settings, followers):
    settings.FANOUT_MAX_RECIPIENTS = 3
    author = acct()
    post = _post(author)
    services.fan_out_post(post)
    services.fan_out_post(post)  # a retry writes nothing more
    assert FeedItem.objects.filter(post_id=post["post_id"]).count() == 3
    row = FanoutCapped.objects.get()
    assert (str(row.post_id), str(row.author_id)) == (post["post_id"], author)
    assert (row.total, row.cap, row.audience) == (7, 3, "public")  # 6 followers + the author
    assert row.created_at == T0


def test_an_untruncated_fan_out_writes_none(settings, followers):
    settings.FANOUT_MAX_RECIPIENTS = 50
    services.fan_out_post(_post(acct()))
    assert not FanoutCapped.objects.exists()
