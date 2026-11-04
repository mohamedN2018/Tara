"""Roadmap 1.6 (graph): relationship privacy settings, counts and the mutual
count, enforced on every list graph exposes."""

import time
import uuid

import jwt
import pytest
from django.conf import settings
from django.urls import reverse
from rest_framework.test import APIClient

from graph import services
from graph.models import RelationshipSettings

pytestmark = pytest.mark.django_db

ALL_LISTS = [
    "graph:social-friends",
    "graph:social-followers",
    "graph:social-following",
    "graph:social-mutual",
    "graph:social-counts",
]


def _acct() -> str:
    return str(uuid.uuid4())


def _befriend(a: str, b: str) -> None:
    request = services.send_friend_request(a, b)
    services.accept_friend_request(b, str(request.id))


def _set(owner: str, **fields) -> None:
    services.update_relationship_settings(owner, fields)


def _status(client, name: str, owner: str) -> int:
    return client.get(reverse(name, args=[owner])).status_code


def _batch(viewer: str, users: list[str]) -> dict:
    now = int(time.time())
    token = jwt.encode(
        {"iss": "search", "aud": "graph-internal", "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    resp = client.post(
        reverse("relationship-batch"), {"viewer_id": viewer, "users": users}, format="json"
    )
    assert resp.status_code == 200
    return resp.json()["data"]["results"]


# ---- acceptance: only_me -> 404 ---------------------------------------------


def test_only_me_friends_list_and_mutual_return_404_to_everyone_else(client_for):
    owner, friend, stranger, shared = _acct(), _acct(), _acct(), _acct()
    _befriend(owner, friend)
    _befriend(owner, shared)
    _befriend(stranger, shared)
    _set(owner, friends_list_visibility="only_me")

    for viewer in (friend, stranger):
        client = client_for(viewer)
        assert _status(client, "graph:social-friends", owner) == 404
        assert _status(client, "graph:social-mutual", owner) == 404
        # Followers are guarded by their own setting, still public.
        assert _status(client, "graph:social-followers", owner) == 200
    owner_client = client_for(owner)
    assert _status(owner_client, "graph:social-friends", owner) == 200
    friends = owner_client.get(reverse("graph:social-friends", args=[owner])).json()["data"]
    assert sorted(friends["friends"]) == sorted([friend, shared])


def test_blocked_viewer_gets_404_on_every_list_whatever_the_settings(client_for):
    owner, viewer = _acct(), _acct()
    services.block(owner, viewer)
    for name in ALL_LISTS:
        assert _status(client_for(viewer), name, owner) == 404, name
        assert _status(client_for(owner), name, viewer) == 404, name


def test_friends_level_shows_lists_to_friends_only(client_for):
    owner, friend, stranger = _acct(), _acct(), _acct()
    _befriend(owner, friend)
    _set(owner, friends_list_visibility="friends", follow_lists_visibility="friends")
    for name in ("graph:social-friends", "graph:social-followers", "graph:social-following"):
        assert _status(client_for(friend), name, owner) == 200, name
        assert _status(client_for(stranger), name, owner) == 404, name


def test_follow_lists_setting_hides_followers_and_following(client_for):
    owner, fan, idol, viewer = _acct(), _acct(), _acct(), _acct()
    services.follow(fan, owner)
    services.follow(owner, idol)
    client = client_for(viewer)
    assert client.get(reverse("graph:social-followers", args=[owner])).json()["data"] == {
        "followers": [fan]
    }
    following = client.get(reverse("graph:social-following", args=[owner])).json()["data"]
    assert following == {"following": [{"target_id": idol, "target_type": "user"}]}

    _set(owner, follow_lists_visibility="only_me")
    assert _status(client, "graph:social-followers", owner) == 404
    assert _status(client, "graph:social-following", owner) == 404
    assert _status(client, "graph:social-friends", owner) == 200
    assert _status(client_for(owner), "graph:social-following", owner) == 200


# ---- counts ------------------------------------------------------------------


def test_counts_follow_the_lists_and_counts_visibility(client_for):
    owner, viewer, shared, fan, idol, blocked = (_acct() for _ in range(6))
    _befriend(owner, shared)
    _befriend(viewer, shared)
    _befriend(owner, blocked)
    services.follow(fan, owner)
    services.follow(owner, idol)
    services.follow(owner, str(uuid.uuid4()), "page")
    # An account blocked by the viewer is never counted for the viewer.
    services.block(viewer, blocked)

    data = client_for(viewer).get(reverse("graph:social-counts", args=[owner])).json()["data"]
    assert data == {
        "friends_count": 1,
        "followers_count": 1,
        "following_count": 2,
        "mutual_count": 1,
    }
    own = client_for(owner).get(reverse("graph:social-counts", args=[owner])).json()["data"]
    assert own["friends_count"] == 2 and own["mutual_count"] is None

    _set(owner, friends_list_visibility="only_me")
    data = client_for(viewer).get(reverse("graph:social-counts", args=[owner])).json()["data"]
    assert data["friends_count"] == 1 and data["mutual_count"] is None

    _set(owner, counts_visibility="only_me")
    assert _status(client_for(viewer), "graph:social-counts", owner) == 404
    assert _status(client_for(owner), "graph:social-counts", owner) == 200


def test_mutual_count_in_the_batch_is_hidden_with_the_friend_list():
    me, target, shared, friend_of_target = _acct(), _acct(), _acct(), _acct()
    _befriend(me, shared)
    _befriend(target, shared)
    assert _batch(me, [target])[target]["mutual_count"] == 1

    _set(target, friends_list_visibility="only_me")
    assert _batch(me, [target])[target]["mutual_count"] is None

    _set(target, friends_list_visibility="friends")
    assert _batch(me, [target])[target]["mutual_count"] is None
    _befriend(friend_of_target, target)
    _befriend(friend_of_target, shared)
    assert _batch(friend_of_target, [target])[target]["mutual_count"] == 1


# ---- settings endpoint and friend requests ------------------------------------


def test_settings_are_owner_only_with_defaults_and_validation(client_for):
    me = _acct()
    client = client_for(me)
    url = reverse("graph:social-settings")
    assert client.get(url).json()["data"] == {
        "friends_list_visibility": "public",
        "follow_lists_visibility": "public",
        "counts_visibility": "public",
        "friend_requests_from": "everyone",
    }
    resp = client.patch(url, {"friends_list_visibility": "only_me"}, format="json")
    assert resp.status_code == 200
    assert resp.json()["data"]["friends_list_visibility"] == "only_me"
    assert RelationshipSettings.objects.get(account_id=me).follow_lists_visibility == "public"
    bad = client.patch(url, {"counts_visibility": "everyone"}, format="json")
    assert bad.status_code == 400
    assert APIClient().get(url).status_code == 401


def test_friend_requests_from_friends_of_friends(client_for):
    target, stranger, fof, shared = _acct(), _acct(), _acct(), _acct()
    _befriend(target, shared)
    _befriend(fof, shared)
    _set(target, friend_requests_from="friends_of_friends")
    url = reverse("graph:friend-requests")

    refused = client_for(stranger).post(url, {"to_user_id": target}, format="json")
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "friend_requests_restricted"
    assert client_for(fof).post(url, {"to_user_id": target}, format="json").status_code == 201
