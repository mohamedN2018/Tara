"""Admin's user console (8.6): the internal profile search by handle or name."""

import time
import uuid

import jwt
import pytest
from django.conf import settings
from django.urls import reverse
from rest_framework.test import APIClient

from profiles.models import UserProfile

pytestmark = pytest.mark.django_db


def _internal() -> APIClient:
    now = int(time.time())
    token = jwt.encode(
        {"iss": "admin", "aud": "profile-internal", "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def _profile(handle: str, name: str = "") -> UserProfile:
    return UserProfile.objects.create(account_id=uuid.uuid4(), handle=handle, display_name=name)


def test_search_needs_an_internal_token():
    assert APIClient().get(reverse("profiles-search"), {"q": "ab"}).status_code == 401


def test_search_by_handle_prefix_or_name_and_handle_only_with_at():
    _profile("layla_one", "Layla One")
    _profile("omar", "ليلى عمر")
    _profile("zed", "Zed")
    resp = _internal().get(reverse("profiles-search"), {"q": "ليلى"})
    assert [p["handle"] for p in resp.json()["data"]] == ["omar"]
    resp = _internal().get(reverse("profiles-search"), {"q": "LAY"})
    assert [p["handle"] for p in resp.json()["data"]] == ["layla_one"]
    # "@" restricts the match to handles, so a name no longer matches.
    resp = _internal().get(reverse("profiles-search"), {"q": "@ze"})
    assert [p["handle"] for p in resp.json()["data"]] == ["zed"]
    resp = _internal().get(reverse("profiles-search"), {"q": "@ليلى"})
    assert resp.json()["data"] == []


def test_search_results_carry_minimal_fields_and_page_by_keyset():
    for i in range(5):
        _profile(f"page_{i}", "Same Name")
    client = _internal()
    first = client.get(reverse("profiles-search"), {"q": "same", "limit": 2}).json()
    assert set(first["data"][0]) == {"account_id", "handle", "display_name"}
    seen = [p["handle"] for p in first["data"]]
    cursor = first["page"]["next_cursor"]
    while cursor:
        page = client.get(
            reverse("profiles-search"), {"q": "same", "limit": 2, "cursor": cursor}
        ).json()
        seen += [p["handle"] for p in page["data"]]
        cursor = page["page"]["next_cursor"]
    assert seen == [f"page_{i}" for i in range(5)]


@pytest.mark.parametrize("q", ["", "a", "x" * 81])
def test_search_rejects_too_short_or_long_queries(q):
    assert _internal().get(reverse("profiles-search"), {"q": q}).status_code == 400


def test_deleted_profiles_are_not_found():
    from django.utils import timezone

    gone = _profile("gone_user", "Gone")
    gone.deleted_at = timezone.now()
    gone.save(update_fields=["deleted_at"])
    assert _internal().get(reverse("profiles-search"), {"q": "gone"}).json()["data"] == []


def test_field_restricts_the_match_to_names_or_handles():
    _profile("layla", "Someone")
    _profile("omar", "Layla Omar")
    by_name = _internal().get(reverse("profiles-search"), {"q": "layla", "field": "name"})
    assert [p["handle"] for p in by_name.json()["data"]] == ["omar"]
    by_handle = _internal().get(reverse("profiles-search"), {"q": "layla", "field": "handle"})
    assert [p["handle"] for p in by_handle.json()["data"]] == ["layla"]


def test_profiles_by_account_returns_names_for_known_accounts_only():
    known = _profile("known", "Known One")
    resp = _internal().post(
        reverse("profiles-by-account"),
        {"account_ids": [str(known.account_id), str(uuid.uuid4())]},
        format="json",
    )
    assert resp.json()["data"] == {
        str(known.account_id): {"handle": "known", "display_name": "Known One"}
    }
    assert APIClient().post(reverse("profiles-by-account"), {}, format="json").status_code == 401
