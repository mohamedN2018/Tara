"""What search learns from profile (roadmap 1.15): the city only while its field
privacy is public, every page edit, and the backfill export."""

import time
import uuid

import jwt
import pytest
from django.conf import settings
from django.urls import reverse

from profiles import services
from profiles.models import OutboxEvent, Page

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _last(event_type: str) -> dict:
    row = OutboxEvent.objects.filter(event_type=event_type).order_by("-created_at").first()
    assert row is not None, event_type
    return row.payload["payload"]


def test_profile_updated_carries_the_city_only_while_it_is_public(auth_client):
    owner = _acct()
    services.ensure_profile(owner)
    client = auth_client(owner)
    client.patch(reverse("profiles:me"), {"city": "الإسكندرية"}, format="json")
    assert _last("profile.updated")["city"] == "الإسكندرية"

    before = OutboxEvent.objects.filter(event_type="profile.updated").count()
    resp = client.put(
        reverse("profiles:field-privacy"),
        {"items": [{"field_key": "city", "visibility": "friends_only"}]},
        format="json",
    )
    assert resp.status_code == 200, resp.content
    # Making the city private is itself announced, so search drops it.
    assert OutboxEvent.objects.filter(event_type="profile.updated").count() == before + 1
    assert _last("profile.updated")["city"] is None

    client.patch(reverse("profiles:me"), {"bio": "hello"}, format="json")
    assert _last("profile.updated")["city"] is None


def test_page_edits_emit_page_updated_with_the_owner(auth_client):
    owner = _acct()
    client = auth_client(owner)
    page_id = client.post(
        reverse("profiles:page-create"),
        {"handle": "nile_books", "name": "Nile Books", "category": "Books"},
        format="json",
    ).json()["data"]["id"]
    created = _last("page.created")
    assert created["category"] == "Books" and created["status"] == "published"
    assert created["owner"] == owner

    resp = client.patch(
        reverse("profiles:page-detail", args=[page_id]), {"status": "draft"}, format="json"
    )
    assert resp.status_code == 200, resp.content
    updated = _last("page.updated")
    assert updated["status"] == "draft" and updated["owner"] == owner
    assert updated["changed"] == ["status"]


def test_page_updated_can_be_switched_off(auth_client, settings):
    settings.PROFILE_EMIT_PAGE_UPDATED = False
    owner = _acct()
    page = services.create_page(owner, {"handle": "quiet", "name": "Quiet"})
    services.update_page(page, owner, {"name": "Quieter"})
    assert not OutboxEvent.objects.filter(event_type="page.updated").exists()


def _internal(api_client, audience="profile-internal"):
    now = int(time.time())
    token = jwt.encode(
        {"iss": "search", "aud": audience, "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return api_client


def test_export_lists_only_searchable_profiles_and_pages_by_keyset(api_client):
    public = [_acct() for _ in range(3)]
    for a in public:
        services.ensure_profile(a)
    hidden = _acct()
    services.update_profile(services.ensure_profile(hidden), {"visibility": "private"})
    owner = _acct()
    services.create_page(owner, {"handle": "open_page", "name": "Open"})
    draft = services.create_page(owner, {"handle": "draft_page", "name": "Draft"})
    Page.objects.filter(id=draft.id).update(status=Page.Status.DRAFT)

    client = _internal(api_client)
    seen, after = [], ""
    while True:
        body = client.get(reverse("search-export-people"), {"after": after, "limit": 2}).json()[
            "data"
        ]
        seen += [item["id"] for item in body["items"]]
        assert body["as_of"]
        after = body["next"]
        if not after:
            break
    assert sorted(seen) == sorted(public)
    item = client.get(reverse("search-export-people")).json()["data"]["items"][0]
    assert set(item["payload"]) >= {"handle", "display_name", "visibility", "city"}

    pages = client.get(reverse("search-export-pages")).json()["data"]["items"]
    assert [p["payload"]["handle"] for p in pages] == ["open_page"]


def test_export_requires_an_internal_token(api_client):
    assert api_client.get(reverse("search-export-people")).status_code == 401
    wrong = _internal(api_client, audience="graph-internal")
    assert wrong.get(reverse("search-export-pages")).status_code == 401


# ---- searchable: the discoverability flag (1.6, spec B) -------------------------------


def test_searchable_defaults_to_true_and_is_carried_in_profile_updated(auth_client):
    me = _acct()
    profile = services.ensure_profile(me)
    assert profile.searchable is True
    assert _last("profile.updated")["searchable"] is True
    client = auth_client(me)
    assert client.get(reverse("profiles:me")).json()["data"]["searchable"] is True

    resp = client.patch(reverse("profiles:me"), {"searchable": False}, format="json")
    assert resp.status_code == 200, resp.content
    assert resp.json()["data"]["searchable"] is False
    event = _last("profile.updated")
    assert event["searchable"] is False
    assert "searchable" in event["changed"]

    client.patch(reverse("profiles:me"), {"searchable": True}, format="json")
    assert _last("profile.updated")["searchable"] is True


def test_searchable_must_be_a_boolean(auth_client):
    me = _acct()
    services.ensure_profile(me)
    resp = auth_client(me).patch(reverse("profiles:me"), {"searchable": "maybe"}, format="json")
    assert resp.status_code == 400


def test_export_leaves_out_unsearchable_people(api_client):
    shown, hidden = _acct(), _acct()
    services.ensure_profile(shown)
    services.update_profile(services.ensure_profile(hidden), {"searchable": False})
    items = _internal(api_client).get(reverse("search-export-people")).json()["data"]["items"]
    ids = [i["id"] for i in items]
    assert shown in ids and hidden not in ids
