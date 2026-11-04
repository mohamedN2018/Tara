"""The sign-up form's live handle check (plan 08, track 1D) and names from sign-up."""

import uuid

import pytest
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from profiles.handlers import on_account_registered
from profiles.models import UserProfile, Visibility
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db

URL = reverse("profiles:handle-available")


@pytest.fixture(autouse=True)
def _fresh_throttle():
    cache.clear()  # throttle history lives in the shared locmem cache


def _check(client: APIClient, handle: str, **extra):
    return client.get(URL, {"handle": handle}, **extra)


def _profile(handle: str, **fields) -> UserProfile:
    return UserProfile.objects.create(account_id=uuid.uuid4(), handle=handle, **fields)


def test_a_free_handle_is_available_without_signing_in():
    resp = _check(APIClient(), "Free_Name")
    assert resp.status_code == 200
    assert resp.json()["data"] == {"handle": "free_name", "available": True, "reason": None}


def test_a_taken_handle_is_unavailable_in_any_case():
    _profile("sara_k")
    body = _check(APIClient(), "SARA_K").json()["data"]
    assert body == {"handle": "sara_k", "available": False, "reason": "unavailable"}


@pytest.mark.parametrize("handle", ["ab", "has space", "bad-dash", "x" * 31, ""])
def test_a_malformed_handle_is_invalid(handle):
    body = _check(APIClient(), handle).json()["data"]
    assert body["available"] is False and body["reason"] == "invalid"


@pytest.mark.parametrize(
    "holder",
    [
        {},  # active, public
        {"visibility": Visibility.PRIVATE},  # hidden
        {"deleted_at": timezone.now()},  # deleted or banned: the handle stays held
    ],
)
def test_who_holds_a_handle_is_never_revealed(holder):
    profile = _profile("held_name", **holder)
    resp = _check(APIClient(), "held_name")
    assert resp.json()["data"] == {
        "handle": "held_name",
        "available": False,
        "reason": "unavailable",
    }
    text = resp.content.decode()
    assert str(profile.account_id) not in text and "deleted" not in text and "private" not in text


def test_reserved_words_read_the_same_as_taken_ones():
    assert _check(APIClient(), "admin").json()["data"]["reason"] == "unavailable"


def test_the_check_is_rate_limited_per_address(settings):
    settings.PROFILE_HANDLE_CHECK_RATE = "3/min"
    client = APIClient()
    statuses = [_check(client, f"name_{i}", REMOTE_ADDR="10.0.0.7").status_code for i in range(4)]
    assert statuses == [200, 200, 200, 429]
    # Another address has its own budget.
    assert _check(client, "name_x", REMOTE_ADDR="10.0.0.8").status_code == 200


def test_a_stale_access_token_does_not_break_the_check():
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer not-a-token")
    assert _check(client, "fine_name").status_code == 200


# ---- names from sign-up -------------------------------------------------------


def _registered(**payload) -> UserProfile:
    account_id = str(uuid.uuid4())
    on_account_registered(
        EventEnvelope(
            event_type="account.registered",
            subject_id=account_id,
            producer="identity-service",
            payload=payload,
        )
    )
    return UserProfile.objects.get(account_id=account_id)


def test_the_display_name_is_built_from_the_first_and_last_names():
    profile = _registered(
        email_verified=False,
        language="ar",
        display_name="ignored",
        first_name="ليلى",
        last_name="أحمد",
        handle="laila_a",
    )
    assert profile.display_name == "ليلى أحمد"
    assert profile.handle == "laila_a"


def test_an_event_without_names_still_uses_display_name():
    profile = _registered(
        email_verified=True, language="en", display_name="Google Person", handle=""
    )
    assert profile.display_name == "Google Person"
