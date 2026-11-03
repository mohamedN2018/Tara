"""Profile API + privacy + event-consumer tests."""

import time
import uuid

import jwt
import pytest
from django.conf import settings
from django.urls import reverse

from profiles import services
from profiles.clients import Relationship
from profiles.handlers import on_account_registered
from profiles.models import BlockedPair, OutboxEvent, Page, PageMember, UserProfile
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


# ---- event-driven provisioning ----------------------------------------------


def test_account_registered_provisions_profile_idempotently():
    account_id = _acct()
    env = EventEnvelope(
        event_type="account.registered",
        subject_id=account_id,
        producer="identity-service",
        payload={"email": "newbie@tara.local"},
    )
    on_account_registered(env)
    on_account_registered(env)  # duplicate delivery must not create a 2nd profile
    profiles = UserProfile.objects.filter(account_id=account_id)
    assert profiles.count() == 1
    assert profiles.first().handle  # a handle was generated


# ---- own profile ------------------------------------------------------------


def test_get_and_patch_my_profile_emits_event(auth_client):
    account_id = _acct()
    services.ensure_profile(account_id, email="me@tara.local")
    client = auth_client(account_id)

    resp = client.get(reverse("profiles:me"))
    assert resp.status_code == 200

    patch = client.patch(
        reverse("profiles:me"), {"display_name": "Nadia", "bio": "hi"}, format="json"
    )
    assert patch.status_code == 200
    assert patch.json()["data"]["display_name"] == "Nadia"
    assert OutboxEvent.objects.filter(event_type="profile.updated").exists()


# ---- public profile privacy (Graph relationship mocked) ---------------------


def test_friends_only_profile_hidden_then_visible(auth_client, monkeypatch):
    owner = _acct()
    profile = services.ensure_profile(owner, email="owner@tara.local")
    profile.visibility = "friends_only"
    profile.bio = "secret bio"
    profile.save()

    viewer = _acct()
    client = auth_client(viewer)
    url = reverse("profiles:public-profile", args=[profile.handle])

    # Not friends -> restricted card, no bio.
    monkeypatch.setattr(
        "profiles.privacy.get_relationship", lambda a, b: Relationship(are_friends=False)
    )
    resp = client.get(url)
    assert resp.status_code == 200
    assert resp.json()["data"]["restricted"] is True
    assert "bio" not in resp.json()["data"]

    # Friends -> full profile incl. bio.
    monkeypatch.setattr(
        "profiles.privacy.get_relationship", lambda a, b: Relationship(are_friends=True)
    )
    resp = client.get(url)
    assert resp.json()["data"]["restricted"] is False
    assert resp.json()["data"]["bio"] == "secret bio"


def test_blocked_profile_returns_404(auth_client, monkeypatch):
    owner = _acct()
    profile = services.ensure_profile(owner, email="owner2@tara.local")
    viewer = _acct()
    BlockedPair.objects.create(blocker_id=owner, blocked_id=viewer)  # owner blocked viewer
    monkeypatch.setattr("profiles.privacy.get_relationship", lambda a, b: Relationship())

    resp = auth_client(viewer).get(reverse("profiles:public-profile", args=[profile.handle]))
    assert resp.status_code == 404


def test_field_privacy_hides_bio_from_public(auth_client, monkeypatch):
    owner = _acct()
    profile = services.ensure_profile(owner, email="owner3@tara.local")
    profile.bio = "private bio"
    profile.save()
    services.set_field_privacy(profile, "bio", "private")

    viewer = _acct()
    monkeypatch.setattr(
        "profiles.privacy.get_relationship", lambda a, b: Relationship(are_friends=True)
    )
    resp = auth_client(viewer).get(reverse("profiles:public-profile", args=[profile.handle]))
    assert resp.status_code == 200
    assert "bio" not in resp.json()["data"]  # bio is private even to friends


# ---- pages ------------------------------------------------------------------


def test_create_page_and_member_permissions(auth_client):
    owner = _acct()
    client = auth_client(owner)
    create = client.post(
        reverse("profiles:page-create"),
        {"handle": "tara_cafe", "name": "Tara Cafe"},
        format="json",
    )
    assert create.status_code == 201
    page_id = create.json()["data"]["id"]

    # Owner can add a member.
    member_acct = _acct()
    add = client.post(
        reverse("profiles:page-members", args=[page_id]),
        {"account_id": member_acct, "role": "editor"},
        format="json",
    )
    assert add.status_code == 201

    # A non-member cannot add members.
    outsider = auth_client(_acct())
    forbidden = outsider.post(
        reverse("profiles:page-members", args=[page_id]),
        {"account_id": _acct(), "role": "editor"},
        format="json",
    )
    assert forbidden.status_code == 403


