"""Milestone 1.11: notifications for groups, their aggregation and deep links."""

import uuid

import pytest

from notifications import handlers, registry
from notifications.models import Notification
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _event(event_type, payload, *, actor_id=None, producer="profile-service"):
    return EventEnvelope(
        event_type=event_type,
        subject_id=payload.get("group_id") or _acct(),
        producer=producer,
        payload=payload,
        actor_id=actor_id,
    )


def _member(group_id, account, action, *, actor=None, handle="riders", **extra):
    payload = {
        "group_id": group_id,
        "account_id": account,
        "role": "member",
        "state": "active",
        "previous_role": None,
        "previous_state": "none",
        "action": action,
        "notify_posts": False,
        "privacy": "public",
        "handle": handle,
        "recipients": [],
        **extra,
    }
    handlers.on_group_member_changed(_event("group.member.changed", payload, actor_id=actor))


def _rows(kind: str):
    return list(Notification.objects.filter(kind=kind).order_by("created_at", "id"))


KINDS = [
    "group.invite",
    "group.request",
    "group.approved",
    "group.post",
    "group.role",
    "group.announcement",
]


@pytest.mark.parametrize("kind", KINDS)
def test_group_kinds_are_registered_and_link_to_the_group(kind):
    assert registry.KINDS[kind].category == "groups"
    data = {"group_handle": "riders"}
    assert registry.build_url(kind, subject_ref="group:g1", data=data) == "/groups/riders"
    assert registry.build_url(kind, subject_ref="group:g1") == "/groups/g1"  # hidden: the id
    assert "groups" in registry.CATEGORIES


def test_requests_and_new_posts_aggregate_per_group():
    assert registry.KINDS["group.request"].aggregate == registry.PER_SUBJECT
    assert registry.KINDS["group.post"].aggregate == registry.PER_SUBJECT
    assert registry.KINDS["group.invite"].aggregate is None


def test_an_invite_reaches_the_invitee_from_the_inviter():
    group, inviter, invitee = _acct(), _acct(), _acct()
    _member(group, invitee, "invited", actor=inviter, state="invited")
    [row] = _rows("group.invite")
    assert str(row.recipient_id) == invitee and str(row.actor_id) == inviter
    assert row.subject_ref == f"group:{group}"
    assert row.data == {"group_id": group, "group_handle": "riders"}


def test_join_requests_reach_the_staff_as_one_row_per_group():
    group, owner, admin = _acct(), _acct(), _acct()
    first, second = _acct(), _acct()
    for requester in (first, second):
        _member(
            group,
            requester,
            "requested",
            actor=requester,
            state="requested",
            recipients=[owner, admin],
        )
    rows = _rows("group.request")
    assert sorted(str(r.recipient_id) for r in rows) == sorted([owner, admin])
    assert all(r.actor_count == 2 for r in rows)


def test_approval_and_role_change_reach_the_member_but_leaving_tells_nobody():
    group, moderator, member = _acct(), _acct(), _acct()
    _member(group, member, "approved", actor=moderator)
    _member(group, member, "role_changed", actor=moderator, role="moderator")
    _member(group, member, "left", actor=member, state="none", role=None)
    _member(group, member, "banned", actor=moderator, state="banned")
    assert [str(r.recipient_id) for r in _rows("group.approved")] == [member]
    [role] = _rows("group.role")
    assert role.data["role"] == "moderator"
    assert Notification.objects.count() == 2


def test_a_hidden_groups_rows_link_by_id():
    group, inviter, invitee = _acct(), _acct(), _acct()
    _member(group, invitee, "invited", actor=inviter, state="invited", handle="")
    [row] = _rows("group.invite")
    assert "group_handle" not in row.data
    assert registry.url_for(row) == f"/groups/{group}"


def test_new_posts_and_announcements_reach_the_recipients_post_chose():
    group, author, admin = _acct(), _acct(), _acct()
    opted, member = _acct(), _acct()
    post_one, post_two = _acct(), _acct()
    for post_id in (post_one, post_two):
        handlers.on_group_post_published(
            _event(
                "group.post.published",
                {
                    "group_id": group,
                    "post_id": post_id,
                    "author_id": author,
                    "handle": "riders",
                    "recipients": [opted],
                    "chunk": 0,
                    "chunks": 1,
                },
                actor_id=author,
                producer="post-service",
            )
        )
    [row] = _rows("group.post")  # two posts by one author: one row per group
    assert str(row.recipient_id) == opted
    handlers.on_group_announcement(
        _event(
            "group.announcement.pinned",
            {
                "group_id": group,
                "post_id": post_one,
                "author_id": author,
                "handle": "riders",
                "recipients": [opted, member, admin],
                "chunk": 0,
                "chunks": 1,
            },
            actor_id=admin,
            producer="post-service",
        )
    )
    assert sorted(str(r.recipient_id) for r in _rows("group.announcement")) == sorted(
        [opted, member]
    )  # never the admin who pinned it


def test_a_deleted_group_takes_its_notifications_with_it():
    group, inviter, invitee = _acct(), _acct(), _acct()
    _member(group, invitee, "invited", actor=inviter, state="invited")
    handlers.on_group_deleted(
        _event(
            "group.deleted",
            {"group_id": group, "handle": "", "name": "", "privacy": "public", "category": "other"},
        )
    )
    assert not Notification.objects.filter(subject_ref=f"group:{group}").exists()
