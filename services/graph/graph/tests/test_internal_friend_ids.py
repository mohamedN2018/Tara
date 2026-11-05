"""Internal friend ids for identity's birthdays list (plan 08, social shell)."""

import time
import uuid

import jwt
import pytest
from django.conf import settings
from django.urls import reverse
from rest_framework.test import APIClient

from graph import services

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _befriend(a: str, b: str) -> None:
    request = services.send_friend_request(a, b)
    services.accept_friend_request(b, str(request.id))


def _client(audience="graph-internal") -> APIClient:
    now = int(time.time())
    token = jwt.encode(
        {"iss": "identity", "aud": audience, "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def test_lists_accepted_friends_only_and_leaves_out_blocks():
    me, friend, blocked, blocker, pending = (_acct() for _ in range(5))
    for other in (friend, blocked, blocker):
        _befriend(me, other)
    services.send_friend_request(me, pending)
    # Stale edges racing a block must never surface, whichever side blocked.
    services.block(me, blocked)
    services.block(blocker, me)

    resp = _client().get(reverse("internal-friend-ids", args=[me]))
    assert resp.status_code == 200, resp.content
    body = resp.json()["data"]
    assert body["account_id"] == me
    assert body["friends"] == [friend]


def test_needs_an_internal_token_for_graph():
    url = reverse("internal-friend-ids", args=[_acct()])
    assert APIClient().get(url).status_code == 401
    assert _client(audience="post-internal").get(url).status_code == 401