# ---- internal API -----------------------------------------------------------


def test_internal_snapshot_requires_internal_token(api_client):
    owner = _acct()
    services.ensure_profile(owner, email="snap@tara.local")
    url = reverse("profile-snapshot", args=[owner])

    assert api_client.get(url).status_code == 401

    now = int(time.time())
    token = jwt.encode(
        {"iss": "x", "aud": "profile-internal", "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    ok = api_client.get(url)
    assert ok.status_code == 200
    assert ok.json()["data"]["handle"]


# ---- lookups used to render other people ------------------------------------


def _profile(handle: str, name: str = "Name") -> UserProfile:
    return UserProfile.objects.create(account_id=_acct(), handle=handle, display_name=name)


def test_public_profile_exposes_account_id(auth_client):
    target = _profile("target")
    url = reverse("profiles:public-profile", args=["target"])
    data = auth_client(_acct()).get(url).json()["data"]
    assert data["account_id"] == str(target.account_id)


def test_profile_by_account_id_hides_blocked_users(auth_client):
    target = _profile("target2")
    viewer = _acct()
    url = reverse("profiles:public-profile-by-id", args=[target.account_id])
    assert auth_client(viewer).get(url).json()["data"]["handle"] == "target2"

    BlockedPair.objects.create(blocker_id=target.account_id, blocked_id=viewer)
    assert auth_client(viewer).get(url).status_code == 404


def test_lookup_returns_cards_without_blocked_users(auth_client):
    visible, blocked = _profile("visible", "Visible"), _profile("hidden")
    viewer = _acct()
    BlockedPair.objects.create(blocker_id=viewer, blocked_id=blocked.account_id)

    resp = auth_client(viewer).post(
        reverse("profiles:profile-lookup"),
        {"ids": [str(visible.account_id), str(blocked.account_id)]},
        format="json",
    )

    assert [c["display_name"] for c in resp.json()["data"]] == ["Visible"]


def test_registration_keeps_the_chosen_name_and_handle():
    account_id = _acct()
    event = EventEnvelope(
        event_type="account.registered",
        subject_id=account_id,
        producer="identity-service",
        payload={"email": "a@b.co", "display_name": "نور", "handle": "noor_1"},
    )
    on_account_registered(event)

    profile = UserProfile.objects.get(account_id=account_id)
    assert (profile.display_name, profile.handle) == ("نور", "noor_1")


def _page(client, handle="tara_page", **extra):
    resp = client.post(
        reverse("profiles:page-create"), {"handle": handle, "name": handle, **extra}, format="json"
    )
    assert resp.status_code == 201
    return resp.json()["data"]


def test_field_privacy_get_lists_every_field_and_rejects_unknown_ones(auth_client):
    account = _acct()
    UserProfile.objects.create(account_id=account, handle="priv_user", display_name="P")
    client = auth_client(account)
    url = reverse("profiles:field-privacy")
    assert (
        client.put(
            url, {"items": [{"field_key": "bio", "visibility": "private"}]}, format="json"
        ).status_code
        == 200
    )
    items = {i["field_key"]: i["visibility"] for i in client.get(url).json()["data"]["items"]}
    assert items["bio"] == "private"
    assert items["city"] == "public"

    bad = client.put(
        url, {"items": [{"field_key": "password", "visibility": "public"}]}, format="json"
    )
    assert bad.status_code == 400
    bad = client.put(url, {"items": [{"field_key": "bio", "visibility": "custom"}]}, format="json")
    assert bad.status_code == 400


def test_page_list_search_and_mine(auth_client):
    owner, other = _acct(), _acct()
    _page(auth_client(owner), "alpha_cafe", category="food")
    _page(auth_client(other), "beta_shop")
    client = auth_client(owner)
    url = reverse("profiles:page-create")
    handles = {p["handle"] for p in client.get(url).json()["data"]}
    assert {"alpha_cafe", "beta_shop"} <= handles
    assert [p["handle"] for p in client.get(url, {"q": "cafe"}).json()["data"]] == ["alpha_cafe"]
    mine = client.get(url, {"mine": "1"}).json()["data"]
    assert [(p["handle"], p["my_role"]) for p in mine] == [("alpha_cafe", "owner")]


def test_draft_page_is_hidden_from_outsiders(auth_client):
    owner = _acct()
    client = auth_client(owner)
    page = _page(client, "draft_page")
    detail = reverse("profiles:page-detail", args=[page["id"]])
    assert client.patch(detail, {"status": "draft"}, format="json").status_code == 200

    outsider = auth_client(_acct())
    assert outsider.get(detail).status_code == 404
    assert outsider.get(reverse("profiles:page-by-handle", args=["draft_page"])).status_code == 404
    assert "draft_page" not in str(outsider.get(reverse("profiles:page-create")).json())
    assert client.get(detail).status_code == 200


def test_blocked_owner_page_is_hidden(auth_client):
    owner, viewer = _acct(), _acct()
    page = _page(auth_client(owner), "blocked_page")
    BlockedPair.objects.create(blocker_id=owner, blocked_id=viewer)
    client = auth_client(viewer)
    assert client.get(reverse("profiles:page-detail", args=[page["id"]])).status_code == 404
    assert "blocked_page" not in str(client.get(reverse("profiles:page-create")).json())


def test_only_members_see_the_member_list(auth_client):
    owner = auth_client(_acct())
    page = _page(owner, "team_page")
    url = reverse("profiles:page-members", args=[page["id"]])
    assert len(owner.get(url).json()["data"]) == 1
    assert auth_client(_acct()).get(url).status_code == 403


def test_page_status_rules(auth_client):
    owner_id, editor_id = _acct(), _acct()
    owner = auth_client(owner_id)
    page = _page(owner, "status_page")
    owner.post(
        reverse("profiles:page-members", args=[page["id"]]),
        {"account_id": editor_id, "role": "editor"},
        format="json",
    )
    detail = reverse("profiles:page-detail", args=[page["id"]])
    editor = auth_client(editor_id)
    assert editor.patch(detail, {"description": "x"}, format="json").status_code == 200
    assert editor.patch(detail, {"status": "draft"}, format="json").status_code == 403
    assert owner.patch(detail, {"status": "suspended"}, format="json").status_code == 400

    Page.objects.filter(id=page["id"]).update(status="suspended")
    assert owner.patch(detail, {"status": "published"}, format="json").status_code == 403


def test_page_patch_ignores_fields_outside_the_allowlist(auth_client):
    owner_id = _acct()
    owner = auth_client(owner_id)
    page = _page(owner, "safe_page")
    resp = owner.patch(
        reverse("profiles:page-detail", args=[page["id"]]),
        {"name": "New", "owner_account_id": _acct(), "handle": "stolen"},
        format="json",
    )
    assert resp.status_code == 200
    stored = Page.objects.get(id=page["id"])
    assert (stored.name, stored.handle, str(stored.owner_account_id)) == (
        "New",
        "safe_page",
        owner_id,
    )


def test_member_roles_removal_and_leaving(auth_client):
    owner_id, a_id, b_id = _acct(), _acct(), _acct()
    owner = auth_client(owner_id)
    page = _page(owner, "roles_page")
    members = reverse("profiles:page-members", args=[page["id"]])
    a = owner.post(members, {"account_id": a_id, "role": "editor"}, format="json").json()["data"]
    b = owner.post(members, {"account_id": b_id, "role": "analyst"}, format="json").json()["data"]

    url_a = reverse("profiles:page-member-detail", args=[page["id"], a["id"]])
    url_b = reverse("profiles:page-member-detail", args=[page["id"], b["id"]])
    assert owner.patch(url_a, {"role": "admin"}, format="json").status_code == 200
    assert auth_client(b_id).delete(url_a).status_code == 403
    assert auth_client(b_id).delete(url_b).status_code == 204  # leaving is allowed
    assert owner.delete(url_a).status_code == 204

    owner_row = PageMember.objects.get(page_id=page["id"], account_id=owner_id)
    url_owner = reverse("profiles:page-member-detail", args=[page["id"], owner_row.id])
    assert owner.delete(url_owner).status_code == 400


def test_cannot_add_a_blocked_account_to_a_page(auth_client):
    owner_id, blocked = _acct(), _acct()
    owner = auth_client(owner_id)
    page = _page(owner, "noblock_page")
    BlockedPair.objects.create(blocker_id=blocked, blocked_id=owner_id)
    resp = owner.post(
        reverse("profiles:page-members", args=[page["id"]]),
        {"account_id": blocked, "role": "editor"},
        format="json",
    )
    assert resp.status_code == 403


def test_internal_handle_lookup_needs_a_service_token(client):
    resp = client.post(
        "/internal/v1/profiles/by-handle/",
        {"handles": ["x"]},
        content_type="application/json",
    )
    assert resp.status_code == 401


def test_a_new_profile_is_announced_so_search_can_index_it():
    account = _acct()
    services.ensure_profile(account, display_name="New Person", requested_handle="new_person")
    event = OutboxEvent.objects.get(event_type="profile.updated")
    assert event.payload["payload"]["handle"] == "new_person"
    assert event.payload["subject_id"] == account
