"""Milestone 1.11: group posts in post — the group read model, the forced group
audience, approvals, the group's staff, announcements, reports and visibility."""

import json
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from posts import groups, services
from posts.handlers import on_group_changed, on_group_member_changed
from posts.models import (
    BlockedPair,
    Comment,
    CommentReport,
    GroupMembership,
    GroupRef,
    OutboxEvent,
    Post,
    PostReport,
)
from tara_common.auth import mint_internal_token
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db


def acct() -> str:
    return str(uuid.uuid4())


class FakeProfile:
    """Profile's authoritative answer (``/internal/v1/groups/<id>/access/``).
    ``down`` makes it unreachable; ``calls`` counts the synchronous checks."""

    def __init__(self):
        self.groups: dict[str, dict] = {}
        self.members: dict[tuple[str, str], dict] = {}
        self.down = False
        self.calls = 0

    def fetch(self, group_id, account_id):
        self.calls += 1
        if self.down:
            return None
        group = self.groups.get(str(group_id))
        if group is None:
            return groups._MISSING
        member = self.members.get((str(group_id), str(account_id)))
        owners = [a for (g, a), m in self.members.items() if g == str(group_id)]
        owners = [a for a in owners if self.members[(str(group_id), a)]["role"] == "owner"]
        return {
            "group": group,
            "member": {
                "account_id": str(account_id),
                "role": member["role"] if member else None,
                "state": member["state"] if member else "none",
                "notify_posts": member["notify_posts"] if member else False,
            },
            "owner_ids": owners,
        }


@pytest.fixture(autouse=True)
def profile(monkeypatch):
    fake = FakeProfile()
    monkeypatch.setattr(groups, "_fetch", fake.fetch)
    cache.clear()
    return fake


_clock = {"t": datetime(2026, 1, 1, tzinfo=UTC)}


def _tick() -> str:
    """Each bus event happens after the previous one and not before now (the
    synchronous check stores what it read as of now)."""
    _clock["t"] = max(_clock["t"] + timedelta(milliseconds=1), timezone.now())
    return _clock["t"].isoformat()


def _bus(event_type: str, payload: dict, *, at: str | None = None) -> None:
    envelope = EventEnvelope(
        event_type=event_type,
        subject_id=payload["group_id"],
        producer="profile-service",
        payload=payload,
        occurred_at=at or _tick(),
    )
    if event_type == "group.member.changed":
        on_group_member_changed(envelope)
    else:
        on_group_changed(envelope)


class Group:
    """A group known to profile and, through the bus, to post's read model."""

    def __init__(self, profile, privacy="public", post_approval=False, handle="riders"):
        self.profile = profile
        self.id = acct()
        self.owner = acct()
        self.data = {
            "group_id": self.id,
            "handle": "" if privacy == "hidden" else handle,
            "name": "" if privacy == "hidden" else "Riders",
            "privacy": privacy,
            "category": "sports",
            "post_approval": post_approval,
            "membership_approval": False,
            "status": "active",
        }
        profile.groups[self.id] = self.data
        _bus("group.created", dict(self.data))
        self.set(self.owner, "owner", "active")

    def set(self, account, role, state, *, notify=False, bus=True):
        if state == "none":
            self.profile.members.pop((self.id, account), None)
        else:
            self.profile.members[(self.id, account)] = {
                "role": role,
                "state": state,
                "notify_posts": notify,
            }
        if bus:
            _bus(
                "group.member.changed",
                {
                    "group_id": self.id,
                    "account_id": account,
                    "role": role if state != "none" else None,
                    "state": state,
                    "notify_posts": notify,
                },
            )
        return account

    def member(self, role="member", **kw):
        return self.set(acct(), role, "active", **kw)

    def update(self, **changes):
        self.data.update(changes)
        _bus("group.updated", dict(self.data))


def _outbox(event_type: str) -> list[dict]:
    rows = OutboxEvent.objects.filter(event_type=event_type).order_by("created_at", "id")
    return [r.payload["payload"] for r in rows]


