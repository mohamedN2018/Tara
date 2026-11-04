"""The owner's Blocked list can name the people they blocked (fix track A),
while every other lookup keeps hiding them."""

import uuid

import pytest
from django.urls import reverse

from profiles.models import BlockedPair, UserProfile

pytestmark = pytest.mark.django_db


def _profile(handle: str) -> UserProfile:
    return UserProfile.objects.create(
        account_id=uuid.uuid4(), handle=handle, display_name=handle.title()
    )


def test_the_blocker_sees_who_they_blocked_and_nobody_else(auth_client):
    me, blocked, blocker, stranger = (_profile(h) for h in ("me", "pest", "hater", "plain"))
    BlockedPair.objects.create(blocker_id=me.account_id, blocked_id=blocked.account_id)
    BlockedPair.objects.create(blocker_id=blocker.account_id, blocked_id=me.account_id)
    client = auth_client(str(me.account_id))
    ids = [str(p.account_id) for p in (blocked, blocker, stranger)]

    body = client.post(reverse("profiles:blocked-lookup"), {"ids": ids}, format="json").json()[
        "data"
    ]
    assert [(c["account_id"], c["display_name"]) for c in body] == [
        (str(blocked.account_id), "Pest")
    ]

    # The general lookup still hides both directions of the block.
    cards = client.post(reverse("profiles:profile-lookup"), {"ids": ids}, format="json").json()[
        "data"
    ]
    assert {c["account_id"] for c in cards} == {str(stranger.account_id)}


def test_a_deleted_profile_is_not_named(auth_client):
    me, gone = _profile("me2"), _profile("gone")
    BlockedPair.objects.create(blocker_id=me.account_id, blocked_id=gone.account_id)
    UserProfile.objects.filter(pk=gone.pk).update(deleted_at="2026-01-01T00:00:00Z")
    client = auth_client(str(me.account_id))
    body = client.post(
        reverse("profiles:blocked-lookup"), {"ids": [str(gone.account_id)]}, format="json"
    ).json()["data"]
    assert body == []


def test_signed_out_is_refused(api_client):
    assert (
        api_client.post(reverse("profiles:blocked-lookup"), {"ids": []}, format="json").status_code
        == 401
    )
