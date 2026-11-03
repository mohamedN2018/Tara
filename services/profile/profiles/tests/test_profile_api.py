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
from profiles.models import BlockedPair, OutboxEvent, UserProfile
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
