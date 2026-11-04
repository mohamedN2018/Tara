"""Staff see the group's pending invitations and can withdraw one; members see
their own pending join requests (``scope=requested``)."""

import pytest
from django.urls import reverse
from profiles.models import OutboxEvent

from groups.models import GroupMember
from groups.tests.conftest import acct, add_member, make_group

pytestmark = pytest.mark.django_db


def _url(name: str, group, **kw) -> str:
    return reverse(f"groups:{name}", kwargs={"ref": group.handle, **kw})


def _last_member_event() -> dict:
    row = OutboxEvent.objects.filter(event_type="group.member.changed").order_by("-created_at")
    return row.first().payload["payload"]


def test_staff_list_pending_invitations(auth_client):
    owner = acct()
    group = make_group(owner)
    invitee = add_member(group, state="invited")
    resp = auth_client(owner).get(_url("group-members", group), {"state": "invited"})
    assert resp.status_code == 200
    assert [m["account_id"] for m in resp.json()["data"]] == [invitee]


def test_a_plain_member_cannot_list_invitations(auth_client):
    group = make_group(acct())
    member = add_member(group)
    add_member(group, state="invited")
    resp = auth_client(member).get(_url("group-members", group), {"state": "invited"})
    assert resp.status_code == 403


def test_staff_revoke_an_invitation_and_the_event_says_removed(auth_client):
    owner = acct()
    group = make_group(owner)
    invitee = add_member(group, state="invited")
    resp = auth_client(owner).post(
        _url("group-invite-revoke", group, account_id=invitee, action="revoke")
    )
    assert resp.status_code == 204
    assert not GroupMember.objects.filter(group=group, account_id=invitee).exists()
    event = _last_member_event()
    assert (event["action"], event["previous_state"], event["state"]) == (
        "removed",
        "invited",
        "none",
    )


def test_revoke_needs_staff_and_a_pending_invitation(auth_client):
    owner = acct()
    group = make_group(owner)
    member = add_member(group)
    invitee = add_member(group, state="invited")
    url = _url("group-invite-revoke", group, account_id=invitee, action="revoke")
    assert auth_client(member).post(url).status_code == 403
    # An active member is not an invitation: nothing to withdraw.
    active = _url("group-invite-revoke", group, account_id=member, action="revoke")
    assert auth_client(owner).post(active).status_code == 404
    assert GroupMember.objects.filter(group=group, account_id=member, state="active").exists()


def test_my_pending_requests_are_listed_with_scope_requested(auth_client):
    group = make_group(acct(), membership_approval=True)
    other = make_group(acct())
    me = acct()
    add_member(group, me, state="requested")
    add_member(other, me)
    resp = auth_client(me).get(reverse("groups:group-list"), {"scope": "requested"})
    assert resp.status_code == 200
    assert [g["id"] for g in resp.json()["data"]] == [str(group.id)]


def test_managed_scope_lists_only_groups_where_i_am_staff(auth_client):
    me = acct()
    owned = make_group(me)
    moderated = make_group(acct())
    add_member(moderated, me, role="moderator")
    plain = make_group(acct())
    add_member(plain, me)
    invited = make_group(acct())
    add_member(invited, me, state="invited")
    resp = auth_client(me).get(reverse("groups:group-list"), {"scope": "managed"})
    assert resp.status_code == 200
    assert {g["id"] for g in resp.json()["data"]} == {str(owned.id), str(moderated.id)}
