"""Tara Intelligence WP 3.3 (rule E11): feed and graph backfill the standing account
restrictions from ``/internal/v1/intel/export/restrictions/``: every user case
decided ``restrict`` or ``shadow`` that no appeal overturned, behind an internal
token, ids and the action only."""

import time
import uuid

import jwt
import pytest
from django.conf import settings
from django.urls import reverse
from rest_framework.test import APIClient

from moderation import services
from moderation.models import ModerationCase

pytestmark = pytest.mark.django_db

URL = "/internal/v1/intel/export/restrictions/"


def _acct() -> str:
    return str(uuid.uuid4())


def _decided(target_type: str, target_id: str, action: str) -> ModerationCase:
    case = services.ingest_report(
        reporter_id=_acct(), target_type=target_type, target_id=target_id, owner_id=target_id
    )
    services.take_action(str(case.id), _acct(), action)
    return case


def _overturn(case: ModerationCase) -> None:
    appeal = services.file_appeal(str(case.id), str(case.owner_id), "please")
    services.resolve_appeal(str(appeal.id), _acct(), "overturned")


def _client(audience="moderation-internal") -> APIClient:
    now = int(time.time())
    token = jwt.encode(
        {"iss": "feed", "aud": audience, "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def _all() -> list[dict]:
    client, out, after = _client(), [], None
    while True:
        params = {"limit": 1, **({"after": after} if after else {})}
        resp = client.get(URL, params)
        assert resp.status_code == 200
        data = resp.json()["data"]
        out += [i["payload"] for i in data["items"]]
        after = data["next"]
        if after is None:
            return out


def test_the_route_is_mounted():
    assert reverse("intel-export-restrictions") == URL


def test_standing_user_restrictions_only():
    restricted, shadowed, overturned, warned = _acct(), _acct(), _acct(), _acct()
    r = _decided("user", restricted, "restrict")
    s = _decided("user", shadowed, "shadow")
    _overturn(_decided("user", overturned, "restrict"))
    _decided("user", warned, "warn")
    _decided("user", _acct(), "dismiss")
    _decided("page", _acct(), "restrict")  # pages: nothing enforces it today
    _decided("post", _acct(), "remove")

    items = sorted(_all(), key=lambda p: p["case_id"])

    assert items == sorted(
        [
            {"account_id": restricted, "action": "restrict", "case_id": str(r.id)},
            {"account_id": shadowed, "action": "shadow", "case_id": str(s.id)},
        ],
        key=lambda p: p["case_id"],
    )


def test_one_overturned_case_leaves_the_other_standing():
    user = _acct()
    a = _decided("user", user, "restrict")
    b = _decided("user", user, "shadow")
    _overturn(a)
    assert _all() == [{"account_id": user, "action": "shadow", "case_id": str(b.id)}]
    _overturn(b)
    assert _all() == []


def test_no_query_per_case(django_assert_max_num_queries):
    for _ in range(4):
        _decided("user", _acct(), "restrict")
    with django_assert_max_num_queries(3):
        resp = _client().get(URL, {"limit": 50})
    assert len(resp.json()["data"]["items"]) == 4


@pytest.mark.parametrize("audience", ["post-internal", "identity-internal"])
def test_a_token_for_another_audience_is_refused(audience):
    assert _client(audience).get(URL).status_code == 401


def test_no_token_is_refused():
    assert APIClient().get(URL).status_code == 401
