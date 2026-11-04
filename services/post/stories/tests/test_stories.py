"""Milestone 1.9: stories with 24-hour expiry, audiences, close friends, views,
reactions, reports, moderation, blocks and private photos."""

import json
import os
from datetime import timedelta

import jwt
import pytest
from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from posts.handlers import on_moderation_actioned
from posts.models import BlockedPair, OutboxEvent
from rest_framework.test import APIClient

from stories import services
from stories.handlers import (
    on_friendship_removed_drop_close_friends,
    on_user_blocked_drop_close_friends,
)
from stories.models import CloseFriend, Story, StoryReaction, StoryReport, StoryView
from stories.tests.conftest import acct, make_story
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db

SCHEMAS = "/opt/tara/libs/tara_events/tara_events/schemas"


def _outbox(event_type: str):
    return [e.payload["payload"] for e in OutboxEvent.objects.filter(event_type=event_type)]


def _code(resp) -> str:
    return resp.json()["error"]["code"]


def _detail(client, story_id):
    return client.get(reverse("stories:story-detail", args=[story_id]))


def _tray(client):
    resp = client.get(reverse("stories:story-tray"))
    assert resp.status_code == 200, resp.content
    return resp.json()["data"]


def _tray_ids(client) -> list[str]:
    return [s["id"] for g in _tray(client) for s in g["stories"]]


def _expire(story: Story) -> None:
    Story.objects.filter(id=story.id).update(
        created_at=timezone.now() - timedelta(hours=25),
        expires_at=timezone.now() - timedelta(hours=1),
    )


def _envelope(event_type, payload, actor=None):
    return EventEnvelope(
        event_type=event_type,
        subject_id=acct(),
        producer="test",
        payload=payload,
        actor_id=actor,
    )


