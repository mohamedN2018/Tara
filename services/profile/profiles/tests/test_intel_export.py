"""Tara Intelligence WP 3.2: feed's group, membership and page backfill."""

import time
import uuid

import jwt
import pytest
from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from groups.models import Group, GroupMember
from rest_framework.test import APIClient

from profiles.models import Page

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _client(audience="profile-internal") -> APIClient:
    now = int(time.time())
    token = jwt.encode(
        {"iss": "feed", "aud": audience, "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def _all(name: str) -> dict:
    client, out, after = _client(), {}, None
    while True:
        params = {"limit": 1, **({"after": after} if after else {})}
        data = client.get(reverse(name), params).json()["data"]
        out.update({i["id"]: i["payload"] for i in data["items"]})
        after = data["next"]
        if after is None:
            return out


def _group(handle, **kw):
    return Group.objects.create(handle=handle, name=f"Secret {handle}", created_by=_acct(), **kw)


@pytest.mark.parametrize(
    "name", ["intel-export-groups", "intel-export-group-members", "intel-export-pages"]
)
def test_exports_need_a_profile_internal_token(name):
    assert APIClient().get(reverse(name)).status_code == 401
    assert _client("graph-internal").get(reverse(name)).status_code == 401


def test_groups_include_hidden_suspended_and_deleted_without_names():
    hidden = _group("hid", privacy="hidden", member_count=3)
    suspended = _group("sus", status="suspended")
    deleted = _group("del")
    Group.objects.filter(id=deleted.id).update(deleted_at=timezone.now())
    rows = _all("intel-export-groups")
    assert rows[str(hidden.id)] == {
        "group_id": str(hidden.id),
        "privacy": "hidden",
        "status": "active",
        "category": hidden.category,
        "member_count": 3,
    }
    assert rows[str(suspended.id)]["status"] == "suspended"
    assert rows[str(deleted.id)]["status"] == "deleted"
    assert all("name" not in r and "handle" not in r for r in rows.values())


def test_members_carry_state_role_and_notify():
    group = _group("grp", privacy="private")
    owner, banned = _acct(), _acct()
    GroupMember.objects.create(
        group=group,
        account_id=owner,
        role="owner",
        state="active",
        notify_posts=True,
        joined_at=timezone.now(),
    )
    GroupMember.objects.create(group=group, account_id=banned, state="banned")
    rows = {r["account_id"]: r for r in _all("intel-export-group-members").values()}
    assert rows[owner]["role"] == "owner" and rows[owner]["state"] == "active"
    assert rows[owner]["notify_posts"] is True and rows[owner]["joined_at"]
    assert rows[banned]["state"] == "banned" and rows[banned]["group_id"] == str(group.id)


def test_pages_include_drafts_suspended_and_deleted():
    owner = _acct()
    live = Page.objects.create(owner_account_id=owner, handle="live", name="L", created_by=owner)
    draft = Page.objects.create(
        owner_account_id=owner, handle="drf", name="D", created_by=owner, status="draft"
    )
    gone = Page.objects.create(owner_account_id=owner, handle="gone", name="G", created_by=owner)
    Page.objects.filter(id=gone.id).update(deleted_at=timezone.now())
    rows = _all("intel-export-pages")
    assert rows[str(live.id)] == {"owner": owner, "status": "published", "deleted": False}
    assert rows[str(draft.id)]["status"] == "draft"
    assert rows[str(gone.id)]["deleted"] is True
