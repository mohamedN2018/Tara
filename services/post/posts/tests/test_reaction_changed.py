"""Tara Intelligence WP 2.6 (D8): a reaction-type change emits ``post.reaction.changed``.

Before this, switching like -> love changed post's per-type counts but told no
consumer, so feed's per-type counts drifted. A change notifies nobody, so
``post.reacted`` stays one per new reaction.
"""

import uuid

import pytest
from django.urls import reverse

from posts import services
from posts.models import PostReaction, PostReactionCount

from .event_schema import assert_all_valid, payloads

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _react(client, post_id, kind):
    return client.post(
        reverse("posts:post-reactions", args=[post_id]), {"type": kind}, format="json"
    )


def _counts(post) -> dict:
    return dict(
        PostReactionCount.objects.filter(post=post, count__gt=0).values_list("type", "count")
    )


def test_a_type_change_emits_one_event_with_both_types(client_for):
    author, me = _acct(), _acct()
    post = services.create_post(author, body="hi", audience="public")
    client = client_for(me)
    assert _react(client, post.id, "like").status_code == 200
    assert _react(client, post.id, "love").status_code == 200
    assert _react(client, post.id, "love").status_code == 200  # same type: nothing changes
    assert _react(client, post.id, "haha").status_code == 200

    assert len(payloads("post.reacted")) == 1
    changes = payloads("post.reaction.changed")
    assert [(c["from_type"], c["to_type"]) for c in changes] == [("like", "love"), ("love", "haha")]
    assert changes[0] == {
        "post_id": str(post.id),
        "reactor": me,
        "author_id": author,
        "from_type": "like",
        "to_type": "love",
    }
    assert _counts(post) == {"haha": 1}
    assert assert_all_valid("post.reaction.changed") == 2


def test_the_concurrent_first_reaction_path_also_emits(client_for, monkeypatch):
    """Two first reactions at once: the loser is treated as a change, and says so."""
    author, me = _acct(), _acct()
    post = services.create_post(author, body="hi", audience="public")
    PostReaction.objects.create(post=post, account_id=me, type="like")
    PostReactionCount.objects.create(post=post, type="like", count=1)
    real = PostReaction.objects.select_for_update

    class Missing:
        """The first lookup sees nothing (the other request has not committed)."""

        def __init__(self):
            self.calls = 0

        def __call__(self):
            self.calls += 1
            qs = real()
            return qs.none() if self.calls == 1 else qs

    monkeypatch.setattr(PostReaction.objects, "select_for_update", Missing())
    services.react(me, str(post.id), "wow")
    assert [(c["from_type"], c["to_type"]) for c in payloads("post.reaction.changed")] == [
        ("like", "wow")
    ]
    assert _counts(post) == {"wow": 1}
    assert_all_valid("post.reaction.changed")


def test_no_event_without_a_change(client_for):
    post = services.create_post(_acct(), body="hi", audience="public")
    client = client_for(_acct())
    _react(client, post.id, "like")
    client.delete(reverse("posts:post-reactions", args=[post.id]))
    assert payloads("post.reaction.changed") == []
