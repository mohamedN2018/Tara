"""Social Graph API + invariants + internal relationship tests."""

import time
import uuid

import jwt
import pytest
from django.conf import settings
from django.urls import reverse

from graph import services
from graph.models import FollowRelation, Friendship

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


# ---- friends ----------------------------------------------------------------


def test_friend_request_accept_makes_friends(client_for):
    a, b = _acct(), _acct()
    create = client_for(a).post(reverse("graph:friend-requests"), {"to_user_id": b}, format="json")
    assert create.status_code == 201
    req_id = create.json()["data"]["id"]

    # Requester cannot accept their own request.
    assert client_for(a).post(reverse("graph:friend-accept", args=[req_id])).status_code == 403

    # Recipient accepts -> they are friends.
    assert client_for(b).post(reverse("graph:friend-accept", args=[req_id])).status_code == 200
    assert services.are_friends(a, b) is True
    assert b in services.list_friend_ids(a)


def test_duplicate_friend_request_conflicts(client_for):
    a, b = _acct(), _acct()
    client_for(a).post(reverse("graph:friend-requests"), {"to_user_id": b}, format="json")
    dup = client_for(a).post(reverse("graph:friend-requests"), {"to_user_id": b}, format="json")
    assert dup.status_code == 409
    # And only one row exists regardless of direction (symmetric, deduped).
    assert Friendship.objects.count() == 1


def test_cannot_friend_self(client_for):
    a = _acct()
    resp = client_for(a).post(reverse("graph:friend-requests"), {"to_user_id": a}, format="json")
    assert resp.status_code == 400


def test_unfriend_is_idempotent(client_for):
    a, b = _acct(), _acct()
    services.send_friend_request(a, b)
    fid = Friendship.objects.get().id
    services.accept_friend_request(b, str(fid))
    assert client_for(a).delete(reverse("graph:friend-delete", args=[b])).status_code == 204
    assert client_for(a).delete(reverse("graph:friend-delete", args=[b])).status_code == 204
    assert services.are_friends(a, b) is False


# ---- follows ----------------------------------------------------------------


def test_follow_is_idempotent_and_unfollow(client_for):
    a, b = _acct(), _acct()
    assert client_for(a).post(reverse("graph:follow", args=[b])).status_code == 204
    assert client_for(a).post(reverse("graph:follow", args=[b])).status_code == 204  # idempotent
    assert FollowRelation.objects.filter(follower_id=a, target_id=b).count() == 1
    assert a in services.follower_ids(b)
    assert client_for(a).delete(reverse("graph:follow", args=[b])).status_code == 204
    assert services.follows(a, b) is False


def test_cannot_follow_self(client_for):
    a = _acct()
    assert client_for(a).post(reverse("graph:follow", args=[a])).status_code == 400


# ---- blocks -----------------------------------------------------------------


def test_block_severs_and_prevents_follow(client_for):
    a, b = _acct(), _acct()
    # A follows B.
    client_for(a).post(reverse("graph:follow", args=[b]))
    assert services.follows(a, b) is True
    # B blocks A -> existing follow severed.
    assert client_for(b).post(reverse("graph:block", args=[a])).status_code == 204
    assert services.follows(a, b) is False
    # A can no longer follow B.
    assert client_for(a).post(reverse("graph:follow", args=[b])).status_code == 403


def test_block_prevents_friend_request(client_for):
    a, b = _acct(), _acct()
    client_for(a).post(reverse("graph:block", args=[b]))
    resp = client_for(b).post(reverse("graph:friend-requests"), {"to_user_id": a}, format="json")
    assert resp.status_code == 403


# ---- internal relationship API ----------------------------------------------


def _internal_token() -> str:
    now = int(time.time())
    return jwt.encode(
        {"iss": "profile", "aud": "graph-internal", "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )


def test_internal_relationship_requires_token_and_reports_flags(client_for):
    from rest_framework.test import APIClient

    a, b = _acct(), _acct()
    services.send_friend_request(a, b)
    services.accept_friend_request(b, str(Friendship.objects.get().id))

    anon = APIClient()
    assert anon.get(reverse("relationship"), {"a": a, "b": b}).status_code == 401

    anon.credentials(HTTP_AUTHORIZATION=f"Bearer {_internal_token()}")
    resp = anon.get(reverse("relationship"), {"a": a, "b": b})
    assert resp.status_code == 200
    assert resp.json()["data"]["are_friends"] is True
