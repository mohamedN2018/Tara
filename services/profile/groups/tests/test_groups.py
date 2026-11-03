"""Milestone 1.11: groups in profile — visibility, roles, membership, rules,
reports, suggestions, moderation and the events they emit."""

import json
import os

import pytest
from django.urls import reverse
from profiles.models import OutboxEvent

from groups import services
from groups.handlers import on_moderation_actioned_group
from groups.models import Group, GroupMember, GroupReport
from groups.tests.conftest import acct, add_member, block, make_group
from tara_common.auth import mint_internal_token
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db


def _outbox(event_type: str) -> list[dict]:
    rows = OutboxEvent.objects.filter(event_type=event_type).order_by("created_at", "id")
    return [r.payload["payload"] for r in rows]


def _code(resp) -> str:
    return resp.json()["error"]["code"]


def _url(name: str, group, **kw) -> str:
    ref = group if isinstance(group, str) else group.handle
    return reverse(f"groups:{name}", kwargs={"ref": ref, **kw})


# ---- create ------------------------------------------------------------------------


def test_any_account_creates_a_group_and_becomes_its_owner(auth_client):
    owner = acct()
    resp = auth_client(owner).post(
        reverse("groups:group-list"),
        {
            "name": "Cairo Cyclists",
            "handle": "Cairo_Cyclists",
            "description": "Weekend rides",
            "category": "sports",
            "privacy": "private",
            "membership_approval": True,
            "rules": [{"title": "Be kind", "body": "No insults"}, {"title": "No spam"}],
        },
        format="json",
    )
    assert resp.status_code == 201, resp.content
    data = resp.json()["data"]
    assert data["handle"] == "cairo_cyclists"
    assert data["member_count"] == 1
    assert data["viewer"]["role"] == "owner" and data["viewer"]["state"] == "active"
    assert data["viewer"]["can"]["delete"] is True
    assert [r["title"] for r in data["rules"]] == ["Be kind", "No spam"]
    created = _outbox("group.created")
    assert created == [
        {
            "group_id": data["id"],
            "handle": "cairo_cyclists",
            "name": "Cairo Cyclists",
            "privacy": "private",
            "category": "sports",
            "post_approval": False,
            "membership_approval": True,
            "status": "active",
        }
    ]
    member = _outbox("group.member.changed")[0]
    assert (member["account_id"], member["role"], member["state"], member["action"]) == (
        owner,
        "owner",
        "active",
        "created",
    )


def test_a_hidden_group_never_puts_its_name_or_handle_on_the_bus():
    group = make_group(privacy="hidden", name="Secret club")
    payload = _outbox("group.created")[0]
    assert payload["privacy"] == "hidden"
    assert payload["name"] == "" and payload["handle"] == ""
    assert _outbox("group.member.changed")[0]["handle"] == ""
    services.update_group(
        str(GroupMember.objects.get(group=group).account_id),
        group,
        GroupMember.objects.get(group=group),
        {"description": "still secret"},
    )
    assert _outbox("group.updated")[0]["name"] == ""


@pytest.mark.parametrize(
    "handle,status,code",
    [
        ("ab", 400, "invalid_handle"),
        ("has space", 400, "invalid_handle"),
        ("discover", 409, "handle_taken"),
        ("new", 409, "handle_taken"),
    ],
)
def test_bad_or_reserved_handles_are_refused(auth_client, handle, status, code):
    resp = auth_client(acct()).post(
        reverse("groups:group-list"), {"name": "X", "handle": handle}, format="json"
    )
    assert resp.status_code == status and _code(resp) == code
    assert not Group.objects.exists()


def test_a_taken_handle_is_409(auth_client):
    make_group(handle="riders")
    resp = auth_client(acct()).post(
        reverse("groups:group-list"), {"name": "Other", "handle": "Riders"}, format="json"
    )
    assert resp.status_code == 409 and _code(resp) == "handle_taken"


