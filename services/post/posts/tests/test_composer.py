"""Wave 2C: drafts, scheduling, people tags, location and feeling, top comments."""

import json
import os
import uuid
from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from posts import composer, handlers, services
from posts.clients import Relationship
from posts.models import BlockedPair, Comment, OutboxEvent, Post, PostSettings, PostTag
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db

SCHEMAS = "/opt/tara/libs/tara_events/tara_events/schemas"


def _acct() -> str:
    return str(uuid.uuid4())


def _create(client, **data):
    return client.post(reverse("posts:post-create"), {"body": "hi", **data}, format="json")


def _events(event_type: str, post_id=None) -> list[dict]:
    rows = [e.payload["payload"] for e in OutboxEvent.objects.filter(event_type=event_type)]
    return [p for p in rows if post_id is None or p.get("post_id") == str(post_id)]


def _friends_with(*pairs):
    friends = {frozenset(p) for p in pairs}
    return lambda a, b: Relationship(are_friends=frozenset((str(a), str(b))) in friends)


def _soon(seconds=120):
    return (timezone.now() + timedelta(seconds=seconds)).isoformat()


# ---- drafts ------------------------------------------------------------------------


def test_a_draft_is_seen_by_nobody_but_its_author(client_for):
    author, other = _acct(), _acct()
    resp = _create(client_for(author), body="secret draft", draft=True)
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["state"] == "draft"
    draft_id = data["id"]

    # Nothing announced: feed, search and notification never hear of it.
    assert _events("post.created") == []
    # Others: 404 everywhere, and never in a list.
    stranger = client_for(other)
    assert stranger.get(reverse("posts:post-detail", args=[draft_id])).status_code == 404
    assert stranger.get(reverse("posts:draft-detail", args=[draft_id])).status_code == 404
    batch = stranger.post(reverse("posts:post-batch"), {"ids": [draft_id]}, format="json")
    assert batch.json()["data"] == []
    timeline = stranger.get(reverse("posts:post-create"), {"author_id": author})
    assert timeline.json()["data"] == []
    assert stranger.get(reverse("posts:drafts")).json()["data"] == []
    assert stranger.post(reverse("posts:draft-publish", args=[draft_id])).status_code == 404
    assert stranger.delete(reverse("posts:draft-detail", args=[draft_id])).status_code == 404
    # The public API does not serve it to the author either: drafts have their own.
    mine = client_for(author)
    assert mine.get(reverse("posts:post-detail", args=[draft_id])).status_code == 404
    assert mine.delete(reverse("posts:post-detail", args=[draft_id])).status_code == 404
    listed = mine.get(reverse("posts:drafts")).json()["data"]
    assert [p["id"] for p in listed] == [draft_id]
    assert mine.get(reverse("posts:draft-detail", args=[draft_id])).status_code == 200


def test_a_draft_is_edited_then_published_once(client_for):
    author = _acct()
    client = client_for(author)
    draft_id = _create(client, body="first", draft=True).json()["data"]["id"]
    resp = client.patch(
        reverse("posts:draft-detail", args=[draft_id]),
        {"body": "second #tag", "location": "  Cairo   Tower ", "feeling": "happy"},
        format="json",
    )
    assert resp.status_code == 200, resp.json()
    assert resp.json()["data"]["location"] == "Cairo Tower"
    assert _events("post.updated") == []  # a draft emits nothing

    published = client.post(reverse("posts:draft-publish", args=[draft_id]))
    assert published.status_code == 200
    assert published.json()["data"]["state"] == "published"
    created = _events("post.created", draft_id)
    assert len(created) == 1
    assert created[0]["excerpt"] == "second #tag" and created[0]["hashtags"] == ["tag"]
    # A second publish (a double click, or the schedule) finds nothing.
    assert client.post(reverse("posts:draft-publish", args=[draft_id])).status_code == 404
    assert client.get(reverse("posts:post-detail", args=[draft_id])).status_code == 200
    assert client_for(_acct()).get(reverse("posts:post-detail", args=[draft_id])).status_code == 200
    assert client.get(reverse("posts:drafts")).json()["data"] == []


def test_deleting_a_draft_emits_nothing(client_for):
    author = _acct()
    client = client_for(author)
    draft_id = _create(client, draft=True).json()["data"]["id"]
    assert client.delete(reverse("posts:draft-detail", args=[draft_id])).status_code == 204
    assert client.get(reverse("posts:draft-detail", args=[draft_id])).status_code == 404
    assert OutboxEvent.objects.count() == 0