def _code(resp) -> str:
    return resp.json()["error"]["code"]


def _post(client, group, body="Hello group", **extra):
    return client.post(
        reverse("posts:post-create"), {"body": body, "group_id": group.id, **extra}, format="json"
    )


def _feed(client, group, view="discussion"):
    return client.get(reverse("posts:group-feed", kwargs={"group_id": group.id}), {"view": view})


def _ids(resp) -> list[str]:
    return [p["id"] for p in resp.json()["data"]]


# ---- posting -----------------------------------------------------------------------


def test_a_group_post_gets_the_group_audience_whatever_the_client_sent(client_for, profile):
    group = Group(profile)
    member = group.member()
    resp = _post(client_for(member), group, audience="public")
    assert resp.status_code == 201, resp.content
    data = resp.json()["data"]
    assert data["audience"] == "group" and data["group_id"] == group.id
    assert data["approval_state"] == "approved"
    created = _outbox("post.created")[-1]
    assert created["audience"] == "group" and created["group_id"] == group.id


def test_group_posts_bind_their_media_restricted(client_for, profile, media_stub):
    group = Group(profile)
    member = group.member()
    media_id = media_stub.add(member)
    resp = _post(client_for(member), group, media_ids=[media_id], type="image")
    assert resp.status_code == 201
    assert media_stub.binds[-1]["restricted"] is True


def test_only_members_post(client_for, profile):
    public, hidden = Group(profile, "public"), Group(profile, "hidden")
    stranger = acct()
    resp = _post(client_for(stranger), public)
    assert resp.status_code == 403 and _code(resp) == "not_group_member"
    assert _post(client_for(stranger), hidden).status_code == 404
    resp = client_for(stranger).post(
        reverse("posts:post-create"), {"body": "x", "audience": "group"}, format="json"
    )
    assert resp.status_code == 400
    assert not Post.objects.exists()


def test_a_banned_member_cannot_post_even_before_the_ban_reaches_the_read_model(
    client_for, profile
):
    group = Group(profile)
    member = group.member()
    group.set(member, "member", "banned", bus=False)  # still "active" in the read model
    assert GroupMembership.objects.get(account_id=member).state == "active"
    assert _post(client_for(member), group).status_code == 404
    # The synchronous answer was kept, so the read model is banned now too.
    assert GroupMembership.objects.get(account_id=member).state == "banned"


def test_a_removed_member_cannot_post_or_comment(client_for, profile):
    group = Group(profile, "private")
    member, other = group.member(), group.member()
    post_id = _post(client_for(other), group).json()["data"]["id"]
    group.set(member, None, "none", bus=False)  # removed; the event is still on the bus
    resp = _post(client_for(member), group)
    assert resp.status_code == 404  # a private group's content is hidden from a non-member
    resp = client_for(member).post(
        reverse("posts:post-comments", args=[post_id]), {"body": "hi"}, format="json"
    )
    assert resp.status_code == 404


def test_the_read_model_decides_when_profile_is_down_and_fails_closed(client_for, profile):
    group = Group(profile)
    banned, active = group.member(), group.member()
    group.set(banned, "member", "banned")  # the ban reached the read model
    profile.down = True
    assert _post(client_for(banned), group).status_code == 404
    assert _post(client_for(active), group).status_code == 201  # the read model says active
    unknown = Group(profile)
    newcomer = acct()
    unknown.set(newcomer, "member", "active", bus=False)  # no row in the read model
    assert _post(client_for(newcomer), unknown).status_code == 403  # fail closed
    GroupRef.objects.filter(group_id=unknown.id).delete()
    assert _post(client_for(unknown.owner), unknown).status_code == 404


def test_a_missing_row_falls_back_to_profile_and_is_kept(client_for, profile):
    group = Group(profile)
    member = group.set(acct(), "member", "active", bus=False)  # the join is still on the bus
    resp = _feed(client_for(member), group)
    assert resp.status_code == 200
    row = GroupMembership.objects.get(group_id=group.id, account_id=member)
    assert row.state == "active"
    # A banned account that the bus has not told post about yet: the fallback says no.
    banned = group.set(acct(), "member", "banned", bus=False)
    assert _post(client_for(banned), group).status_code == 404