def test_the_cover_must_be_my_own_image_and_is_bound_restricted(auth_client, media):
    owner = acct()
    mine, theirs = media.add(owner), media.add(acct())
    client = auth_client(owner)
    resp = client.post(
        reverse("groups:group-list"),
        {"name": "A", "handle": "with_cover", "cover_media_id": theirs},
        format="json",
    )
    assert resp.status_code == 400 and _code(resp) == "media_not_owned"
    resp = client.post(
        reverse("groups:group-list"),
        {"name": "A", "handle": "with_cover", "cover_media_id": mine},
        format="json",
    )
    assert resp.status_code == 201
    assert media.binds == [
        {"owner_id": owner, "post_id": resp.json()["data"]["id"], "media_id": mine}
    ]
    media.down = True
    resp = client.patch(
        _url("group-detail", "with_cover"), {"cover_media_id": media.add(owner)}, format="json"
    )
    assert resp.status_code == 503


def test_a_failure_inside_the_transaction_writes_no_group_and_no_event(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("after the group row")

    monkeypatch.setattr(services, "_emit_member", boom)
    with pytest.raises(RuntimeError):
        make_group(handle="never_saved")
    assert not Group.objects.filter(handle="never_saved").exists()
    assert not OutboxEvent.objects.filter(event_type__startswith="group.").exists()


# ---- the visibility matrix ---------------------------------------------------------


def _viewers(group, owner):
    member = add_member(group)
    banned = add_member(group, state="banned")
    blocked_by_owner, blocking_owner = acct(), acct()
    block(owner, blocked_by_owner)
    block(blocking_owner, owner)
    return {
        "member": member,
        "stranger": acct(),
        "banned": banned,
        "blocked_by_owner": blocked_by_owner,
        "blocking_owner": blocking_owner,
    }


MATRIX = {
    # privacy: {viewer: (detail status, content_visible, members list status)}
    "public": {
        "member": (200, True, 200),
        "stranger": (200, True, 200),
        "banned": (404, None, 404),
        "blocked_by_owner": (404, None, 404),
        "blocking_owner": (404, None, 404),
    },
    "private": {
        "member": (200, True, 200),
        "stranger": (200, False, 404),
        "banned": (404, None, 404),
        "blocked_by_owner": (404, None, 404),
        "blocking_owner": (404, None, 404),
    },
    "hidden": {
        "member": (200, True, 200),
        "stranger": (404, None, 404),
        "banned": (404, None, 404),
        "blocked_by_owner": (404, None, 404),
        "blocking_owner": (404, None, 404),
    },
}


@pytest.mark.parametrize("privacy", ["public", "private", "hidden"])
def test_visibility_matrix(auth_client, privacy):
    owner = acct()
    group = make_group(owner, privacy=privacy)
    for who, account in _viewers(group, owner).items():
        detail_status, content, members_status = MATRIX[privacy][who]
        client = auth_client(account)
        for ref in (group.handle, str(group.id)):
            resp = client.get(_url("group-detail", ref))
            assert resp.status_code == detail_status, (privacy, who, ref)
        if detail_status == 200:
            data = resp.json()["data"]
            assert data["content_visible"] is content, (privacy, who)
            assert data["name"] == group.name and data["description"] == group.description
        assert client.get(_url("group-members", group)).status_code == members_status, (
            privacy,
            who,
        )
        # A hidden group and an invisible one look the same on every write too.
        if detail_status == 404:
            assert client.post(_url("group-join", group)).status_code == 404
            assert (
                client.post(_url("group-report", group), {"reason": "spam"}, format="json")
            ).status_code == 404


def test_an_invitee_and_a_requester_see_a_hidden_group_but_not_its_content(auth_client):
    group = make_group(privacy="hidden")
    invitee = add_member(group, state="invited")
    requester = add_member(group, state="requested")
    for account in (invitee, requester):
        data = auth_client(account).get(_url("group-detail", group)).json()["data"]
        assert data["content_visible"] is False
        assert auth_client(account).get(_url("group-members", group)).status_code == 404


def test_discover_never_lists_hidden_groups_nor_my_own(auth_client):
    viewer = acct()
    public, private = make_group(privacy="public"), make_group(privacy="private")
    make_group(privacy="hidden")
    joined = make_group(privacy="public")
    add_member(joined, viewer)
    blocked_owner = acct()
    make_group(blocked_owner, privacy="public")
    block(viewer, blocked_owner)
    resp = auth_client(viewer).get(reverse("groups:group-list"), {"scope": "discover"})
    ids = {g["id"] for g in resp.json()["data"]}
    assert ids == {str(public.id), str(private.id)}
    mine = auth_client(viewer).get(reverse("groups:group-list"))
    assert [g["id"] for g in mine.json()["data"]] == [str(joined.id)]


def test_deleted_and_removed_groups_are_404_for_everyone(auth_client):
    owner = acct()
    group = make_group(owner)
    assert auth_client(owner).delete(_url("group-detail", group)).status_code == 204
    assert auth_client(owner).get(_url("group-detail", group)).status_code == 404
    assert _outbox("group.deleted")[0]["status"] == "deleted"


def test_member_lists_leave_out_accounts_blocked_either_way(auth_client):
    owner = acct()
    group = make_group(owner)
    viewer = add_member(group)
    blocked = add_member(group)
    block(blocked, viewer)
    rows = auth_client(viewer).get(_url("group-members", group)).json()["data"]
    assert blocked not in {r["account_id"] for r in rows}
    assert {owner, viewer} <= {r["account_id"] for r in rows}
    admins = auth_client(viewer).get(_url("group-members", group), {"role": "owner"})
    assert [r["account_id"] for r in admins.json()["data"]] == [owner]


# ---- roles and permissions ---------------------------------------------------------


def _staffed_group(**kw):
    owner = acct()
    group = make_group(owner, **kw)
    return (
        group,
        owner,
        add_member(group, role="admin"),
        add_member(group, role="moderator"),
        add_member(group),
    )


def test_role_permissions_are_checked_on_the_backend(auth_client):
    group, owner, admin, moderator, member = _staffed_group()
    edit = {"description": "new"}
    assert (
        auth_client(member).patch(_url("group-detail", group), edit, format="json").status_code
        == 403
    )
    assert (
        auth_client(moderator).patch(_url("group-detail", group), edit, format="json").status_code
        == 403
    )
    assert (
        auth_client(admin).patch(_url("group-detail", group), edit, format="json").status_code
        == 200
    )
    assert auth_client(admin).delete(_url("group-detail", group)).status_code == 403
    rule = {"title": "Be kind"}
    assert (
        auth_client(moderator).post(_url("group-rules", group), rule, format="json").status_code
        == 403
    )
    assert (
        auth_client(admin).post(_url("group-rules", group), rule, format="json").status_code == 201
    )
    # Requests are moderator work; a plain member cannot see them.
    assert (
        auth_client(member).get(_url("group-members", group), {"state": "requested"}).status_code
        == 403
    )
    assert (
        auth_client(moderator).get(_url("group-members", group), {"state": "requested"}).status_code
        == 200
    )
    can = auth_client(moderator).get(_url("group-detail", group)).json()["data"]["viewer"]["can"]
    assert can["approve_posts"] and can["moderate"] and not can["edit"] and not can["change_roles"]


def test_acting_on_a_member_needs_a_higher_rank(auth_client):
    group, owner, admin, moderator, member = _staffed_group()

    def role(actor, target, new):
        return auth_client(actor).patch(
            reverse("groups:group-member-role", kwargs={"ref": group.handle, "account_id": target}),
            {"role": new},
            format="json",
        )

    def act(actor, target, action):
        return auth_client(actor).post(
            reverse(
                "groups:group-member-action",
                kwargs={"ref": group.handle, "account_id": target, "action": action},
            )
        )

    assert act(moderator, admin, "remove").status_code == 403
    assert _code(act(moderator, admin, "ban")) == "role_not_allowed"
    assert role(moderator, member, "moderator").status_code == 403  # no change_roles
    assert _code(role(admin, member, "admin")) == "role_not_allowed"  # only below admin
    assert role(admin, member, "moderator").json()["data"]["role"] == "moderator"
    assert role(admin, owner, "member").status_code == 403
    assert role(owner, admin, "owner").json()["data"]["role"] == "owner"  # a second owner
    changed = [p for p in _outbox("group.member.changed") if p["action"] == "role_changed"]
    assert [(p["account_id"], p["previous_role"], p["role"]) for p in changed] == [
        (member, "member", "moderator"),
        (admin, "admin", "owner"),
    ]
    assert act(moderator, member, "remove").status_code == 403  # equal rank now
    assert act(owner, member, "remove").status_code == 204
    assert GroupMember.objects.get(group=group, account_id=owner).role == "owner"


def test_the_last_owner_cannot_leave_be_demoted_removed_or_banned(auth_client):
    owner = acct()
    group = make_group(owner)
    client = auth_client(owner)
    resp = client.post(_url("group-leave", group))
    assert resp.status_code == 409 and _code(resp) == "last_owner"
    resp = client.patch(
        reverse("groups:group-member-role", kwargs={"ref": group.handle, "account_id": owner}),
        {"role": "admin"},
        format="json",
    )
    assert resp.status_code == 409 and _code(resp) == "last_owner"
    second = add_member(group, role="owner")
    services.ban(second, group, owner)  # owners are peers while another one remains
    assert GroupMember.objects.get(group=group, account_id=owner).state == "banned"
    client = auth_client(second)
    assert _code(client.post(_url("group-leave", group))) == "last_owner"
    resp = client.patch(
        reverse("groups:group-member-role", kwargs={"ref": group.handle, "account_id": second}),
        {"role": "member"},
        format="json",
    )
    assert resp.status_code == 409 and _code(resp) == "last_owner"
    assert GroupMember.objects.filter(group=group, state="active", role="owner").count() == 1


def test_with_two_owners_one_may_leave(auth_client):
    owner = acct()
    group = make_group(owner)
    add_member(group, role="owner")
    assert auth_client(owner).post(_url("group-leave", group)).status_code == 204
    group.refresh_from_db()
    assert group.member_count == 1
    assert _outbox("group.member.changed")[-1]["action"] == "left"


# ---- joining -----------------------------------------------------------------------


def test_join_without_approval_is_instant(auth_client):
    group = make_group(privacy="public")
    joiner = acct()
    resp = auth_client(joiner).post(_url("group-join", group))
    assert resp.status_code == 201 and resp.json()["data"]["state"] == "active"
    group.refresh_from_db()
    assert group.member_count == 2
    assert _outbox("group.member.changed")[-1]["action"] == "joined"


def test_join_with_approval_asks_the_staff_who_approve_or_decline(auth_client):
    group, owner, admin, moderator, member = _staffed_group(
        privacy="private", membership_approval=True
    )
    joiner, other = acct(), acct()
    resp = auth_client(joiner).post(_url("group-join", group))
    assert resp.json()["data"]["state"] == "requested"
    asked = _outbox("group.member.changed")[-1]
    assert asked["action"] == "requested"
    assert set(asked["recipients"]) == {owner, admin, moderator}
    assert (
        auth_client(joiner).post(_url("group-join", group)).json()["data"]["state"] == "requested"
    )
    assert len([p for p in _outbox("group.member.changed") if p["action"] == "requested"]) == 1
    group.refresh_from_db()
    assert group.member_count == 4  # nothing yet
    pending = auth_client(moderator).get(_url("group-members", group), {"state": "requested"})
    assert [r["account_id"] for r in pending.json()["data"]] == [joiner]

    def request(actor, target, action):
        return auth_client(actor).post(
            reverse(
                "groups:group-request-action",
                kwargs={"ref": group.handle, "account_id": target, "action": action},
            )
        )

    assert request(member, joiner, "approve").status_code == 403
    resp = request(moderator, joiner, "approve")
    assert resp.status_code == 200 and resp.json()["data"]["state"] == "active"
    assert _outbox("group.member.changed")[-1]["action"] == "approved"
    group.refresh_from_db()
    assert group.member_count == 5
    auth_client(other).post(_url("group-join", group))
    assert request(moderator, other, "decline").status_code == 204
    assert not GroupMember.objects.filter(group=group, account_id=other).exists()
    assert _outbox("group.member.changed")[-1]["state"] == "none"


def test_a_requester_can_take_the_request_back(auth_client):
    group = make_group(membership_approval=True)
    joiner = acct()
    auth_client(joiner).post(_url("group-join", group))
    assert auth_client(joiner).delete(_url("group-join", group)).status_code == 204
    assert _outbox("group.member.changed")[-1]["action"] == "cancelled"


def test_invites_go_to_friends_only_and_staff_invites_skip_approval(auth_client, graph):
    group, owner, admin, moderator, member = _staffed_group(
        privacy="hidden", membership_approval=True
    )
    friend, stranger, other_friend = acct(), acct(), acct()
    graph.befriend(owner, friend)
    graph.befriend(member, other_friend)
    url = _url("group-invite", group)
    resp = auth_client(owner).post(url, {"account_ids": [stranger]}, format="json")
    assert resp.status_code == 400 and _code(resp) == "invite_not_friend"
    assert auth_client(owner).post(url, {"account_ids": [friend]}, format="json").json()[
        "data"
    ] == {"invited": [friend]}
    invited = _outbox("group.member.changed")[-1]
    assert (invited["action"], invited["account_id"], invited["state"]) == (
        "invited",
        friend,
        "invited",
    )
    # The invitee sees the hidden group and joins at once (a staff invite).
    assert auth_client(friend).get(_url("group-detail", group)).status_code == 200
    assert auth_client(friend).post(_url("group-join", group)).json()["data"]["state"] == "active"
    # A plain member's invite still needs approval.
    auth_client(member).post(url, {"account_ids": [other_friend]}, format="json")
    assert (
        auth_client(other_friend).post(_url("group-join", group)).json()["data"]["state"]
        == "requested"
    )
    graph.down = True
    assert auth_client(owner).post(url, {"account_ids": [friend]}, format="json").status_code == 503


def test_an_invitee_can_decline(auth_client, graph):
    owner, friend = acct(), acct()
    graph.befriend(owner, friend)
    group = make_group(owner)
    services.invite(owner, group, [friend])
    assert auth_client(friend).delete(_url("group-join", group)).status_code == 204
    assert _outbox("group.member.changed")[-1]["action"] == "invite_declined"


def test_post_notifications_are_opt_in_per_group(auth_client):
    group = make_group()
    member = add_member(group)
    data = auth_client(member).get(_url("group-detail", group)).json()["data"]
    assert data["viewer"]["notify_posts"] is False
    resp = auth_client(member).patch(
        _url("group-membership", group), {"notify_posts": True}, format="json"
    )
    assert resp.json()["data"]["notify_posts"] is True
    last = _outbox("group.member.changed")[-1]
    assert (last["action"], last["notify_posts"]) == ("settings_changed", True)


# ---- bans --------------------------------------------------------------------------


def test_a_banned_member_loses_the_group_and_cannot_rejoin_until_unbanned(auth_client):
    group, owner, admin, moderator, member = _staffed_group(privacy="public")

    def act(actor, target, action):
        return auth_client(actor).post(
            reverse(
                "groups:group-member-action",
                kwargs={"ref": group.handle, "account_id": target, "action": action},
            )
        )

    resp = act(moderator, member, "ban")
    assert resp.status_code == 200 and resp.json()["data"]["state"] == "banned"
    group.refresh_from_db()
    assert group.member_count == 3
    assert _outbox("group.member.changed")[-1]["action"] == "banned"
    assert auth_client(member).get(_url("group-detail", group)).status_code == 404
    assert auth_client(member).post(_url("group-join", group)).status_code == 404
    banned = auth_client(moderator).get(_url("group-members", group), {"state": "banned"})
    assert [r["account_id"] for r in banned.json()["data"]] == [member]
    assert act(moderator, member, "unban").status_code == 204
    assert auth_client(member).post(_url("group-join", group)).status_code == 201


def test_staff_can_ban_someone_who_is_not_a_member():
    group, owner, *_ = _staffed_group()
    stranger = acct()
    row = services.ban(owner, group, stranger)
    assert row.state == "banned"
    assert _outbox("group.member.changed")[-1]["previous_state"] == "none"


# ---- rules -------------------------------------------------------------------------


def test_rules_crud_and_order(auth_client):
    owner = acct()
    group = make_group(owner)
    client = auth_client(owner)
    ids = [
        client.post(_url("group-rules", group), {"title": f"Rule {i}"}, format="json").json()[
            "data"
        ]["id"]
        for i in range(3)
    ]
    resp = client.patch(
        reverse("groups:group-rule-detail", kwargs={"ref": group.handle, "rule_id": ids[1]}),
        {"body": "Explained"},
        format="json",
    )
    assert resp.json()["data"]["body"] == "Explained"
    resp = client.put(
        _url("group-rule-order", group), {"ids": [ids[2], ids[0], ids[1]]}, format="json"
    )
    assert [r["id"] for r in resp.json()["data"]] == [ids[2], ids[0], ids[1]]
    assert (
        client.put(_url("group-rule-order", group), {"ids": ids[:2]}, format="json").status_code
        == 400
    )
    client.delete(
        reverse("groups:group-rule-detail", kwargs={"ref": group.handle, "rule_id": ids[2]})
    )
    rules = client.get(_url("group-rules", group)).json()["data"]
    assert [(r["id"], r["position"]) for r in rules] == [(ids[0], 0), (ids[1], 1)]
    for i in range(8):
        client.post(_url("group-rules", group), {"title": f"More {i}"}, format="json")
    resp = client.post(_url("group-rules", group), {"title": "Eleven"}, format="json")
    assert resp.status_code == 400 and _code(resp) == "too_many_rules"


# ---- reports and moderation --------------------------------------------------------


def test_a_report_needs_the_group_to_be_visible_and_counts_once(auth_client):
    owner = acct()
    group = make_group(owner, privacy="private")
    reporter = acct()
    url = _url("group-report", group)
    assert auth_client(reporter).post(url, {"reason": "spam"}, format="json").status_code == 202
    assert auth_client(reporter).post(url, {"reason": "scam"}, format="json").status_code == 202
    assert _outbox("group.reported") == [
        {"group_id": str(group.id), "reporter": reporter, "reason": "spam", "owner_id": owner}
    ]
    hidden = make_group(privacy="hidden")
    resp = auth_client(reporter).post(
        _url("group-report", hidden), {"reason": "spam"}, format="json"
    )
    assert resp.status_code == 404
    assert GroupReport.objects.count() == 1 and len(_outbox("group.reported")) == 1
    # Last: a validation error marks the test's transaction for rollback.
    assert (
        auth_client(reporter).post(url, {"reason": "free text"}, format="json").status_code == 400
    )


def _actioned(group, action):
    on_moderation_actioned_group(
        EventEnvelope(
            event_type="moderation.actioned",
            subject_id=acct(),
            producer="moderation-service",
            payload={"target_type": "group", "target_id": str(group.id), "action": action},
        )
    )


def test_moderation_removes_and_restores_a_group(auth_client):
    owner = acct()
    group = make_group(owner)
    _actioned(group, "remove")
    _actioned(group, "remove")  # a redelivery changes nothing
    assert auth_client(owner).get(_url("group-detail", group)).status_code == 404
    deleted = _outbox("group.deleted")
    assert (
        len(deleted) == 1
        and deleted[0]["status"] == "suspended"
        and deleted[0]["by"] == "moderation"
    )
    _actioned(group, "approve")
    assert auth_client(owner).get(_url("group-detail", group)).status_code == 200
    updated = _outbox("group.updated")
    assert updated[-1]["changed"] == ["status"] and updated[-1]["status"] == "active"


def test_other_moderation_targets_are_ignored():
    group = make_group()
    on_moderation_actioned_group(
        EventEnvelope(
            event_type="moderation.actioned",
            subject_id=acct(),
            producer="moderation-service",
            payload={"target_type": "post", "target_id": str(group.id), "action": "remove"},
        )
    )
    group.refresh_from_db()
    assert group.status == "active"


# ---- suggestions -------------------------------------------------------------------


def test_suggestions_rank_by_friends_never_hidden_and_can_be_dismissed(auth_client, graph):
    viewer, f1, f2 = acct(), acct(), acct()
    graph.befriend(viewer, f1)
    graph.befriend(viewer, f2)
    two_friends = make_group(privacy="private")
    one_friend = make_group(privacy="public", category="food")
    secret = make_group(privacy="hidden")
    for group, friends in ((two_friends, (f1, f2)), (one_friend, (f1,)), (secret, (f1, f2))):
        for friend in friends:
            add_member(group, friend)
    no_friend = make_group(privacy="public")
    resp = auth_client(viewer).get(reverse("groups:group-suggestions"))
    items = resp.json()["data"]
    assert [i["id"] for i in items][:3] == [
        str(two_friends.id),
        str(one_friend.id),
        str(no_friend.id),
    ]
    assert str(secret.id) not in {i["id"] for i in items}
    assert items[0]["friend_member_count"] == 2 and set(items[0]["friend_ids"]) == {f1, f2}
    auth_client(viewer).post(
        reverse("groups:group-suggestion-dismiss", kwargs={"group_id": str(two_friends.id)})
    )
    items = auth_client(viewer).get(reverse("groups:group-suggestions")).json()["data"]
    assert str(two_friends.id) not in {i["id"] for i in items}


# ---- the internal access check -----------------------------------------------------


def test_internal_access_reports_the_role_and_state_and_needs_a_token(api_client):
    owner = acct()
    group = make_group(owner, post_approval=True)
    banned = add_member(group, state="banned")
    url = reverse("group-access", kwargs={"group_id": group.id})
    assert api_client.get(url, {"account_id": owner}).status_code == 401
    token = mint_internal_token(issuer="post", audience="profile-internal")
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    data = api_client.get(url, {"account_id": banned}).json()["data"]
    assert data["member"]["state"] == "banned"
    assert data["group"]["post_approval"] is True and data["owner_ids"] == [owner]
    stranger = api_client.get(url, {"account_id": acct()}).json()["data"]
    assert stranger["member"] == {
        "account_id": stranger["member"]["account_id"],
        "role": None,
        "state": "none",
        "notify_posts": False,
    }


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
        if "enum" in rule:
            assert value in rule["enum"], (title, key, value)
        if rule.get("type") == "array" and "enum" in rule.get("items", {}):
            assert set(value) <= set(rule["items"]["enum"]), (title, key, value)


def test_every_group_event_matches_its_json_schema(graph):
    if not os.path.isdir(SCHEMAS):
        pytest.skip("schemas are copied into the image at /opt/tara/libs")
    owner, friend, joiner = acct(), acct(), acct()
    graph.befriend(owner, friend)
    group = make_group(owner, privacy="private", membership_approval=True)
    services.invite(owner, group, [friend])
    services.join(joiner, group)
    services.approve_request(owner, group, joiner)
    services.change_role(owner, group, joiner, "moderator")
    services.set_notify_posts(joiner, group, True)
    services.ban(owner, group, acct())
    services.report(acct(), group, None, "spam")
    services.update_group(owner, group, services.membership(group, owner), {"privacy": "hidden"})
    services.apply_moderation(str(group.id), "remove")
    services.apply_moderation(str(group.id), "approve")
    group.refresh_from_db()
    services.delete_group(owner, group)

    seen = set()
    for row in OutboxEvent.objects.filter(event_type__startswith="group."):
        with open(f"{SCHEMAS}/{row.event_type}.v1.json", encoding="utf-8") as f:
            _check(row.payload["payload"], json.load(f))
        seen.add(row.event_type)
    assert seen == {
        "group.created",
        "group.updated",
        "group.deleted",
        "group.member.changed",
        "group.reported",
    }


def test_suggestions_without_graph_fall_back_to_size(auth_client, graph):
    small, big = make_group(privacy="public"), make_group(privacy="private")
    add_member(big)
    graph.down = True
    items = auth_client(acct()).get(reverse("groups:group-suggestions")).json()["data"]
    assert [i["id"] for i in items][:2] == [str(big.id), str(small.id)]
    assert all(i["friend_member_count"] == 0 for i in items)