def test_a_draft_with_photos_binds_them_restricted(client_for, media_stub):
    author = _acct()
    media = media_stub.add(author)
    resp = _create(client_for(author), media_ids=[media], audience="public", draft=True)
    assert resp.status_code == 201
    assert media_stub.binds[-1]["restricted"] is True


def test_groups_have_no_drafts(client_for):
    resp = _create(client_for(_acct()), draft=True, group_id=_acct())
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "group_drafts_not_supported"


# ---- scheduling ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("delta", "code"),
    [(timedelta(minutes=-1), "publish_at_past"), (timedelta(days=76), "publish_at_too_far")],
)
def test_publish_at_must_be_ahead_and_within_75_days(client_for, delta, code):
    resp = _create(client_for(_acct()), publish_at=(timezone.now() + delta).isoformat())
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == code


def test_a_scheduled_post_is_hidden_until_the_beat_task_publishes_it(client_for):
    author = _acct()
    client = client_for(author)
    resp = _create(client, body="later", publish_at=_soon(120))
    assert resp.status_code == 201
    post_id = resp.json()["data"]["id"]
    assert resp.json()["data"]["state"] == "scheduled"
    scheduled = client.get(reverse("posts:drafts"), {"state": "scheduled"}).json()["data"]
    assert [p["id"] for p in scheduled] == [post_id]
    assert client.get(reverse("posts:drafts"), {"state": "draft"}).json()["data"] == []
    other = client_for(_acct())
    assert other.get(reverse("posts:post-detail", args=[post_id])).status_code == 404

    assert composer.publish_due() == 0  # not yet
    assert _events("post.created") == []

    later = timezone.now() + timedelta(minutes=3)
    assert composer.publish_due(now=later) == 1
    post = Post.objects.get(id=post_id)
    assert post.state == "published" and post.publish_at is None
    assert post.created_at == later  # published "now", not when it was written
    created = _events("post.created", post_id)
    assert len(created) == 1 and created[0]["created_at"] == later.isoformat()
    assert other.get(reverse("posts:post-detail", args=[post_id])).status_code == 200
    assert composer.publish_due(now=later) == 0  # once
    assert len(_events("post.created", post_id)) == 1


def test_a_scheduled_post_can_be_moved_back_to_drafts(client_for):
    client = client_for(_acct())
    post_id = _create(client, publish_at=_soon()).json()["data"]["id"]
    url = reverse("posts:draft-detail", args=[post_id])
    resp = client.patch(url, {"publish_at": None}, format="json")
    assert resp.json()["data"]["state"] == "draft"
    assert composer.publish_due(now=timezone.now() + timedelta(days=1)) == 0
    resp = client.patch(url, {"publish_at": _soon(600)}, format="json")
    assert resp.json()["data"]["state"] == "scheduled"
    past = (timezone.now() - timedelta(minutes=1)).isoformat()
    assert client.patch(url, {"publish_at": past}, format="json").status_code == 400


def test_a_scheduled_poll_starts_its_clock_when_published():
    author = _acct()
    post = services.create_post(
        author,
        body="pick one",
        poll={"options": ["a", "b"], "duration_hours": 24},
        state="scheduled",
        publish_at=timezone.now() + timedelta(hours=5),
    )
    later = timezone.now() + timedelta(hours=6)
    composer.publish_due(now=later)
    post.poll.refresh_from_db()
    assert abs((post.poll.closes_at - later) - timedelta(hours=24)) < timedelta(seconds=5)


# ---- people tags ----------------------------------------------------------------------


def test_tagging_a_friend_stores_the_tag(client_for, monkeypatch):
    author, friend = _acct(), _acct()
    monkeypatch.setattr("posts.services.get_relationship", _friends_with((author, friend)))
    resp = _create(client_for(author), tagged_ids=[friend, friend, author])
    assert resp.status_code == 201, resp.json()
    assert resp.json()["data"]["tagged_ids"] == [friend]  # de-duplicated, never yourself
    assert _events("post.created")[0]["tagged_ids"] == [friend]


def test_tagging_someone_blocked_either_way_is_refused(client_for, monkeypatch):
    author, blocker, blocked = _acct(), _acct(), _acct()
    monkeypatch.setattr(
        "posts.services.get_relationship",
        _friends_with((author, blocker), (author, blocked)),
    )
    BlockedPair.objects.create(blocker_id=blocker, blocked_id=author)
    BlockedPair.objects.create(blocker_id=author, blocked_id=blocked)
    for target in (blocker, blocked):
        resp = _create(client_for(author), tagged_ids=[target])
        assert resp.status_code == 400
        # The same answer as any refusal: a block is never revealed.
        assert resp.json()["error"]["code"] == "tag_not_allowed"
    assert Post.objects.count() == 0


