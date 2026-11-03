"""Handles (never from the email, never a route, always found), the internal
API under load, and bounded profile lists."""

import time
import uuid
from unittest import mock

import jwt
import pytest
from django.conf import settings
from django.core.cache import cache
from django.db.models.query import QuerySet
from django.urls import reverse
from rest_framework.test import APIClient

from profiles import services
from profiles.handlers import on_account_registered
from profiles.models import Page, UserProfile
from tara_common.exceptions import Conflict
from tara_common.throttling import ReadThrottle, WriteThrottle
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _registered(**payload) -> UserProfile:
    account_id = _acct()
    on_account_registered(
        EventEnvelope(
            event_type="account.registered",
            subject_id=account_id,
            producer="identity-service",
            payload=payload,
        )
    )
    return UserProfile.objects.get(account_id=account_id)


# ---- handles ------------------------------------------------------------------------


def test_a_google_signup_handle_does_not_reveal_the_email():
    """Google sign-up sends no handle; the email's local part used to become it."""
    profile = _registered(email="john.secret1984@gmail.com", display_name="John Smith", handle="")
    assert profile.handle == "johnsmith"
    assert "secret" not in profile.handle and "1984" not in profile.handle


def test_a_name_in_arabic_gets_a_generic_handle():
    first = _registered(email="nour.private@example.com", display_name="نور", handle="")
    second = _registered(email="sara.private@example.com", display_name="سارة", handle="")
    assert first.handle == "user"
    assert second.handle.startswith("user") and second.handle[4:].isdigit()
    assert "private" not in first.handle + second.handle


@pytest.mark.parametrize("route", sorted(services.RESERVED_HANDLES))
def test_a_reserved_handle_gets_digits(route):
    profile = _registered(display_name="X", handle=route)
    assert profile.handle not in services.RESERVED_HANDLES
    assert profile.handle.startswith(route if len(route) >= 3 else "user")


def test_a_profile_named_like_a_route_is_still_reachable(auth_client):
    """``users/lookup/`` is the batch endpoint, so @lookup could never be opened."""
    profile = _registered(display_name="Look Up", handle="lookup")
    url = reverse("profiles:public-profile", args=[profile.handle])
    assert auth_client(_acct()).get(url).json()["data"]["account_id"] == str(profile.account_id)


def test_handle_generation_always_ends(monkeypatch):
    """Every short suffix taken (thousands of Arabic names share ``user``)."""
    calls = []

    def taken(handle):
        calls.append(handle)
        assert len(calls) < 20, "generate_handle does not stop"
        return True

    monkeypatch.setattr(services, "_handle_taken", taken)
    handle = services.generate_handle("")
    assert handle.startswith("user") and len(handle) <= 30
    assert [len(c) for c in calls] == [4, 8, 8, 8, 12, 12, 12]


def test_a_one_letter_name_is_padded_to_a_valid_handle():
    assert services.generate_handle("A") == "user"


# ---- internal API ---------------------------------------------------------------


def _internal() -> APIClient:
    now = int(time.time())
    token = jwt.encode(
        {"iss": "post", "aud": "profile-internal", "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def test_mentions_resolve_case_insensitively():
    profile = _registered(display_name="Target", handle="target_1")
    resp = _internal().post(
        reverse("profiles-by-handle"), {"handles": ["Target_1", "nobody"]}, format="json"
    )
    assert resp.json()["data"] == {"target_1": str(profile.account_id)}


@pytest.mark.parametrize("handles", [5, "abc", [{"x": 1}]])
def test_a_malformed_handle_list_is_a_400(handles):
    resp = _internal().post(reverse("profiles-by-handle"), {"handles": handles}, format="json")
    assert resp.status_code == 400


def test_the_internal_api_is_not_rate_limited_per_ip(monkeypatch):
    """Every post pod resolving mentions shares one IP: a per-IP limit would drop mentions."""
    cache.clear()
    monkeypatch.setitem(WriteThrottle.THROTTLE_RATES, "tara_write", "1/min")
    monkeypatch.setitem(ReadThrottle.THROTTLE_RATES, "tara_read", "1/min")
    profile = _registered(display_name="Target", handle="target_2")
    client = _internal()
    for _ in range(3):
        resp = client.post(reverse("profiles-by-handle"), {"handles": ["x"]}, format="json")
        assert resp.status_code == 200
        snapshot = client.get(reverse("profile-snapshot", args=[profile.account_id]))
        assert snapshot.status_code == 200


# ---- own lists and pages ---------------------------------------------------------------


@pytest.mark.parametrize("name", ["profiles:links", "profiles:education", "profiles:work"])
def test_own_lists_can_be_read(auth_client, name):
    """These used to 500: the paginator ordered by a created_at they do not have."""
    owner = _acct()
    services.ensure_profile(owner)
    resp = auth_client(owner).get(reverse(name))
    assert resp.status_code == 200
    assert resp.json()["data"] == []


@pytest.mark.parametrize(
    ("name", "item"),
    [
        ("profiles:links", {"label": "site", "url": "https://example.com"}),
        ("profiles:education", {"school": "Cairo University"}),
        ("profiles:work", {"company": "QTech"}),
    ],
)
def test_profile_lists_are_capped(auth_client, name, item):
    owner = _acct()
    services.ensure_profile(owner)
    client = auth_client(owner)
    for _ in range(20):
        assert client.post(reverse(name), item, format="json").status_code == 201
    assert client.post(reverse(name), item, format="json").status_code == 400
    assert len(client.get(reverse(name)).json()["data"]) == 20


def test_a_page_handle_taken_concurrently_is_a_conflict_not_a_500():
    owner = _acct()
    Page.objects.create(owner_account_id=owner, handle="dup", name="First", created_by=owner)
    with mock.patch.object(QuerySet, "exists", return_value=False):  # the check raced
        with pytest.raises(Conflict):
            services.create_page(owner, {"handle": "dup", "name": "Second"})
    assert Page.objects.filter(handle="dup").count() == 1
