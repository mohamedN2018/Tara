"""Shares, polls, mentions, hashtags."""

import uuid
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from posts import handlers, services
from posts.clients import Relationship
from posts.models import BlockedPair, OutboxEvent, Poll, PollVote, Post, Share
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _share(client, post_id, **data):
    return client.post(reverse("posts:post-share", args=[post_id]), data, format="json")


def _detail(client, post_id):
    return client.get(reverse("posts:post-detail", args=[post_id]))


# ---- shares ------------------------------------------------------------------


def test_share_creates_a_post_with_the_original_embedded(client_for):
    author, sharer = _acct(), _acct()
    original = services.create_post(author, body="original text", media_ids=[_acct()])
    resp = _share(client_for(sharer), original.id, body="look at this")
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["type"] == "share"
    assert data["author_id"] == sharer
    assert data["body"] == "look at this"
    assert data["shared_post_id"] == str(original.id)
    assert data["shared_post"]["body"] == "original text"
    assert len(data["shared_post"]["media_ids"]) == 1

    original.refresh_from_db()
    assert original.share_count == 1
    assert Share.objects.filter(post=original, account_id=sharer).exists()
    event = OutboxEvent.objects.get(event_type="post.shared")
    assert event.payload["payload"]["author_id"] == author
    assert OutboxEvent.objects.filter(event_type="post.created").count() == 2


def test_share_of_a_share_points_at_the_first_post(client_for):
    original = services.create_post(_acct(), body="root")
    first = _share(client_for(_acct()), original.id).json()["data"]
    second = _share(client_for(_acct()), first["id"]).json()["data"]
    assert second["shared_post_id"] == str(original.id)


def test_share_cannot_reach_further_than_the_original(client_for, monkeypatch):
    monkeypatch.setattr(
        "posts.services.get_relationship", lambda a, b: Relationship(are_friends=True)
    )
    author, friend = _acct(), _acct()
    original = services.create_post(author, body="friends only", audience="friends")
    client = client_for(friend)
    assert _share(client, original.id, audience="public").status_code == 400
    resp = _share(client, original.id)
    assert resp.status_code == 201
    assert resp.json()["data"]["audience"] == "friends"


def test_cannot_share_what_you_cannot_see(client_for, monkeypatch):
    monkeypatch.setattr("posts.services.get_relationship", lambda a, b: Relationship())
    original = services.create_post(_acct(), body="friends only", audience="friends")
    assert _share(client_for(_acct()), original.id).status_code == 404


def test_reader_outside_the_original_audience_sees_no_content(client_for, monkeypatch):
    author, friend, stranger = _acct(), _acct(), _acct()
    monkeypatch.setattr(
        "posts.services.get_relationship",
        lambda a, b: Relationship(are_friends={a, b} == {author, friend} or friend in (a, b)),
    )
    original = services.create_post(author, body="secret", audience="friends")
    share_id = _share(client_for(friend), original.id).json()["data"]["id"]

    # The stranger is the sharer's friend but not the author's.
    data = _detail(client_for(stranger), share_id).json()["data"]
    assert data["shared_post_id"] == str(original.id)
    assert data["shared_post"] is None
    assert "secret" not in str(data)


def test_share_event_excerpt_never_carries_the_original(client_for):
    original = services.create_post(_acct(), body="private words")
    _share(client_for(_acct()), original.id, body="mine")
    created = OutboxEvent.objects.filter(event_type="post.created").order_by("-created_at")[0]
    assert created.payload["payload"]["excerpt"] == "mine"


def test_deleted_original_leaves_an_unavailable_card(client_for):
    author = _acct()
    original = services.create_post(author, body="gone soon")
    sharer = _acct()
    share_id = _share(client_for(sharer), original.id).json()["data"]["id"]
    services.delete_post(author, str(original.id))
    assert _detail(client_for(sharer), share_id).json()["data"]["shared_post"] is None


def test_deleting_a_share_lowers_the_count(client_for):
    original = services.create_post(_acct(), body="x")
    sharer = _acct()
    share_id = _share(client_for(sharer), original.id).json()["data"]["id"]
    services.delete_post(sharer, share_id)
    original.refresh_from_db()
    assert original.share_count == 0


def test_client_cannot_supply_share_or_link_preview_fields(client_for):
    me = _acct()
    original = services.create_post(_acct(), body="x", audience="only_me")
    resp = client_for(me).post(
        reverse("posts:post-create"),
        {
            "body": "hello",
            "shared_post_id": str(original.id),
            "link_preview": {"url": "http://evil", "title": "fake"},
        },
        format="json",
    )
    assert resp.status_code == 201
    post = Post.objects.get(id=resp.json()["data"]["id"])
    assert post.shared_post_id is None
    assert post.link_preview is None


def test_client_cannot_pick_the_poll_or_share_type_directly(client_for):
    for kind in ("poll", "share", "link"):
        resp = client_for(_acct()).post(
            reverse("posts:post-create"), {"body": "x", "type": kind}, format="json"
        )
        assert resp.status_code == 400


# ---- polls -------------------------------------------------------------------


def _poll(client, **extra):
    return client.post(
        reverse("posts:post-create"),
        {"body": "tea or coffee?", "poll": {"options": ["Tea", "Coffee"], **extra}},
        format="json",
    )


def test_poll_is_created_and_shows_viewer_state(client_for):
    author, voter = _acct(), _acct()
    resp = _poll(client_for(author))
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["type"] == "poll"
    assert [o["text"] for o in data["poll"]["options"]] == ["Tea", "Coffee"]
    option = data["poll"]["options"][1]["id"]

    voted = client_for(voter).post(
        reverse("posts:post-vote", args=[data["id"]]), {"option_id": option}, format="json"
    )
    assert voted.status_code == 200
    poll = voted.json()["data"]["poll"]
    assert poll["my_option_id"] == option
    assert poll["total_votes"] == 1

    assert _detail(client_for(author), data["id"]).json()["data"]["poll"]["my_option_id"] is None