def test_an_approval_still_on_the_bus_is_seen_at_once(client_for, profile):
    group = Group(profile, "private")
    joiner = group.set(acct(), "member", "requested")
    assert _feed(client_for(joiner), group).status_code == 404
    group.set(joiner, "member", "active", bus=False)  # approved; the event is in flight
    cache.clear()  # past the recheck throttle
    assert _feed(client_for(joiner), group).status_code == 200
    assert GroupMembership.objects.get(account_id=joiner).state == "active"


def test_strangers_are_answered_from_a_short_negative_cache(client_for, profile):
    group = Group(profile, "private")
    stranger = acct()
    for _ in range(3):
        assert _feed(client_for(stranger), group).status_code == 404
    assert profile.calls == 1
    assert not GroupMembership.objects.filter(account_id=stranger).exists()
    group.set(stranger, "member", "active")  # the join event clears the negative entry
    assert _feed(client_for(stranger), group).status_code == 200


# ---- the visibility matrix ---------------------------------------------------------


def _matrix_viewers(group):
    member = group.member()
    banned = group.set(acct(), "member", "banned")
    blocked_by_owner, blocking_owner = acct(), acct()
    BlockedPair.objects.create(blocker_id=group.owner, blocked_id=blocked_by_owner)
    BlockedPair.objects.create(blocker_id=blocking_owner, blocked_id=group.owner)
    return {
        "member": member,
        "stranger": acct(),
        "banned": banned,
        "blocked_by_owner": blocked_by_owner,
        "blocking_owner": blocking_owner,
    }


EXPECTED = {
    "public": {"member", "stranger"},
    "private": {"member"},
    "hidden": {"member"},
}


@pytest.mark.parametrize("privacy", ["public", "private", "hidden"])
def test_group_post_visibility_matrix(client_for, profile, privacy):
    group = Group(profile, privacy)
    viewers = _matrix_viewers(group)
    post_id = _post(client_for(group.owner), group).json()["data"]["id"]
    for who, account in viewers.items():
        client = client_for(account)
        sees = who in EXPECTED[privacy]
        detail = client.get(reverse("posts:post-detail", args=[post_id]))
        assert detail.status_code == (200 if sees else 404), (privacy, who)
        feed = _feed(client, group)
        assert feed.status_code == (200 if sees else 404), (privacy, who)
        batch = client.post(reverse("posts:post-batch"), {"ids": [post_id]}, format="json")
        assert _ids(batch) == ([post_id] if sees else []), (privacy, who)
        assert services.visible_to_viewer(account, Post.objects.get(id=post_id)) is sees


def test_blocks_with_the_author_hide_a_post_both_ways(client_for, profile):
    group = Group(profile)
    author, reader = group.member(), group.member()
    post_id = _post(client_for(author), group).json()["data"]["id"]
    BlockedPair.objects.create(blocker_id=reader, blocked_id=author)
    assert client_for(reader).get(reverse("posts:post-detail", args=[post_id])).status_code == 404
    assert _ids(_feed(client_for(reader), group)) == []
    BlockedPair.objects.all().delete()
    BlockedPair.objects.create(blocker_id=author, blocked_id=reader)
    assert _ids(_feed(client_for(reader), group)) == []


def test_a_removed_or_deleted_group_hides_its_posts(client_for, profile):
    group = Group(profile)
    member = group.member()
    post_id = _post(client_for(member), group).json()["data"]["id"]
    group.update(status="suspended")
    assert client_for(member).get(reverse("posts:post-detail", args=[post_id])).status_code == 404
    group.update(status="active")
    assert client_for(member).get(reverse("posts:post-detail", args=[post_id])).status_code == 200
    _bus("group.deleted", {**group.data, "status": "deleted"})
    group.update(status="active")  # a late update cannot revive a deleted group
    assert GroupRef.objects.get(group_id=group.id).status == "deleted"
    assert client_for(member).get(reverse("posts:post-detail", args=[post_id])).status_code == 404