def test_a_block_graph_knows_of_is_refused_too(client_for, monkeypatch):
    author, other = _acct(), _acct()
    monkeypatch.setattr(
        "posts.services.get_relationship",
        lambda a, b: Relationship(are_friends=True, blocked_either_way=True),
    )
    resp = _create(client_for(author), tagged_ids=[other])
    assert resp.status_code == 400 and resp.json()["error"]["code"] == "tag_not_allowed"


def test_who_can_tag_me_is_enforced(client_for, monkeypatch):
    author, friend, stranger = _acct(), _acct(), _acct()
    monkeypatch.setattr("posts.services.get_relationship", _friends_with((author, friend)))
    client = client_for(author)
    # The default is friends: a friend yes, a stranger no.
    assert _create(client, tagged_ids=[friend]).status_code == 201
    refused = _create(client, tagged_ids=[stranger])
    assert refused.status_code == 400 and refused.json()["error"]["code"] == "tag_not_allowed"
    # "everyone" lets a stranger tag; "nobody" stops even a friend.
    settings_url = reverse("posts:post-settings")
    assert client_for(stranger).get(settings_url).json()["data"] == {"who_can_tag": "friends"}
    resp = client_for(stranger).patch(settings_url, {"who_can_tag": "everyone"}, format="json")
    assert resp.json()["data"] == {"who_can_tag": "everyone"}
    assert _create(client, tagged_ids=[stranger]).status_code == 201
    client_for(friend).patch(settings_url, {"who_can_tag": "nobody"}, format="json")
    assert PostSettings.objects.get(account_id=friend).who_can_tag == "nobody"
    nobody = _create(client, tagged_ids=[friend])
    assert nobody.status_code == 400 and nobody.json()["error"]["code"] == "tag_not_allowed"
    bad = client_for(friend).patch(settings_url, {"who_can_tag": "anyone"}, format="json")
    assert bad.status_code == 400


def test_nobody_also_applies_when_editing_tags(client_for, monkeypatch):
    author, friend = _acct(), _acct()
    monkeypatch.setattr("posts.services.get_relationship", _friends_with((author, friend)))
    post_id = _create(client_for(author)).json()["data"]["id"]
    PostSettings.objects.create(account_id=friend, who_can_tag="nobody")
    resp = client_for(author).patch(
        reverse("posts:post-detail", args=[post_id]), {"tagged_ids": [friend]}, format="json"
    )
    assert resp.status_code == 400 and resp.json()["error"]["code"] == "tag_not_allowed"


def test_tags_are_capped(client_for, monkeypatch):
    monkeypatch.setattr("posts.services.get_relationship", lambda a, b: Relationship(True))
    resp = _create(client_for(_acct()), tagged_ids=[_acct() for _ in range(21)])
    assert resp.status_code == 400 and resp.json()["error"]["code"] == "too_many_tags"


def test_the_tagged_person_can_remove_their_tag(client_for, monkeypatch):
    author, friend = _acct(), _acct()
    monkeypatch.setattr("posts.services.get_relationship", _friends_with((author, friend)))
    post_id = _create(client_for(author), tagged_ids=[friend]).json()["data"]["id"]
    resp = client_for(friend).delete(reverse("posts:post-my-tag", args=[post_id]))
    assert resp.status_code == 204
    assert not PostTag.objects.filter(post_id=post_id).exists()


def _envelope(event_type: str, payload: dict) -> EventEnvelope:
    return EventEnvelope(
        event_type=event_type, subject_id=payload["post_id"], producer="post", payload=payload
    )


def test_tagged_people_are_notified_once_the_post_is_published(client_for, monkeypatch):
    author, friend, outsider = _acct(), _acct(), _acct()
    monkeypatch.setattr(
        "posts.services.get_relationship",
        _friends_with((author, friend), (author, outsider)),
    )
    client = client_for(author)
    data = _create(client, draft=True, tagged_ids=[friend], audience="friends").json()["data"]
    assert _events("post.created") == [] and _events("post.tagged") == []
    client.post(reverse("posts:draft-publish", args=[data["id"]]))
    created = _events("post.created", data["id"])[0]
    handlers.on_post_created_tags(_envelope("post.created", created))
    tagged = _events("post.tagged")
    assert tagged == [{"post_id": data["id"], "author_id": author, "recipient": friend}]

    # A tag added by an edit notifies only the new person, and a blocked one never.
    post = client.patch(
        reverse("posts:post-detail", args=[data["id"]]),
        {"tagged_ids": [friend, outsider]},
        format="json",
    )
    assert post.status_code == 200, post.json()
    updated = _events("post.updated", data["id"])[-1]
    assert updated["new_tagged_ids"] == [outsider]
    BlockedPair.objects.create(blocker_id=outsider, blocked_id=author)
    handlers.on_post_updated_tags(_envelope("post.updated", updated))
    assert len(_events("post.tagged")) == 1


