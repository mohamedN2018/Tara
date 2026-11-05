"""The groups rail's "last active" (plan 08, social shell):
GET /posts/groups/activity/?ids=..."""

import uuid

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from posts.models import BlockedPair, Post

from .test_groups import Group, _post, profile  # noqa: F401  (profile: autouse fixture)

pytestmark = pytest.mark.django_db

URL = "posts:group-activity"


def _activity(client, *groups_or_ids):
    ids = ",".join(g if isinstance(g, str) else g.id for g in groups_or_ids)
    return client.get(reverse(URL), {"ids": ids})


def _rows(resp) -> dict:
    assert resp.status_code == 200, resp.content
    return {r["group_id"]: r["last_post_at"] for r in resp.json()["data"]}


def test_newest_published_post_per_readable_group(client_for, profile):  # noqa: F811
    busy, quiet, private, hidden = (
        Group(profile),
        Group(profile, handle="quiet"),
        Group(profile, "private", handle="priv"),
        Group(profile, "hidden"),
    )
    member = busy.member()
    quiet.set(member, "member", "active")
    hidden_member = hidden.member()
    first = _post(client_for(member), busy, body="one").json()["data"]
    second = _post(client_for(member), busy, body="two").json()["data"]
    _post(client_for(hidden_member), hidden, body="secret")
    _post(client_for(private.owner), private, body="members only")

    rows = _rows(_activity(client_for(member), busy, quiet, private, hidden))
    # Private and hidden groups the viewer is not in are left out, not errors.
    assert set(rows) == {busy.id, quiet.id}
    assert rows[quiet.id] is None
    newest = Post.objects.get(id=second["id"]).created_at
    assert rows[busy.id] == newest.isoformat()
    assert Post.objects.get(id=first["id"]).created_at <= newest

    # A public group's activity is readable by anyone who may read its posts.
    assert set(_rows(_activity(client_for(str(uuid.uuid4())), busy))) == {busy.id}


def test_pending_deleted_and_blocked_authors_do_not_count(client_for, profile):  # noqa: F811
    group = Group(profile, post_approval=True)
    viewer, author = group.member(), group.member()
    _post(client_for(author), group, body="waiting")  # pending approval
    assert _rows(_activity(client_for(viewer), group)) == {group.id: None}

    group.update(post_approval=False)
    made = _post(client_for(author), group, body="live").json()["data"]
    assert _rows(_activity(client_for(viewer), group))[group.id] is not None

    BlockedPair.objects.create(blocker_id=viewer, blocked_id=author)
    assert _rows(_activity(client_for(viewer), group)) == {group.id: None}
    BlockedPair.objects.all().delete()

    Post.objects.filter(id=made["id"]).update(moderation_status=Post.ModerationStatus.REMOVED)
    assert _rows(_activity(client_for(viewer), group)) == {group.id: None}


def test_bad_or_too_many_ids_are_400_and_none_is_empty(client_for, profile):  # noqa: F811
    me = str(uuid.uuid4())
    assert _activity(client_for(me), "nope").status_code == 400
    many = [str(uuid.uuid4()) for _ in range(21)]
    assert _activity(client_for(me), *many).status_code == 400
    assert _rows(client_for(me).get(reverse(URL))) == {}
    # Unknown groups are simply absent.
    assert _rows(_activity(client_for(me), str(uuid.uuid4()))) == {}


def test_needs_sign_in():
    assert APIClient().get(reverse(URL)).status_code == 401