def _internal_client():
    now = int(timezone.now().timestamp())
    token = jwt.encode(
        {"iss": "media", "aud": "post-internal", "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def _media_visible(story_id, viewer) -> bool:
    resp = _internal_client().get(
        reverse("internal-post-visibility", args=[story_id]), {"viewer_id": viewer}
    )
    assert resp.status_code == 200
    return resp.json()["data"]["visible"]


# ---- create -----------------------------------------------------------------------


def test_create_text_story_lasts_a_day(client_for):
    me = acct()
    resp = client_for(me).post(
        reverse("stories:story-list"),
        {"kind": "text", "text": "  Good morning  ", "audience": "friends", "background": "dusk"},
        format="json",
    )
    assert resp.status_code == 201, resp.content
    data = resp.json()["data"]
    assert data["text"] == "Good morning"
    assert data["is_mine"] and data["is_active"] and data["view_count"] == 0
    story = Story.objects.get(id=data["id"])
    assert (
        timedelta(hours=23, minutes=59)
        < story.expires_at - story.created_at
        <= timedelta(hours=24, seconds=1)
    )


@pytest.mark.parametrize(
    "body,code",
    [
        ({"kind": "text", "text": "  "}, "text_required"),
        ({"kind": "photo"}, "media_required"),
        ({"kind": "text", "text": "x", "background": "neon"}, "validation_error"),
        ({"kind": "video", "media_id": None}, "validation_error"),
    ],
)
def test_create_rejects_bad_input(client_for, body, code):
    resp = client_for(acct()).post(reverse("stories:story-list"), body, format="json")
    assert resp.status_code == 400
    assert _code(resp) == code


def test_photo_story_binds_its_media_privately(client_for, media_stub):
    me = acct()
    media_id = media_stub.add(me)
    resp = client_for(me).post(
        reverse("stories:story-list"),
        {"kind": "photo", "media_id": media_id, "audience": "public"},
        format="json",
    )
    assert resp.status_code == 201, resp.content
    story_id = resp.json()["data"]["id"]
    assert media_stub.binds == [
        {"owner_id": me, "post_id": story_id, "ids": [media_id], "restricted": True}
    ]


def test_photo_story_rules(client_for, media_stub):
    me, other = acct(), acct()
    client = client_for(me)

    def create(media_id):
        return client.post(
            reverse("stories:story-list"), {"kind": "photo", "media_id": media_id}, format="json"
        )

    assert _code(create(media_stub.add(other))) == "media_not_owned"
    assert _code(create(media_stub.add(me, kind="video"))) == "media_kind_not_allowed"
    assert _code(create(media_stub.add(me, status="uploading"))) == "media_not_ready"
    used = media_stub.add(me)
    assert create(used).status_code == 201
    assert _code(create(used)) == "media_already_attached"
    media_stub.down = True
    resp = create(media_stub.add(me))
    assert resp.status_code == 503
    assert Story.objects.count() == 1


def test_daily_limit(client_for, monkeypatch):
    monkeypatch.setattr(services, "MAX_STORIES_PER_DAY", 2)
    me = acct()
    make_story(me)
    make_story(me)
    resp = client_for(me).post(
        reverse("stories:story-list"), {"kind": "text", "text": "third"}, format="json"
    )
    assert resp.status_code == 400 and _code(resp) == "story_limit"


# ---- visibility -------------------------------------------------------------------

VIEWERS = ("author", "close", "friend", "stranger")
EXPECTED = {
    "public": {"author", "close", "friend", "stranger"},
    "friends": {"author", "close", "friend"},
    "close_friends": {"author", "close"},
}


@pytest.fixture
def people(graph):
    p = {v: acct() for v in VIEWERS}
    graph.befriend(p["author"], p["close"])
    graph.befriend(p["author"], p["friend"])
    CloseFriend.objects.create(owner_id=p["author"], friend_id=p["close"])
    return p


@pytest.mark.parametrize("audience", list(EXPECTED))
def test_visibility_matrix(client_for, people, audience):
    story = make_story(people["author"], audience=audience)
    for viewer in VIEWERS:
        client = client_for(people[viewer])
        visible = viewer in EXPECTED[audience]
        assert _detail(client, story.id).status_code == (200 if visible else 404), viewer
        assert _media_visible(story.id, people[viewer]) is visible, viewer
        # The tray holds the viewer and their friends; the stranger reaches a
        # public story by its link or the author's ring.
        in_tray = visible and viewer != "stranger"
        assert (str(story.id) in _tray_ids(client)) is in_tray, viewer
        ring = client.get(reverse("stories:story-list"), {"author_id": people["author"]})
        assert (str(story.id) in [s["id"] for s in ring.json()["data"]]) is visible, viewer


@pytest.mark.parametrize("audience", list(EXPECTED))
def test_expired_story_is_the_authors_alone(client_for, people, audience):
    story = make_story(people["author"], audience=audience)
    _expire(story)
    for viewer in VIEWERS:
        client = client_for(people[viewer])
        mine = viewer == "author"
        assert _detail(client, story.id).status_code == (200 if mine else 404), viewer
        assert _media_visible(story.id, people[viewer]) is mine, viewer
        assert str(story.id) not in _tray_ids(client)
        if not mine:
            assert client.post(reverse("stories:story-seen", args=[story.id])).status_code == 404
    archive = client_for(people["author"]).get(reverse("stories:story-archive"))
    item = archive.json()["data"][0]
    assert item["id"] == str(story.id) and item["is_active"] is False


def test_close_friends_story_hidden_after_unfriend_even_on_the_list(client_for, people, graph):
    story = make_story(people["author"], audience="close_friends")
    graph.unfriend(people["author"], people["close"])
    assert _detail(client_for(people["close"]), story.id).status_code == 404
    assert _media_visible(story.id, people["close"]) is False


def test_graph_down_fails_closed(client_for, people, graph):
    story = make_story(people["author"], audience="friends")
    graph.down = True
    client = client_for(people["friend"])
    assert _detail(client, story.id).status_code == 404
    assert _tray_ids(client) == []
    # The author still sees their own.
    assert str(story.id) in _tray_ids(client_for(people["author"]))


@pytest.mark.parametrize("direction", ["author_blocks", "viewer_blocks"])
def test_blocks_hide_stories_both_ways(client_for, people, direction):
    story = make_story(people["author"], audience="public")
    a, b = people["author"], people["friend"]
    blocker, blocked = (a, b) if direction == "author_blocks" else (b, a)
    BlockedPair.objects.create(blocker_id=blocker, blocked_id=blocked)
    client = client_for(people["friend"])
    assert _detail(client, story.id).status_code == 404
    assert str(story.id) not in _tray_ids(client)
    assert client.get(reverse("stories:story-list"), {"author_id": a}).json()["data"] == []
    assert _media_visible(story.id, b) is False


def test_deleted_and_removed_are_hidden_from_everyone(client_for, people):
    deleted = make_story(people["author"])
    removed = make_story(people["author"])
    author = client_for(people["author"])
    assert (
        client_for(people["friend"])
        .delete(reverse("stories:story-detail", args=[deleted.id]))
        .status_code
        == 404
    )  # not the author
    assert author.delete(reverse("stories:story-detail", args=[deleted.id])).status_code == 204
    assert _outbox("story.deleted") == [
        {"story_id": str(deleted.id), "author_id": people["author"]}
    ]
    services.apply_moderation(str(removed.id), "remove")
    services.apply_moderation(str(removed.id), "remove")  # idempotent
    for story in (deleted, removed):
        for viewer in VIEWERS:
            assert _detail(client_for(people[viewer]), story.id).status_code == 404
            assert _media_visible(story.id, people[viewer]) is False
    assert len(_outbox("story.deleted")) == 2
    assert _outbox("story.deleted")[1]["by"] == "moderation"


def test_moderation_event_routes_to_stories(client_for, people):
    story = make_story(people["author"])
    for action in ("remove", "approve"):
        on_moderation_actioned(
            _envelope(
                "moderation.actioned",
                {
                    "case_id": acct(),
                    "target_type": "story",
                    "target_id": str(story.id),
                    "action": action,
                },
            )
        )
        story.refresh_from_db()
        expected = "removed" if action == "remove" else "ok"
        assert story.moderation_status == expected
    assert _detail(client_for(people["friend"]), story.id).status_code == 200


# ---- tray -------------------------------------------------------------------------


def test_tray_groups_by_author_mine_first_then_unseen(client_for, graph):
    me, seen_friend, fresh_friend = acct(), acct(), acct()
    graph.befriend(me, seen_friend)
    graph.befriend(me, fresh_friend)
    s1 = make_story(seen_friend, audience="friends")
    f1 = make_story(fresh_friend, audience="friends")
    f2 = make_story(fresh_friend, audience="public")
    mine = make_story(me, audience="friends")
    client = client_for(me)
    assert client.post(reverse("stories:story-seen", args=[s1.id])).status_code == 200
    tray = _tray(client)
    assert [g["author_id"] for g in tray] == [me, fresh_friend, seen_friend]
    assert [s["id"] for s in tray[1]["stories"]] == [str(f1.id), str(f2.id)]  # oldest first
    assert [g["has_unseen"] for g in tray] == [False, True, False]
    assert tray[0]["stories"][0]["id"] == str(mine.id)
    assert tray[0]["stories"][0]["view_count"] == 0
    assert tray[1]["stories"][0]["view_count"] is None  # counts are the author's


def test_tray_includes_public_stories_of_accounts_i_follow_only(client_for, graph):
    me, followed, stranger, blocked = acct(), acct(), acct(), acct()
    graph.follow(me, followed)
    graph.follow(me, blocked)
    public = make_story(followed, audience="public")
    make_story(followed, audience="friends")  # friends-only: not for a follower
    make_story(stranger, audience="public")  # public, but I don't follow them
    make_story(blocked, audience="public")
    BlockedPair.objects.create(blocker_id=blocked, blocked_id=me)
    tray = _tray(client_for(me))
    assert [g["author_id"] for g in tray] == [followed]
    assert [s["id"] for s in tray[0]["stories"]] == [str(public.id)]
    assert tray[0]["has_unseen"] is True


def test_tray_without_graph_shows_no_followed_stories(client_for, graph):
    me, followed = acct(), acct()
    graph.follow(me, followed)
    make_story(followed, audience="public")
    graph.down = True
    assert _tray(client_for(me)) == []


def test_tray_follow_lookup_down_keeps_own_and_friends(client_for, graph, monkeypatch):
    # Matches the tray() docstring: only the follow lookup failing drops the
    # followed accounts, not the viewer's own or their friends' stories.
    me, friend, followed = acct(), acct(), acct()
    graph.befriend(me, friend)
    graph.follow(me, followed)
    mine = make_story(me, audience="friends")
    theirs = make_story(friend, audience="friends")
    make_story(followed, audience="public")
    monkeypatch.setattr("stories.services.followed_ids", lambda viewer, candidates: set())
    tray = _tray(client_for(me))
    assert [g["author_id"] for g in tray] == [me, friend]
    assert [g["stories"][0]["id"] for g in tray] == [str(mine.id), str(theirs.id)]


def test_followed_ids_asks_graph_batch_and_fails_closed(monkeypatch, graph):
    # The real helper: drop the fake graph the autouse fixture installed.
    monkeypatch.undo()
    real = services.followed_ids
    calls = {}

    class Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": {"results": {"a": {"following": True}, "b": {"following": False}}}}

    def fake_post(url, json, headers, timeout):
        calls["url"], calls["json"] = url, json
        return Resp()

    monkeypatch.setattr("stories.services.requests.post", fake_post)
    assert real("v", ["a", "b"]) == {"a"}
    assert calls["url"].endswith("/internal/v1/relationships/batch/")
    assert calls["json"] == {"viewer_id": "v", "users": ["a", "b"], "pages": []}
    assert real("v", []) == set()

    def broken(*args, **kwargs):
        raise OSError("down")

    monkeypatch.setattr("stories.services.requests.post", broken)
    assert real("v", ["a"]) == set()


# ---- views, viewers and reactions -------------------------------------------------


def test_views_count_once_and_not_the_author(client_for, people):
    story = make_story(people["author"], audience="friends")
    friend = client_for(people["friend"])
    for _ in range(3):
        assert friend.post(reverse("stories:story-seen", args=[story.id])).status_code == 200
    client_for(people["author"]).post(reverse("stories:story-seen", args=[story.id]))
    story.refresh_from_db()
    assert story.view_count == 1
    assert StoryView.objects.filter(story=story).count() == 1
    assert _detail(friend, story.id).json()["data"]["seen"] is True


def test_viewers_list_is_the_authors_only(client_for, people):
    story = make_story(people["author"], audience="public")
    for viewer in ("friend", "close", "stranger"):
        client_for(people[viewer]).post(reverse("stories:story-seen", args=[story.id]))
    client_for(people["friend"]).post(
        reverse("stories:story-react", args=[story.id]), {"reaction": "love"}, format="json"
    )
    BlockedPair.objects.create(blocker_id=people["stranger"], blocked_id=people["author"])
    url = reverse("stories:story-viewers", args=[story.id])
    for viewer in ("friend", "stranger"):
        assert client_for(people[viewer]).get(url).status_code == 404
    rows = client_for(people["author"]).get(url).json()["data"]
    assert {r["account_id"] for r in rows} == {people["friend"], people["close"]}
    assert {r["account_id"]: r["reaction"] for r in rows}[people["friend"]] == "love"
    # Still the author's after it expires (the archive shows who saw it).
    _expire(story)
    assert client_for(people["author"]).get(url).status_code == 200


def test_react_notifies_the_author_once(client_for, people):
    story = make_story(people["author"], audience="friends")
    friend = client_for(people["friend"])
    url = reverse("stories:story-react", args=[story.id])
    assert friend.post(url, {"reaction": "like"}, format="json").status_code == 200
    resp = friend.post(url, {"reaction": "haha"}, format="json")
    assert resp.json()["data"]["my_reaction"] == "haha"
    assert StoryReaction.objects.get(story=story).reaction == "haha"
    assert _outbox("story.reacted") == [
        {
            "story_id": str(story.id),
            "author_id": people["author"],
            "reactor": people["friend"],
            "reaction_type": "like",
        }
    ]
    story.refresh_from_db()
    assert (story.reaction_count, story.view_count) == (1, 1)
    assert friend.delete(url).json()["data"]["my_reaction"] is None
    story.refresh_from_db()
    assert story.reaction_count == 0


def test_react_rules(client_for, people):
    story = make_story(people["author"], audience="friends")
    url = reverse("stories:story-react", args=[story.id])
    own = client_for(people["author"]).post(url, {"reaction": "like"}, format="json")
    assert own.status_code == 400 and _code(own) == "cannot_react_own"
    stranger = client_for(people["stranger"]).post(url, {"reaction": "like"}, format="json")
    assert stranger.status_code == 404
    assert not OutboxEvent.objects.filter(event_type="story.reacted").exists()
    # Last: a serializer error marks the test transaction for rollback.
    bad = client_for(people["friend"]).post(url, {"reaction": "meh"}, format="json")
    assert bad.status_code == 400


def test_emission_flag_off_writes_no_events(client_for, people, settings):
    settings.POST_EMIT_STORY_EVENTS = False
    story = make_story(people["author"], audience="friends")
    client_for(people["friend"]).post(
        reverse("stories:story-react", args=[story.id]), {"reaction": "like"}, format="json"
    )
    client_for(people["friend"]).post(
        reverse("stories:story-report", args=[story.id]), {"reason": "spam"}, format="json"
    )
    assert not OutboxEvent.objects.filter(event_type__startswith="story.").exists()
    assert StoryReport.objects.count() == 1


# ---- reports ----------------------------------------------------------------------


def test_report_once_and_only_when_visible(client_for, people):
    story = make_story(people["author"], audience="close_friends")
    url = reverse("stories:story-report", args=[story.id])
    hidden = client_for(people["friend"]).post(url, {"reason": "spam"}, format="json")
    assert hidden.status_code == 404
    assert not OutboxEvent.objects.filter(event_type="story.reported").exists()
    close = client_for(people["close"])
    assert close.post(url, {"reason": "harassment"}, format="json").status_code == 202
    assert close.post(url, {"reason": "spam"}, format="json").status_code == 202
    assert _outbox("story.reported") == [
        {
            "story_id": str(story.id),
            "reporter": people["close"],
            "reason": "harassment",
            "owner_id": people["author"],
        }
    ]
    own = client_for(people["author"]).post(url, {"reason": "spam"}, format="json")
    assert own.status_code == 400 and _code(own) == "cannot_report_own"


# ---- close friends ----------------------------------------------------------------


def test_close_friends_list(client_for, graph):
    me, friend, other_friend, stranger = acct(), acct(), acct(), acct()
    graph.befriend(me, friend)
    graph.befriend(me, other_friend)
    client = client_for(me)
    url = reverse("stories:close-friends")
    bad = client.post(url, {"account_ids": [stranger]}, format="json")
    assert bad.status_code == 400 and _code(bad) == "not_friend"
    resp = client.post(url, {"account_ids": [friend, other_friend]}, format="json")
    assert resp.json()["data"]["added"] == [friend, other_friend]
    again = client.post(url, {"account_ids": [friend]}, format="json")
    assert again.json()["data"]["added"] == []
    assert {r["account_id"] for r in client.get(url).json()["data"]} == {friend, other_friend}
    # Nobody else reads my list.
    assert client_for(friend).get(url).json()["data"] == []
    detail = reverse("stories:close-friend-detail", args=[other_friend])
    assert client.delete(detail).status_code == 204
    assert client.delete(detail).status_code == 204
    assert [r["account_id"] for r in client.get(url).json()["data"]] == [friend]
    graph.down = True
    down = client.post(url, {"account_ids": [other_friend]}, format="json")
    assert down.status_code == 503
    assert CloseFriend.objects.filter(owner_id=me).count() == 1


def test_block_and_unfriend_clean_the_lists(graph):
    a, b, c = acct(), acct(), acct()
    graph.befriend(a, b)
    graph.befriend(a, c)
    CloseFriend.objects.create(owner_id=a, friend_id=b)
    CloseFriend.objects.create(owner_id=b, friend_id=a)
    CloseFriend.objects.create(owner_id=a, friend_id=c)
    on_user_blocked_drop_close_friends(
        _envelope("user.blocked", {"blocker_id": b, "blocked_id": a})
    )
    assert not CloseFriend.objects.filter(owner_id__in=[a, b], friend_id__in=[a, b]).exists()
    # A stale unfriend after a re-friend drops nothing; graph down retries.
    on_friendship_removed_drop_close_friends(_envelope("friendship.removed", {"a": a, "b": c}))
    assert CloseFriend.objects.filter(owner_id=a, friend_id=c).exists()
    graph.down = True
    with pytest.raises(Exception):  # noqa: B017 - the consumer retries
        on_friendship_removed_drop_close_friends(_envelope("friendship.removed", {"a": a, "b": c}))
    graph.down = False
    graph.unfriend(a, c)
    on_friendship_removed_drop_close_friends(_envelope("friendship.removed", {"a": a, "b": c}))
    assert not CloseFriend.objects.filter(owner_id=a, friend_id=c).exists()


# ---- event contracts --------------------------------------------------------------


def test_emitted_payloads_match_their_json_schemas(client_for, people):
    if not os.path.isdir(SCHEMAS):
        pytest.skip("schemas are copied into the image at /opt/tara/libs")
    story = make_story(people["author"], audience="public")
    friend = client_for(people["friend"])
    friend.post(reverse("stories:story-react", args=[story.id]), {"reaction": "wow"}, format="json")
    friend.post(reverse("stories:story-report", args=[story.id]), {"reason": "spam"}, format="json")
    services.apply_moderation(str(story.id), "remove")
    other = make_story(people["author"])
    services.delete_story(people["author"], other.id)
    seen = set()
    for row in OutboxEvent.objects.filter(event_type__startswith="story."):
        with open(f"{SCHEMAS}/{row.event_type}.v1.json", encoding="utf-8") as f:
            schema = json.load(f)
        payload = row.payload["payload"]
        assert set(schema["required"]) <= set(payload) <= set(schema["properties"])
        for key, rule in schema["properties"].items():
            if "enum" in rule and key in payload:
                assert payload[key] in rule["enum"], (row.event_type, key)
        assert row.payload["partition_key"] == f"story:{payload['story_id']}"
        seen.add(row.event_type)
    assert seen == {"story.reacted", "story.reported", "story.deleted"}