def test_a_tagged_person_who_cannot_see_the_post_is_not_notified(monkeypatch):
    author, friend = _acct(), _acct()
    monkeypatch.setattr("posts.services.get_relationship", _friends_with((author, friend)))
    post = services.create_post(author, body="me only", audience="only_me", tagged_ids=[friend])
    sent = composer.notify_tags(actor_id=author, post_id=str(post.id), account_ids=[friend])
    assert sent == 0


def test_tag_events_respect_the_flag(settings, monkeypatch):
    settings.POST_EMIT_TAG_EVENTS = False
    author, friend = _acct(), _acct()
    monkeypatch.setattr("posts.services.get_relationship", _friends_with((author, friend)))
    post = services.create_post(author, body="p", tagged_ids=[friend])
    assert composer.notify_tags(actor_id=author, post_id=str(post.id), account_ids=[friend]) == 0


def test_post_tagged_matches_its_json_schema(monkeypatch):
    if not os.path.isdir(SCHEMAS):
        pytest.skip("schemas are copied into the image at /opt/tara/libs")
    author, friend = _acct(), _acct()
    monkeypatch.setattr("posts.services.get_relationship", _friends_with((author, friend)))
    post = services.create_post(author, body="p", tagged_ids=[friend])
    composer.notify_tags(actor_id=author, post_id=str(post.id), account_ids=[friend])
    with open(f"{SCHEMAS}/post.tagged.v1.json", encoding="utf-8") as f:
        schema = json.load(f)
    (payload,) = _events("post.tagged")
    assert set(schema["required"]) <= set(payload) <= set(schema["properties"])


# ---- location and feeling ----------------------------------------------------------------


def test_location_is_cleaned_and_capped(client_for):
    client = client_for(_acct())
    spoof = "Cairo\u202e\u0007  Egypt"
    resp = _create(client, location=spoof)
    assert resp.json()["data"]["location"] == "Cairo Egypt"
    too_long = _create(client, location="x" * 121)
    assert too_long.status_code == 400
    assert too_long.json()["error"]["code"] == "location_too_long"


def test_feeling_comes_from_the_catalogue(client_for):
    client = client_for(_acct())
    resp = _create(client, body="", feeling="grateful")  # a feeling alone is a post
    assert resp.status_code == 201 and resp.json()["data"]["feeling"] == "grateful"
    assert _create(client, feeling="hungry-ish").status_code == 400


# ---- top comments -------------------------------------------------------------------------


def _comment(post, author, reactions=0, **extra):
    c = services.add_comment(author, str(post.id), f"from {author[:4]}")
    Comment.objects.filter(id=c.id).update(reaction_count=reactions, **extra)
    return c


def test_top_comments_respect_blocks_and_hidden_comments(client_for):
    viewer, author = _acct(), _acct()
    post = services.create_post(author, body="p")
    blocked, removed, deleted = _acct(), _acct(), _acct()
    best = _comment(post, _acct(), reactions=5)
    _comment(post, blocked, reactions=9)
    _comment(post, removed, reactions=8, moderation_status="removed")
    _comment(post, deleted, reactions=7, deleted_at=timezone.now())
    second = _comment(post, _acct(), reactions=1)
    _comment(post, _acct(), reactions=0)
    services.add_comment(_acct(), str(post.id), "a reply", str(best.id))  # never a reply
    BlockedPair.objects.create(blocker_id=viewer, blocked_id=blocked)

    data = client_for(viewer).get(reverse("posts:post-detail", args=[post.id])).json()["data"]
    assert [c["id"] for c in data["top_comments"]] == [str(best.id), str(second.id)]
    assert data["top_comments"][0]["parent_id"] is None


def test_top_comments_do_not_add_queries_per_post(client_for):
    viewer = _acct()
    client = client_for(viewer)

    def post_with_comments():
        post = services.create_post(_acct(), body="p")
        for n in range(3):
            _comment(post, _acct(), reactions=n)
        return post

    def batch(posts):
        with CaptureQueriesContext(connection) as ctx:
            resp = client.post(
                reverse("posts:post-batch"), {"ids": [str(p.id) for p in posts]}, format="json"
            )
        assert resp.status_code == 200
        assert all(len(p["top_comments"]) == 2 for p in resp.json()["data"])
        return len(ctx)

    posts = [post_with_comments()]
    few = batch(posts)
    posts += [post_with_comments() for _ in range(6)]
    assert batch(posts) == few
