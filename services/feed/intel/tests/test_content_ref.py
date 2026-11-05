"""WP 2.7: hashtags survive into feed's snapshot (D7), with the excerpt's privacy rule.

``intel_content_ref`` (WP 3.1) reads them from the same events; until it exists the
feed snapshot is where hashtags live in ``feed_db``.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from feed import services
from feed.models import FeedItem

from .helpers import acct

pytestmark = pytest.mark.django_db
T0 = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


@pytest.fixture
def audience(monkeypatch):
    friend = acct()
    monkeypatch.setattr(
        services, "fanout_audience", lambda author, **kw: {"friends": [friend], "followers": []}
    )
    return friend


def _created(author, *, audience="public", hashtags=("cairo", "food")):
    post_id = str(uuid.uuid4())
    payload = {
        "post_id": post_id,
        "author_id": author,
        "author_type": "user",
        "type": "text",
        "audience": audience,
        "excerpt": "hello",
        "media_ids": [],
        "hashtags": list(hashtags),
        "created_at": T0.isoformat(),
    }
    return post_id, payload


def _snapshot(post_id, recipient):
    return FeedItem.objects.get(post_id=post_id, recipient_id=recipient).snapshot


def test_public_post_keeps_hashtags_for_everyone(audience):
    author = acct()
    post_id, payload = _created(author)
    services.fan_out_post(payload)
    assert _snapshot(post_id, author)["hashtags"] == ["cairo", "food"]
    assert _snapshot(post_id, audience)["hashtags"] == ["cairo", "food"]


def test_non_public_post_keeps_hashtags_for_the_author_only(audience):
    author = acct()
    post_id, payload = _created(author, audience="friends")
    services.fan_out_post(payload)
    assert _snapshot(post_id, author)["hashtags"] == ["cairo", "food"]
    assert "hashtags" not in _snapshot(post_id, audience)


def test_edit_replaces_hashtags(audience):
    author = acct()
    post_id, payload = _created(author)
    services.fan_out_post(payload)
    services.update_post_excerpt(
        post_id, "edited", "public", when=T0 + timedelta(minutes=1), hashtags=["nile"]
    )
    assert _snapshot(post_id, audience)["hashtags"] == ["nile"]
    # An edit that does not carry hashtags leaves them.
    services.update_post_excerpt(post_id, "again", None, when=T0 + timedelta(minutes=2))
    assert _snapshot(post_id, audience)["hashtags"] == ["nile"]


def test_edit_before_a_retried_creation_wins(audience):
    author = acct()
    post_id, payload = _created(author)
    services.update_post_excerpt(
        post_id, "edited", "public", when=T0 + timedelta(minutes=1), hashtags=["nile"]
    )
    services.fan_out_post(payload)  # the creation arrives late
    assert _snapshot(post_id, audience)["hashtags"] == ["nile"]


def test_hashtags_are_cleaned():
    snap = services._snapshot(
        {"post_id": "p", "author_id": "a", "hashtags": ["b", "a", "b", "", 3, None]}
    )
    assert snap["hashtags"] == ["a", "b"]
    assert services._snapshot({"post_id": "p", "author_id": "a"})["hashtags"] == []
