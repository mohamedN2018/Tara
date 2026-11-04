"""Wave 2 review fixes in the composer: removing your own tag always, tags on a
block, tag notifications on a group approval, media's view of a draft, and the
joiners a location keeps."""

import json
import os
import uuid

import pytest
from django.urls import reverse

from posts import composer, handlers, services
from posts.clients import Relationship
from posts.models import BlockedPair, OutboxEvent, Post, PostTag
from posts.tests.test_groups import Group, _post, api_client_internal, profile  # noqa: F401
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db

SCHEMAS = "/opt/tara/libs/tara_events/tara_events/schemas"


def _acct() -> str:
    return str(uuid.uuid4())


def _events(event_type: str) -> list[dict]:
    rows = OutboxEvent.objects.filter(event_type=event_type).order_by("created_at", "id")
    return [r.payload["payload"] for r in rows]


def _friends_with(*pairs):
    friends = {frozenset(p) for p in pairs}
    return lambda a, b: Relationship(are_friends=frozenset((str(a), str(b))) in friends)


def _envelope(event_type: str, payload: dict) -> EventEnvelope:
    return EventEnvelope(
        event_type=event_type, subject_id=payload["post_id"], producer="post", payload=payload
    )


def _create(client, **data):
    return client.post(reverse("posts:post-create"), {"body": "hi", **data}, format="json")


def _untag(client, post_id):
    return client.delete(reverse("posts:post-my-tag", args=[post_id]))


# ---- #3: the tagged person always removes their tag; a block drops tags --------------


def test_a_tagged_person_removes_their_tag_after_blocking_the_author(client_for, monkeypatch):
    author, friend = _acct(), _acct()
    monkeypatch.setattr("posts.services.get_relationship", _friends_with((author, friend)))
    post_id = _create(client_for(author), tagged_ids=[friend]).json()["data"]["id"]
    BlockedPair.objects.create(blocker_id=friend, blocked_id=author)  # no tag cleanup
    assert not services.visible_to_viewer(friend, Post.objects.get(id=post_id))
    assert _untag(client_for(friend), post_id).status_code == 204
    assert not PostTag.objects.filter(post_id=post_id).exists()


def test_a_tag_is_removed_after_an_unfriend_and_on_a_draft(client_for, monkeypatch):
    author, friend = _acct(), _acct()
    monkeypatch.setattr("posts.services.get_relationship", _friends_with((author, friend)))
    client = client_for(author)
    narrow = _create(client, tagged_ids=[friend], audience="friends").json()["data"]["id"]
    draft = _create(client, tagged_ids=[friend], draft=True).json()["data"]["id"]
    monkeypatch.setattr("posts.services.get_relationship", lambda a, b: Relationship())
    assert _untag(client_for(friend), narrow).status_code == 204
    assert _untag(client_for(friend), draft).status_code == 204
    assert not PostTag.objects.filter(account_id=friend).exists()


def test_removing_a_tag_you_do_not_have_keeps_its_old_answers(client_for, monkeypatch):
    author, friend, stranger = _acct(), _acct(), _acct()
    monkeypatch.setattr("posts.services.get_relationship", _friends_with((author, friend)))
    client = client_for(author)
    public = _create(client, tagged_ids=[friend]).json()["data"]["id"]
    hidden = _create(client, tagged_ids=[friend], audience="only_me").json()["data"]["id"]
    assert _untag(client_for(stranger), public).status_code == 204  # visible: a no-op
    assert _untag(client_for(stranger), hidden).status_code == 404  # never revealed
    assert _untag(client_for(stranger), _acct()).status_code == 404
    assert PostTag.objects.filter(account_id=friend).count() == 2


def test_a_block_drops_the_tags_between_the_two_both_ways(client_for, monkeypatch):
    a, b, c = _acct(), _acct(), _acct()
    monkeypatch.setattr("posts.services.get_relationship", lambda x, y: Relationship(True))
    a_tags_b = _create(client_for(a), tagged_ids=[b, c]).json()["data"]["id"]
    _create(client_for(b), tagged_ids=[a])
    c_tags_b = _create(client_for(c), tagged_ids=[b]).json()["data"]["id"]
    event = EventEnvelope(
        event_type="user.blocked",
        subject_id=a,
        producer="graph",
        payload={"blocker_id": a, "blocked_id": b},
    )
    handlers.on_user_blocked(event)
    handlers.on_user_blocked(event)  # redelivered: idempotent
    assert BlockedPair.objects.filter(blocker_id=a, blocked_id=b).count() == 1
    remaining = set(PostTag.objects.values_list("post_id", "account_id"))  # b's tag of a went
    assert remaining == {(uuid.UUID(a_tags_b), uuid.UUID(c)), (uuid.UUID(c_tags_b), uuid.UUID(b))}


def test_an_edit_drops_a_kept_tag_once_either_side_blocked(client_for, monkeypatch):
    author, friend, other = _acct(), _acct(), _acct()
    monkeypatch.setattr(
        "posts.services.get_relationship", _friends_with((author, friend), (author, other))
    )
    client = client_for(author)
    post_id = _create(client, tagged_ids=[friend]).json()["data"]["id"]
    BlockedPair.objects.create(blocker_id=friend, blocked_id=author)  # event not yet applied
    resp = client.patch(
        reverse("posts:post-detail", args=[post_id]),
        {"tagged_ids": [friend, other]},
        format="json",
    )
    assert resp.status_code == 200, resp.json()
    assert resp.json()["data"]["tagged_ids"] == [other]