def test_older_events_never_overwrite_newer_ones(profile):
    group = Group(profile)
    member = acct()
    late = _tick()
    group.set(member, "member", "banned")
    _bus(
        "group.member.changed",
        {"group_id": group.id, "account_id": member, "role": "member", "state": "active"},
        at=late,
    )
    assert GroupMembership.objects.get(account_id=member).state == "banned"


def test_group_posts_never_reach_timelines_or_the_wider_feed(client_for, profile):
    group = Group(profile)
    member = group.member()
    post_id = _post(client_for(member), group).json()["data"]["id"]
    timeline = client_for(member).get(reverse("posts:post-create"), {"author_id": member})
    assert post_id not in _ids(timeline)
    # Feed fans out only the author's own item for an audience it does not know.
    assert _outbox("post.created")[-1]["audience"] == "group"


# ---- approval ----------------------------------------------------------------------


def test_post_approval_holds_members_posts_but_not_the_staffs(client_for, profile):
    group = Group(profile, "private", post_approval=True)
    member, other = group.member(), group.member()
    watcher = group.member(notify=True)
    moderator = group.member("moderator")
    pending = _post(client_for(member), group).json()["data"]
    assert pending["approval_state"] == "pending"
    assert _post(client_for(moderator), group).json()["data"]["approval_state"] == "approved"
    assert pending["id"] not in _ids(_feed(client_for(other), group))
    assert (
        client_for(other).get(reverse("posts:post-detail", args=[pending["id"]])).status_code == 404
    )
    assert _ids(_feed(client_for(member), group, "pending")) == [pending["id"]]
    assert _ids(_feed(client_for(other), group, "pending")) == []
    assert _ids(_feed(client_for(moderator), group, "pending")) == [pending["id"]]
    published_before = len(_outbox("group.post.published"))
    approve = reverse(
        "posts:group-post-approval", kwargs={"post_id": pending["id"], "action": "approve"}
    )
    assert client_for(other).post(approve).status_code == 403
    resp = client_for(moderator).post(approve)
    assert resp.status_code == 200 and resp.json()["data"]["approval_state"] == "approved"
    assert pending["id"] in _ids(_feed(client_for(other), group))
    published = _outbox("group.post.published")[published_before:]
    assert published[-1]["recipients"] == [watcher]
    assert published[-1]["post_id"] == pending["id"]
    assert client_for(moderator).post(approve).status_code == 409


def test_a_declined_post_is_deleted(client_for, profile):
    group = Group(profile, post_approval=True)
    member, admin = group.member(), group.member("admin")
    post_id = _post(client_for(member), group).json()["data"]["id"]
    decline = reverse("posts:group-post-approval", kwargs={"post_id": post_id, "action": "decline"})
    assert client_for(admin).post(decline).status_code == 204
    assert Post.objects.get(id=post_id).deleted_at is not None
    assert _outbox("post.deleted")[-1] == {"post_id": post_id, "by": "group", "group_id": group.id}


def test_new_post_notifications_go_only_to_members_who_opted_in(client_for, profile):
    group = Group(profile)
    author = group.member(notify=True)
    opted, quiet, blocker = group.member(notify=True), group.member(), group.member(notify=True)
    BlockedPair.objects.create(blocker_id=blocker, blocked_id=author)
    _post(client_for(author), group)
    event = _outbox("group.post.published")[-1]
    assert event["recipients"] == [opted]
    assert quiet not in event["recipients"] and event["handle"] == "riders"


# ---- the group's staff -------------------------------------------------------------


