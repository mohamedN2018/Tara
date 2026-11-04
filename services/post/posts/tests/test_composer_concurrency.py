"""Two workers publishing scheduled posts at once (2C): each post goes out once.

Run as two real transactions on two connections: the first worker takes the due
rows and stays open; the second runs meanwhile and must skip them (SKIP LOCKED),
not wait and not publish them again.
"""

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from posts import composer, services
from posts.models import OutboxEvent, Post
from posts.tests.test_concurrency import _race

pytestmark = pytest.mark.django_db(transaction=True)


def test_two_workers_publish_a_scheduled_post_once():
    author = str(uuid.uuid4())
    posts = [
        services.create_post(
            author,
            body=f"later {n}",
            state="scheduled",
            publish_at=timezone.now() + timedelta(minutes=5),
        )
        for n in range(3)
    ]
    due = timezone.now() + timedelta(minutes=10)

    out = _race(lambda: composer.publish_due(now=due), lambda: composer.publish_due(now=due))

    assert "second_error" not in out, out.get("second_error")
    assert out["first"] == 3
    assert out["second"] == 0  # the rows were locked: skipped, not published again
    assert composer.publish_due(now=due) == 0  # and a later tick finds nothing either
    assert set(Post.objects.values_list("state", flat=True)) == {"published"}
    created = OutboxEvent.objects.filter(event_type="post.created")
    assert sorted(e.payload["payload"]["post_id"] for e in created) == sorted(
        str(p.id) for p in posts
    )