# ---- #5: a group post held for approval tells its tagged people when approved --------


def test_tagged_members_hear_of_a_group_post_when_it_is_approved(
    client_for,
    profile,  # noqa: F811
    monkeypatch,
):
    monkeypatch.setattr("posts.services.get_relationship", lambda a, b: Relationship())
    group = Group(profile, "private", post_approval=True)
    author, tagged, moderator = group.member(), group.member(), group.member("moderator")
    group.member(notify=True)
    for account in (tagged, moderator):  # not the author's friends
        client_for(account).patch(
            reverse("posts:post-settings"), {"who_can_tag": "everyone"}, format="json"
        )
    resp = _post(client_for(author), group, tagged_ids=[tagged, moderator])
    assert resp.status_code == 201, resp.json()
    pending = resp.json()["data"]
    assert pending["approval_state"] == "pending"
    created = [p for p in _events("post.created") if p["post_id"] == pending["id"]][0]
    handlers.on_post_created_tags(_envelope("post.created", created))
    assert _events("post.tagged") == []  # nobody while it waits, not even the staff

    approve = reverse(
        "posts:group-post-approval", kwargs={"post_id": pending["id"], "action": "approve"}
    )
    assert client_for(moderator).post(approve).status_code == 200
    (approved,) = _events("post.approved")
    assert approved == {
        "post_id": pending["id"],
        "group_id": group.id,
        "author_id": author,
        "approved_by": moderator,
        "tagged_ids": [tagged, moderator],
    }
    handlers.on_post_approved_tags(_envelope("post.approved", approved))
    recipients = sorted(p["recipient"] for p in _events("post.tagged"))
    assert recipients == sorted([tagged, moderator])
    if os.path.isdir(SCHEMAS):
        with open(f"{SCHEMAS}/post.approved.v1.json", encoding="utf-8") as f:
            schema = json.load(f)
        assert set(schema["required"]) <= set(approved) <= set(schema["properties"])


def test_a_declined_group_post_never_tells_its_tagged_people(
    client_for,
    profile,  # noqa: F811
    monkeypatch,
):
    monkeypatch.setattr("posts.services.get_relationship", lambda a, b: Relationship())
    group = Group(profile, post_approval=True)
    author, tagged, admin = group.member(), group.member(), group.member("admin")
    client_for(tagged).patch(
        reverse("posts:post-settings"), {"who_can_tag": "everyone"}, format="json"
    )
    post_id = _post(client_for(author), group, tagged_ids=[tagged]).json()["data"]["id"]
    decline = reverse("posts:group-post-approval", kwargs={"post_id": post_id, "action": "decline"})
    assert client_for(admin).post(decline).status_code == 204
    assert _events("post.approved") == []
    assert composer.notify_tags(actor_id=author, post_id=post_id, account_ids=[tagged]) == 0


# ---- #6: media's visibility check sees a draft as live for its author -----------------


def test_the_internal_check_keeps_a_draft_live_for_its_author(
    client_for,
    api_client_internal,  # noqa: F811
):
    author, other = _acct(), _acct()
    client = client_for(author)
    draft = _create(client, body="draft", draft=True).json()["data"]["id"]
    scheduled = _create(client, body="later", draft=True).json()["data"]["id"]
    Post.objects.filter(id=scheduled).update(state="scheduled")

    def visible(post_id, viewer):
        url = reverse("internal-post-visibility", kwargs={"post_id": post_id})
        return api_client_internal.get(url, {"viewer_id": viewer}).json()["data"]["visible"]

    assert visible(draft, author) is True  # media: still attached, not released
    assert visible(scheduled, author) is True
    assert visible(draft, other) is False
    # The public API still does not serve it, to the author either.
    assert client.get(reverse("posts:post-detail", args=[draft])).status_code == 404
    client.delete(reverse("posts:draft-detail", args=[draft]))
    assert visible(draft, author) is False  # a deleted draft lets its media go
    Post.objects.filter(id=scheduled).update(moderation_status=Post.ModerationStatus.REMOVED)
    assert visible(scheduled, author) is False


# ---- #7: a location keeps the joiners Arabic-script text and emoji need -----------------


@pytest.mark.parametrize(
    "text",
    [
        "\u0645\u06cc\u200c\u062e\u0627\u0646\u0647",  # Persian, with a ZWNJ
        "\u062f\u0627\u0646\u0634\u06af\u0627\u0647\u200c\u0647\u0627",
        "\U0001f468\u200d\U0001f469\u200d\U0001f467 Cairo",  # an emoji ZWJ sequence
    ],
)
def test_a_location_keeps_zwnj_and_zwj(text):
    assert composer.clean_location(text) == text


def test_a_location_still_drops_bidi_and_loose_joiners():
    assert composer.clean_location("Cairo\u202e\u2066 Egypt\u200f") == "Cairo Egypt"
    assert composer.clean_location("\u200cCairo\u200d\u200d\u200dx \u200d Egypt\u200c") == (
        "Cairo\u200dx Egypt"
    )
