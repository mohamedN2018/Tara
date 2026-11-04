"""Roadmap 1.6 / plan 08 track 2D: "People you may know" and "Suggested pages"."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from django.urls import reverse

from graph import handlers, services
from graph.models import AccountRef, BlockRelation, PageRef
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _befriend(a: str, b: str) -> None:
    request = services.send_friend_request(a, b)
    services.accept_friend_request(b, str(request.id))


def _people(client) -> list[dict]:
    resp = client.get(reverse("graph:suggestions-people"))
    assert resp.status_code == 200
    return resp.json()["data"]["results"]


def _ids(rows: list[dict]) -> list[str]:
    return [r.get("account_id") or r.get("page_id") for r in rows]


def _profile_updated(account_id: str, **payload) -> None:
    handlers.on_profile_updated(
        EventEnvelope(
            event_type="profile.updated",
            payload={"handle": "h" + account_id[:6], **payload},
            subject_id=account_id,
            producer="profile-service",
        )
    )


def _page_event(page_id: str, *, at: datetime, **payload) -> None:
    body = {
        "handle": "p" + page_id[:6],
        "name": "Page " + page_id[:4],
        "owner": payload.pop("owner", _acct()),
        "category": "Food",
        "location": "",
        "status": "published",
        "avatar_media_id": None,
        "deleted": False,
        **payload,
    }
    handlers.on_page_changed(
        EventEnvelope(
            event_type="page.updated",
            payload={**body, "changed": []},
            subject_id=page_id,
            producer="profile-service",
            occurred_at=at.isoformat(),
        )
    )


# ---- people -------------------------------------------------------------------


def test_friends_of_friends_ranked_by_mutual_count_showing_only_the_count(client_for):
    me, f1, f2 = _acct(), _acct(), _acct()
    two, one = _acct(), _acct()
    _befriend(me, f1)
    _befriend(me, f2)
    for bridge in (f1, f2):
        _befriend(two, bridge)
    _befriend(one, f1)

    rows = _people(client_for(me))
    assert rows == [
        {"account_id": two, "mutual_count": 2, "reason": "mutual_friends"},
        {"account_id": one, "mutual_count": 1, "reason": "mutual_friends"},
    ]


def test_excludes_self_friends_pending_blocks_unsearchable_and_dismissed(client_for):
    me, bridge = _acct(), _acct()
    _befriend(me, bridge)
    keep, friend, asked, asking = _acct(), _acct(), _acct(), _acct()
    i_blocked, blocked_me, hidden, dismissed = _acct(), _acct(), _acct(), _acct()
    for other in (keep, friend, asked, asking, i_blocked, blocked_me, hidden, dismissed):
        _befriend(other, bridge)
    _befriend(me, friend)
    services.send_friend_request(me, asked)
    services.send_friend_request(asking, me)
    # Stale blocks (block() would also cut the bridge edge for the blocked side).
    BlockRelation.objects.create(blocker_id=me, blocked_id=i_blocked)
    BlockRelation.objects.create(blocker_id=blocked_me, blocked_id=me)
    _profile_updated(hidden, searchable=False)
    client = client_for(me)
    resp = client.post(reverse("graph:suggestion-dismiss", args=[dismissed]))
    assert resp.status_code == 204
    # Dismissing twice is fine.
    assert client.post(reverse("graph:suggestion-dismiss", args=[dismissed])).status_code == 204

    assert _ids(_people(client)) == [keep]


def test_searchable_false_comes_from_profile_updated_and_can_be_turned_back_on(client_for):
    me, bridge, other = _acct(), _acct(), _acct()
    _befriend(me, bridge)
    _befriend(other, bridge)
    _profile_updated(other, searchable=False)
    assert AccountRef.objects.get(account_id=other).searchable is False
    assert _people(client_for(me)) == []
    # An event without the flag (today's profile) leaves it as it is.
    _profile_updated(other)
    assert AccountRef.objects.get(account_id=other).searchable is False
    _profile_updated(other, searchable=True)
    assert _ids(_people(client_for(me))) == [other]


def test_dismiss_can_be_undone(client_for):
    me, bridge, other = _acct(), _acct(), _acct()
    _befriend(me, bridge)
    _befriend(other, bridge)
    client = client_for(me)
    url = reverse("graph:suggestion-dismiss", args=[other])
    client.post(url)
    assert _people(client) == []
    assert client.delete(url).status_code == 204
    assert _ids(_people(client)) == [other]
    assert client.post(url, {"target_type": "group"}, format="json").status_code == 400


def test_a_bridge_with_a_hidden_friend_list_is_not_used(client_for):
    me, bridge, other = _acct(), _acct(), _acct()
    _befriend(me, bridge)
    _befriend(other, bridge)
    services.update_relationship_settings(bridge, {"friends_list_visibility": "only_me"})
    assert _people(client_for(me)) == []
    services.update_relationship_settings(bridge, {"friends_list_visibility": "friends"})
    assert _ids(_people(client_for(me))) == [other]


def test_followers_fill_in_after_friends_of_friends(client_for):
    me, bridge, fof, fan, closed_fan, hidden_fan = (_acct() for _ in range(6))
    _befriend(me, bridge)
    _befriend(fof, bridge)
    for f in (fan, closed_fan, hidden_fan):
        services.follow(f, me)
    services.update_relationship_settings(
        closed_fan, {"friend_requests_from": "friends_of_friends"}
    )
    _profile_updated(hidden_fan, searchable=False)
    rows = _people(client_for(me))
    assert rows == [
        {"account_id": fof, "mutual_count": 1, "reason": "mutual_friends"},
        {"account_id": fan, "mutual_count": 0, "reason": "follows_you"},
    ]


def test_suggestions_require_authentication():
    from rest_framework.test import APIClient

    assert APIClient().get(reverse("graph:suggestions-people")).status_code == 401
    assert APIClient().get(reverse("graph:suggestions-pages")).status_code == 401


# ---- pages ----------------------------------------------------------------------


def test_suggested_pages_are_popular_published_pages_not_followed_yet(client_for):
    me, blocker = _acct(), _acct()
    now = datetime.now(UTC)
    popular, quiet, followed, draft, deleted, mine, dismissed, blocked_owner = (
        _acct() for _ in range(8)
    )
    for page in (popular, quiet, followed, dismissed, blocked_owner):
        _page_event(page, at=now)
    _page_event(draft, at=now, status="draft")
    _page_event(deleted, at=now, deleted=True)
    _page_event(mine, at=now, owner=me)
    _page_event(blocked_owner, at=now + timedelta(seconds=1), owner=blocker)
    services.block(blocker, me)
    for _ in range(3):
        services.follow(_acct(), popular, "page")
    services.follow(_acct(), quiet, "page")
    services.follow(me, followed, "page")
    client = client_for(me)
    resp = client.post(
        reverse("graph:suggestion-dismiss", args=[dismissed]), {"target_type": "page"}
    )
    assert resp.status_code == 204

    rows = client.get(reverse("graph:suggestions-pages")).json()["data"]["results"]
    assert _ids(rows) == [popular, quiet]
    assert rows[0]["followers_count"] == 3
    assert rows[0]["handle"] == "p" + popular[:6] and rows[0]["name"]


def test_page_read_model_applies_only_newer_events(client_for):
    page = _acct()
    now = datetime.now(UTC)
    _page_event(page, at=now, name="New name")
    _page_event(page, at=now - timedelta(minutes=1), name="Old name", status="draft")
    row = PageRef.objects.get(page_id=page)
    assert row.name == "New name" and row.status == "published"
    _page_event(page, at=now + timedelta(minutes=1), status="suspended")
    assert PageRef.objects.get(page_id=page).status == "suspended"
    assert client_for(_acct()).get(reverse("graph:suggestions-pages")).json()["data"] == {
        "results": []
    }
