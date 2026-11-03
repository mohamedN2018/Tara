"""Avatars and covers are the account's own images (checked with media, fail
closed); page contact details are bounded and their links are http(s) only."""

import uuid

import jwt
import pytest
from django.conf import settings
from django.urls import reverse

from profiles import media_client, services
from profiles.models import Page, UserProfile
from tara_resilience import CircuitBreaker

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


class _Resp:
    def __init__(self, rows):
        self.rows = rows

    def raise_for_status(self):
        return None

    def json(self):
        return {"data": self.rows}


@pytest.fixture
def media(monkeypatch):
    """Media's batch answer: ``media.add(id, owner, kind=..., status=...)``."""
    monkeypatch.setattr(media_client, "_breaker", CircuitBreaker(name="media-test"))

    class _Media:
        def __init__(self):
            self.rows: dict[str, dict] = {}
            self.calls: list[dict] = []
            self.down = False

        def add(self, owner, *, kind="image", status="ready") -> str:
            media_id = _acct()
            self.rows[media_id] = {
                "id": media_id,
                "owner_id": owner,
                "kind": kind,
                "status": status,
            }
            return media_id

        def post(self, url, json, headers, timeout):
            self.calls.append({"url": url, "json": json, "headers": headers})
            if self.down:
                raise ConnectionError("media down")
            return _Resp([self.rows[i] for i in json["ids"] if i in self.rows])

    stub = _Media()
    monkeypatch.setattr(media_client.requests, "post", stub.post)
    return stub


def _patch(auth_client, owner, **fields):
    return auth_client(owner).patch(reverse("profiles:me"), fields, format="json")


@pytest.mark.parametrize("field", ["avatar_media_id", "cover_media_id"])
@pytest.mark.parametrize("status", ["processing", "ready"])
def test_my_own_image_can_be_my_avatar_or_cover(auth_client, media, field, status):
    owner = _acct()
    services.ensure_profile(owner)
    media_id = media.add(owner, status=status)
    resp = _patch(auth_client, owner, **{field: media_id})
    assert resp.status_code == 200
    assert resp.json()["data"][field] == media_id
    (call,) = media.calls
    assert call["url"] == f"{settings.MEDIA_INTERNAL_URL}/internal/v1/media/batch/"
    token = call["headers"]["Authorization"].split()[1]
    claims = jwt.decode(
        token, settings.TARA_INTERNAL_JWT_SECRET, algorithms=["HS256"], audience="media-internal"
    )
    assert claims["iss"] == "profile"


@pytest.mark.parametrize(
    ("make", "code"),
    [
        (lambda m, owner: m.add(_acct()), "media_not_owned"),  # someone else's photo
        (lambda m, owner: _acct(), "media_not_owned"),  # unknown or deleted
        (lambda m, owner: m.add(owner, kind="file"), "media_kind_not_allowed"),
        (lambda m, owner: m.add(owner, kind="video"), "media_kind_not_allowed"),
        (lambda m, owner: m.add(owner, status="uploading"), "media_not_ready"),
        (lambda m, owner: m.add(owner, status="failed"), "media_not_ready"),
    ],
)
def test_anything_else_is_refused_and_nothing_changes(auth_client, media, make, code):
    owner = _acct()
    services.ensure_profile(owner)
    resp = _patch(auth_client, owner, avatar_media_id=make(media, owner), display_name="New")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == code
    profile = UserProfile.objects.get(account_id=owner)
    assert (profile.avatar_media_id, profile.display_name) == (None, profile.handle)


def test_media_down_is_a_503_and_nothing_changes(auth_client, media):
    owner = _acct()
    services.ensure_profile(owner)
    media.down = True
    resp = _patch(auth_client, owner, cover_media_id=media.add(owner))
    assert resp.status_code == 503
    assert UserProfile.objects.get(account_id=owner).cover_media_id is None


def test_clearing_or_keeping_an_avatar_does_not_ask_media(auth_client, media):
    owner = _acct()
    profile = services.ensure_profile(owner)
    kept = media.add(owner)
    UserProfile.objects.filter(pk=profile.pk).update(avatar_media_id=kept)
    assert _patch(auth_client, owner, avatar_media_id=kept, bio="hi").status_code == 200
    assert _patch(auth_client, owner, avatar_media_id=None).status_code == 200
    assert media.calls == []
    assert UserProfile.objects.get(account_id=owner).avatar_media_id is None


# ---- page contact -------------------------------------------------------------------


def _create(auth_client, owner, contact):
    return auth_client(owner).post(
        reverse("profiles:page-create"),
        {"handle": f"p{uuid.uuid4().hex[:10]}", "name": "Cafe", "contact": contact},
        format="json",
    )


def test_page_contact_keeps_known_keys_and_drops_blanks(auth_client):
    owner = _acct()
    contact = {
        "website": "https://cafe.example",
        "instagram": "http://instagram.com/cafe",
        "email": "hello@cafe.example",
        "phone": "+20 (2) 123-4567",
        "whatsapp": " ",
    }
    resp = _create(auth_client, owner, contact)
    assert resp.status_code == 201
    expected = {k: v for k, v in contact.items() if k != "whatsapp"}
    assert resp.json()["data"]["contact"] == expected


@pytest.mark.parametrize(
    "contact",
    [
        {"website": "javascript:alert(document.cookie)"},
        {"facebook": "data:text/html,<script>alert(1)</script>"},
        {"website": "ftp://cafe.example"},
        {"x": "//evil.example"},
        {"email": "not an email"},
        {"phone": "call me"},
        {"address": "Cairo"},  # not a contact key
        {"website": "https://cafe.example/" + "a" * 200},  # over the length cap
        {"website": {"nested": "https://cafe.example"}},
        ["https://cafe.example"],
    ],
)
def test_page_contact_refuses_unsafe_or_unknown_values(auth_client, contact):
    owner = _acct()
    assert _create(auth_client, owner, contact).status_code == 400
    assert not Page.objects.filter(owner_account_id=owner).exists()


def test_page_contact_is_checked_on_edit_too(auth_client):
    owner = _acct()
    page = _create(auth_client, owner, {}).json()["data"]
    url = reverse("profiles:page-detail", args=[page["id"]])
    bad = auth_client(owner).patch(url, {"contact": {"website": "javascript:x"}}, format="json")
    assert bad.status_code == 400
    good = auth_client(owner).patch(
        url, {"contact": {"website": "https://cafe.example"}}, format="json"
    )
    assert good.json()["data"]["contact"] == {"website": "https://cafe.example"}


# ---- text length caps ---------------------------------------------------------------


def test_intro_is_capped(auth_client):
    owner = _acct()
    services.ensure_profile(owner)
    assert _patch(auth_client, owner, intro="ن" * 500).status_code == 200
    assert _patch(auth_client, owner, intro="ن" * 501).status_code == 400
    assert UserProfile.objects.get(account_id=owner).intro == "ن" * 500


def test_page_description_is_capped_on_create_and_edit(auth_client):
    owner = _acct()
    page_url = reverse("profiles:page-create")
    too_long = {"handle": "long_page", "name": "Cafe", "description": "a" * 2001}
    assert auth_client(owner).post(page_url, too_long, format="json").status_code == 400
    page = auth_client(owner).post(page_url, {**too_long, "description": "a" * 2000}, format="json")
    assert page.status_code == 201
    detail = reverse("profiles:page-detail", args=[page.json()["data"]["id"]])
    assert (
        auth_client(owner).patch(detail, {"description": "b" * 2001}, format="json").status_code
        == 400
    )
    assert Page.objects.get(handle="long_page").description == "a" * 2000
