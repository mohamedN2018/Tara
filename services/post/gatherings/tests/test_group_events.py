"""Milestone 1.11: events in a group follow the group's visibility."""

from datetime import timedelta

import pytest
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from posts import groups
from posts.models import OutboxEvent
from posts.tests.test_groups import FakeProfile, Group

from gatherings.models import Gathering
from gatherings.tests.conftest import acct

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def profile(monkeypatch):
    fake = FakeProfile()
    monkeypatch.setattr(groups, "_fetch", fake.fetch)
    cache.clear()
    return fake


def _create(client, group_id=None, **data):
    body = {
        "title": "Ride to Sokhna",
        "starts_at": (timezone.now() + timedelta(days=2)).isoformat(),
        "location": "Tahrir square",
        **data,
    }
    if group_id:
        body["group_id"] = group_id
    return client.post(reverse("gatherings:event-list"), body, format="json")


def test_members_create_group_events_with_the_group_audience(client_for, profile):
    group = Group(profile, "private")
    member = group.member()
    resp = _create(client_for(member), group.id, audience="public")
    assert resp.status_code == 201, resp.content
    data = resp.json()["data"]
    assert data["audience"] == "group" and data["group_id"] == group.id
    created = OutboxEvent.objects.get(event_type="gathering.created").payload["payload"]
    assert created["group_id"] == group.id and created["audience"] == "group"
    resp = _create(client_for(acct()), group.id)
    assert resp.status_code == 404  # a private group is hidden from a stranger's write
    public = Group(profile, "public", handle="open")
    resp = _create(client_for(acct()), public.id)
    assert resp.status_code == 403 and resp.json()["error"]["code"] == "not_group_member"


def test_a_group_event_is_seen_as_the_group_content_is(client_for, profile):
    group = Group(profile, "private")
    member, banned = group.member(), group.set(acct(), "member", "banned")
    event_id = _create(client_for(member), group.id).json()["data"]["id"]
    detail = reverse("gatherings:event-detail", args=[event_id])
    assert client_for(group.owner).get(detail).status_code == 200
    assert client_for(acct()).get(detail).status_code == 404
    assert client_for(banned).get(detail).status_code == 404
    listed = client_for(group.owner).get(reverse("gatherings:event-list"), {"group_id": group.id})
    assert [g["id"] for g in listed.json()["data"]] == [event_id]
    stranger_list = client_for(acct()).get(reverse("gatherings:event-list"), {"group_id": group.id})
    assert stranger_list.status_code == 404
    # Upcoming lists: the group's members only.
    upcoming = client_for(group.owner).get(reverse("gatherings:event-list"))
    assert event_id in [g["id"] for g in upcoming.json()["data"]]
    other = client_for(acct()).get(reverse("gatherings:event-list"))
    assert event_id not in [g["id"] for g in other.json()["data"]]


def test_a_public_groups_events_are_open_to_anyone(client_for, profile):
    group = Group(profile, "public")
    event_id = _create(client_for(group.owner), group.id).json()["data"]["id"]
    detail = reverse("gatherings:event-detail", args=[event_id])
    assert client_for(acct()).get(detail).status_code == 200


def test_only_a_group_event_has_the_group_audience(client_for, profile):
    resp = _create(client_for(acct()), audience="group")
    assert resp.status_code == 400
    group = Group(profile)
    event_id = _create(client_for(group.owner), group.id).json()["data"]["id"]
    resp = client_for(group.owner).patch(
        reverse("gatherings:event-detail", args=[event_id]), {"audience": "public"}, format="json"
    )
    assert resp.status_code == 400
    assert Gathering.objects.get(id=event_id).audience == "group"
