"""Account lifecycle consumers (identity 3C): deactivation hides the profile
from everyone until reactivation; deletion erases it."""

import uuid

import pytest
from django.urls import reverse

from profiles import handlers
from profiles.models import (
    BlockedPair,
    Page,
    PageMember,
    ProfileFieldPrivacy,
    UserLink,
    UserProfile,
)
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _event(event_type: str, account_id: str) -> EventEnvelope:
    return EventEnvelope(
        event_type=event_type,
        subject_id=account_id,
        producer="identity-service",
        payload={"account_id": account_id},
    )


def test_deactivation_hides_the_profile_and_reactivation_restores_it(auth_client):
    owner = UserProfile.objects.create(account_id=_acct(), handle="sleeper", display_name="S")
    viewer = auth_client(_acct())
    by_handle = reverse("profiles:public-profile", args=["sleeper"])
    by_id = reverse("profiles:public-profile-by-id", args=[owner.account_id])
    assert viewer.get(by_handle).status_code == 200

    handlers.on_account_deactivated(_event("account.deactivated", str(owner.account_id)))
    handlers.on_account_deactivated(_event("account.deactivated", str(owner.account_id)))
    assert viewer.get(by_handle).status_code == 404
    assert viewer.get(by_id).status_code == 404
    lookup = viewer.post(
        reverse("profiles:profile-lookup"), {"ids": [str(owner.account_id)]}, format="json"
    )
    assert lookup.status_code == 200
    assert str(owner.account_id) not in str(lookup.json()["data"])

    handlers.on_account_reactivated(_event("account.reactivated", str(owner.account_id)))
    handlers.on_account_reactivated(_event("account.reactivated", str(owner.account_id)))
    body = viewer.get(by_handle).json()["data"]
    assert (body["handle"], body["display_name"]) == ("sleeper", "S")


def test_deletion_erases_the_profile_and_its_details():
    account = _acct()
    other = _acct()
    profile = UserProfile.objects.create(account_id=account, handle="gone", display_name="G")
    ProfileFieldPrivacy.objects.create(profile=profile, field_key="bio", visibility="private")
    UserLink.objects.create(profile=profile, label="x", url="https://example.com")
    page = Page.objects.create(
        name="P", handle="ppp", category="x", created_by=other, owner_account_id=other
    )
    PageMember.objects.create(page=page, account_id=account, role="editor")
    PageMember.objects.create(page=page, account_id=other, role="owner")
    BlockedPair.objects.create(blocker_id=account, blocked_id=other)
    BlockedPair.objects.create(blocker_id=other, blocked_id=account)
    kept = UserProfile.objects.create(account_id=other, handle="stays")

    handlers.on_account_deleted(_event("account.deleted", account))
    handlers.on_account_deleted(_event("account.deleted", account))  # idempotent

    assert not UserProfile.objects.filter(account_id=account).exists()
    assert not ProfileFieldPrivacy.objects.filter(profile_id=profile.id).exists()
    assert not UserLink.objects.filter(profile_id=profile.id).exists()
    assert not PageMember.objects.filter(account_id=account).exists()
    assert not BlockedPair.objects.filter(blocker_id=account).exists()
    assert not BlockedPair.objects.filter(blocked_id=account).exists()
    assert PageMember.objects.filter(account_id=other).exists()
    assert UserProfile.objects.filter(pk=kept.pk).exists()
    # The handle is free again.
    UserProfile.objects.create(account_id=_acct(), handle="gone")