def test_moderators_delete_posts_and_comments_in_their_group(client_for, profile):
    group = Group(profile)
    author, other, moderator = group.member(), group.member(), group.member("moderator")
    post_id = _post(client_for(author), group).json()["data"]["id"]
    comment = client_for(author).post(
        reverse("posts:post-comments", args=[post_id]), {"body": "mine"}, format="json"
    )
    comment_id = comment.json()["data"]["id"]
    assert (
        client_for(other).delete(reverse("posts:comment-detail", args=[comment_id])).status_code
        == 403
    )
    assert client_for(other).delete(reverse("posts:post-detail", args=[post_id])).status_code == 403
    resp = client_for(moderator).delete(reverse("posts:comment-detail", args=[comment_id]))
    assert resp.status_code == 200
    assert _outbox("comment.deleted")[-1]["by"] == "group_moderator"
    assert (
        client_for(moderator).delete(reverse("posts:post-detail", args=[post_id])).status_code
        == 204
    )
    assert _outbox("post.deleted")[-1]["by"] == "group"


def test_a_demoted_moderator_is_refused_at_once(client_for, profile):
    group = Group(profile)
    author, moderator = group.member(), group.member("moderator")
    post_id = _post(client_for(author), group).json()["data"]["id"]
    group.set(moderator, "member", "active", bus=False)  # demoted; the event is in flight
    resp = client_for(moderator).delete(reverse("posts:post-detail", args=[post_id]))
    assert resp.status_code == 403


def test_pinning_an_announcement_tells_the_members(client_for, profile):
    group = Group(profile)
    author, member, admin = group.member(), group.member(), group.member("admin")
    first = _post(client_for(author), group).json()["data"]["id"]
    second = _post(client_for(author), group).json()["data"]["id"]
    pin = reverse("posts:post-pin", args=[first])
    assert client_for(member).post(pin).status_code == 403
    resp = client_for(admin).post(pin)
    assert resp.status_code == 200 and resp.json()["data"]["pinned_at"]
    client_for(admin).post(reverse("posts:post-pin", args=[second]))
    assert _ids(_feed(client_for(member), group, "featured")) == [second, first]
    pinned = _outbox("group.announcement.pinned")
    assert len(pinned) == 2
    assert set(pinned[0]["recipients"]) == {group.owner, author, member}
    client_for(admin).delete(pin)
    assert _ids(_feed(client_for(member), group, "featured")) == [second]


def test_non_members_read_a_public_group_but_only_members_comment(client_for, profile):
    group = Group(profile)
    post_id = _post(client_for(group.owner), group).json()["data"]["id"]
    stranger = acct()
    assert client_for(stranger).get(reverse("posts:post-detail", args=[post_id])).status_code == 200
    resp = client_for(stranger).post(
        reverse("posts:post-comments", args=[post_id]), {"body": "hi"}, format="json"
    )
    assert resp.status_code == 403 and _code(resp) == "not_group_member"


def test_only_public_group_posts_can_be_shared(client_for, profile):
    public, private = Group(profile, "public"), Group(profile, "private", handle="p")
    member = acct()
    public.set(member, "member", "active")
    private.set(member, "member", "active")
    open_post = _post(client_for(public.owner), public).json()["data"]["id"]
    closed_post = _post(client_for(private.owner), private).json()["data"]["id"]
    share = client_for(member).post(
        reverse("posts:post-share", args=[open_post]), {}, format="json"
    )
    assert share.status_code == 201 and share.json()["data"]["audience"] == "public"
    resp = client_for(member).post(
        reverse("posts:post-share", args=[closed_post]), {}, format="json"
    )
    assert resp.status_code == 400 and _code(resp) == "group_post_not_shareable"


def test_a_group_post_keeps_its_audience_on_edit(client_for, profile):
    group = Group(profile)
    member = group.member()
    post_id = _post(client_for(member), group).json()["data"]["id"]
    resp = client_for(member).patch(
        reverse("posts:post-detail", args=[post_id]), {"audience": "public"}, format="json"
    )
    assert resp.status_code == 400 and _code(resp) == "group_audience"
    resp = client_for(member).patch(
        reverse("posts:post-detail", args=[post_id]), {"body": "edited"}, format="json"
    )
    assert resp.status_code == 200 and resp.json()["data"]["audience"] == "group"


# ---- the group's reported-content queue --------------------------------------------


