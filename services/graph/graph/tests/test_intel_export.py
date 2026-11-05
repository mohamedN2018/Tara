"""Tara Intelligence WP 3.2: feed's edge backfill pages through these exports."""

import time
import uuid

import jwt
import pytest
from django.conf import settings
from django.urls import reverse
from rest_framework.test import APIClient

from graph.models import BlockRelation, FollowRelation, Friendship

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _client(audience="graph-internal") -> APIClient:
    now = int(time.time())
    token = jwt.encode(
        {"iss": "feed", "aud": audience, "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def _all(name: str) -> list[dict]:
    client, out, after = _client(), [], None
    while True:
        params = {"limit": 1, **({"after": after} if after else {})}
        data = client.get(reverse(name), params).json()["data"]
        out += [i["payload"] for i in data["items"]]
        after = data["next"]
        if after is None:
            return out


def _pair(a, b):
    return (a, b) if a < b else (b, a)


@pytest.mark.parametrize(
    "name", ["intel-export-friendships", "intel-export-follows", "intel-export-blocks"]
)
def test_exports_need_a_graph_internal_token(name):
    assert APIClient().get(reverse(name)).status_code == 401
    assert _client("post-internal").get(reverse(name)).status_code == 401


def test_friendships_export_accepted_ones_only():
    a, b, c = _acct(), _acct(), _acct()
    low, high = _pair(a, b)
    Friendship.objects.create(
        account_low_id=low, account_high_id=high, status="accepted", requested_by=a
    )
    low2, high2 = _pair(a, c)
    Friendship.objects.create(
        account_low_id=low2, account_high_id=high2, status="pending", requested_by=a
    )
    rows = _all("intel-export-friendships")
    assert [(r["a"], r["b"]) for r in rows] == [(low, high)]
    assert rows[0]["accepted_at"]


def test_follows_and_blocks_export_every_row_with_its_kind():
    a, b, page = _acct(), _acct(), _acct()
    FollowRelation.objects.create(follower_id=a, target_id=b)
    FollowRelation.objects.create(follower_id=a, target_id=page, target_type="page")
    BlockRelation.objects.create(blocker_id=b, blocked_id=a)
    follows = {(r["follower"], r["target"], r["target_type"]) for r in _all("intel-export-follows")}
    assert follows == {(a, b, "user"), (a, page, "page")}
    blocks = _all("intel-export-blocks")
    assert [(r["blocker_id"], r["blocked_id"]) for r in blocks] == [(b, a)]