def test_one_vote_per_account(client_for):
    data = _poll(client_for(_acct())).json()["data"]
    client = client_for(_acct())
    url = reverse("posts:post-vote", args=[data["id"]])
    first, second = data["poll"]["options"]
    assert client.post(url, {"option_id": first["id"]}, format="json").status_code == 200
    assert client.post(url, {"option_id": second["id"]}, format="json").status_code == 409
    assert PollVote.objects.count() == 1
    poll = Poll.objects.get(post_id=data["id"])
    assert sum(o.vote_count for o in poll.options.all()) == 1


def test_vote_is_refused_for_foreign_option_closed_poll_and_hidden_post(client_for, monkeypatch):
    monkeypatch.setattr("posts.services.get_relationship", lambda a, b: Relationship())
    data = _poll(client_for(_acct())).json()["data"]
    other = _poll(client_for(_acct())).json()["data"]
    client = client_for(_acct())
    url = reverse("posts:post-vote", args=[data["id"]])

    foreign = other["poll"]["options"][0]["id"]
    assert client.post(url, {"option_id": foreign}, format="json").status_code == 404

    Poll.objects.filter(post_id=data["id"]).update(closes_at=timezone.now() - timedelta(hours=1))
    option = data["poll"]["options"][0]["id"]
    assert client.post(url, {"option_id": option}, format="json").status_code == 409

    hidden = client_for(_acct()).post(
        reverse("posts:post-create"),
        {"body": "q", "audience": "friends", "poll": {"options": ["a", "b"]}},
        format="json",
    )
    hidden_data = hidden.json()["data"]
    resp = client.post(
        reverse("posts:post-vote", args=[hidden_data["id"]]),
        {"option_id": hidden_data["poll"]["options"][0]["id"]},
        format="json",
    )
    assert resp.status_code == 404


@pytest.mark.parametrize(
    "poll",
    [
        {"options": ["only one"]},
        {"options": ["same", "SAME"]},
        {"options": [str(i) for i in range(7)]},
        {"options": ["a", "b"], "duration_hours": 0},
    ],
)
def test_bad_polls_are_rejected(client_for, poll):
    resp = client_for(_acct()).post(
        reverse("posts:post-create"), {"body": "q", "poll": poll}, format="json"
    )
    assert resp.status_code == 400


def test_poll_needs_a_question(client_for):
    resp = client_for(_acct()).post(
        reverse("posts:post-create"), {"body": "", "poll": {"options": ["a", "b"]}}, format="json"
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["details"][0]["field"] == "body"


# ---- hashtags and mentions ---------------------------------------------------


def test_tag_and_mention_parsing_skips_urls_and_emails():
    body = "#مرحبا x#no https://a.b/#frag me@host.com @nadia_1"
    assert services.extract_hashtags(body) == ["مرحبا"]
    assert services.extract_mentions(body) == ["nadia_1"]


def test_hashtag_listing_applies_audience(client_for, monkeypatch):
    monkeypatch.setattr("posts.services.get_relationship", lambda a, b: Relationship())
    public = services.create_post(_acct(), body="hello #Tara")
    services.create_post(_acct(), body="secret #tara", audience="friends")
    services.create_post(_acct(), body="other #nope")
    resp = client_for(_acct()).get(reverse("posts:post-create"), {"hashtag": "tara"})
    assert [p["id"] for p in resp.json()["data"]] == [str(public.id)]


def _envelope(event_type, payload):
    return EventEnvelope(
        event_type=event_type, subject_id=str(uuid.uuid4()), producer="post", payload=payload
    )


def test_mentions_notify_only_people_who_can_see_the_post(monkeypatch):
    author, friend, stranger, blocked = _acct(), _acct(), _acct(), _acct()
    monkeypatch.setattr(
        "posts.services.get_relationship",
        lambda a, b: Relationship(are_friends=friend in (a, b)),
    )
    monkeypatch.setattr(
        "posts.services.resolve_handles",
        lambda handles: {"fr": friend, "st": stranger, "me": author, "bl": blocked},
    )
    BlockedPair.objects.create(blocker_id=blocked, blocked_id=author)
    post = services.create_post(author, body="hi @fri @str @bloc", audience="friends")
    handlers.on_post_created_mentions(
        _envelope(
            "post.created",
            {"author_id": author, "post_id": str(post.id), "mentions": ["fr", "st", "me", "bl"]},
        )
    )
    events = OutboxEvent.objects.filter(event_type="user.mentioned")
    assert [e.payload["payload"]["recipient"] for e in events] == [friend]


def test_editing_a_post_only_reports_new_mentions(client_for):
    author = _acct()
    post = services.create_post(author, body="hi @oldone")
    services.edit_post(author, str(post.id), "hi @oldone and @newone")
    event = OutboxEvent.objects.get(event_type="post.updated")
    assert event.payload["payload"]["new_mentions"] == ["newone"]


def test_comment_mentions_are_resolved(monkeypatch):
    author, commenter, target = _acct(), _acct(), _acct()
    monkeypatch.setattr("posts.services.resolve_handles", lambda handles: {"target": target})
    post = services.create_post(author, body="p")
    comment = services.add_comment(commenter, str(post.id), "hey @target")
    created = OutboxEvent.objects.get(event_type="post.commented").payload["payload"]
    assert created["mentions"] == ["target"]
    handlers.on_comment_mentions(_envelope("post.commented", created))
    event = OutboxEvent.objects.get(event_type="user.mentioned").payload["payload"]
    assert event["recipient"] == target
    assert event["comment_id"] == str(comment.id)