def test_reported_content_reaches_the_groups_moderators(client_for, profile):
    group = Group(profile)
    author, member, moderator = group.member(), group.member(), group.member("moderator")
    post_id = _post(client_for(author), group).json()["data"]["id"]
    comment_id = (
        client_for(author)
        .post(reverse("posts:post-comments", args=[post_id]), {"body": "rude"}, format="json")
        .json()["data"]["id"]
    )
    client_for(member).post(reverse("posts:post-report", args=[post_id]), {"reason": "spam"})
    client_for(member).post(
        reverse("posts:comment-report", args=[comment_id]), {"reason": "harassment"}
    )
    assert PostReport.objects.count() == 1 and CommentReport.objects.count() == 1
    url = reverse("posts:group-reports", kwargs={"group_id": group.id})
    assert client_for(member).get(url).status_code == 403
    items = client_for(moderator).get(url).json()["data"]
    assert {(i["target_type"], i["target_id"]) for i in items} == {
        ("post", post_id),
        ("comment", comment_id),
    }
    dismiss = reverse("posts:group-report-dismiss", kwargs={"group_id": group.id})
    resp = client_for(moderator).post(
        dismiss, {"target_type": "comment", "target_id": comment_id}, format="json"
    )
    assert resp.status_code == 204
    items = client_for(moderator).get(url).json()["data"]
    assert [(i["target_type"], i["report_count"]) for i in items] == [("post", 1)]
    assert Comment.objects.get(id=comment_id).deleted_at is None


# ---- media of a group (the cover) --------------------------------------------------


def test_the_cover_follows_the_groups_own_visibility(api_client_internal, profile):
    hidden = Group(profile, "hidden")
    member = hidden.member()
    url = reverse("internal-post-visibility", kwargs={"post_id": hidden.id})

    def visible(viewer):
        return api_client_internal.get(url, {"viewer_id": viewer}).json()["data"]["visible"]

    assert visible(member) is True
    assert visible(acct()) is False
    private = Group(profile, "private", handle="private_one")
    url = reverse("internal-post-visibility", kwargs={"post_id": private.id})
    assert visible(acct()) is True
    banned = private.set(acct(), "member", "banned")
    assert visible(banned) is False
    url = reverse("internal-post-visibility", kwargs={"post_id": acct()})
    assert visible(member) is False  # no such post, event or group: fails closed


@pytest.fixture
def api_client_internal():
    from rest_framework.test import APIClient

    client = APIClient()
    token = mint_internal_token(issuer="media", audience="post-internal")
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


# ---- event contracts ---------------------------------------------------------------

SCHEMAS = "/opt/tara/libs/tara_events/tara_events/schemas"
_TYPES = {"string": str, "integer": int, "array": list, "boolean": bool, "null": type(None)}


def _check(payload: dict, schema: dict) -> None:
    title = schema["title"]
    assert set(schema["required"]) <= set(payload) <= set(schema["properties"]), (title, payload)
    for key, value in payload.items():
        rule = schema["properties"][key]
        kinds = rule["type"] if isinstance(rule["type"], list) else [rule["type"]]
        assert isinstance(value, tuple(_TYPES[k] for k in kinds)), (title, key, value)


def test_group_post_events_match_their_json_schemas(client_for, profile):
    if not os.path.isdir(SCHEMAS):
        pytest.skip("schemas are copied into the image at /opt/tara/libs")
    group = Group(profile)
    author = group.member()
    group.member(notify=True)
    admin = group.member("admin")
    post_id = _post(client_for(author), group).json()["data"]["id"]
    client_for(admin).post(reverse("posts:post-pin", args=[post_id]))
    seen = set()
    for row in OutboxEvent.objects.filter(event_type__startswith="group."):
        with open(f"{SCHEMAS}/{row.event_type}.v1.json", encoding="utf-8") as f:
            _check(row.payload["payload"], json.load(f))
        seen.add(row.event_type)
    assert seen == {"group.post.published", "group.announcement.pinned"}
