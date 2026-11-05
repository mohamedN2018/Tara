"""Tara Intelligence WP 3.2 / 3.3: feed and graph backfill account lifecycle from
``/internal/v1/intel/export/accounts/``: only the accounts that are not active,
with deactivation and suspension kept apart, behind an internal token."""

import time
import uuid

import jwt
import pytest
from django.conf import settings
from django.urls import reverse
from rest_framework.test import APIClient

from identity import account_admin
from identity.models import Account

pytestmark = pytest.mark.django_db

URL = "/internal/v1/intel/export/accounts/"


def _account(status=Account.Status.ACTIVE) -> Account:
    return Account.objects.create_user(
        email=f"{uuid.uuid4().hex[:10]}@example.com",
        password="Str0ng-Pass-987!",
        email_verified=True,
        status=status,
    )


def _client(audience="identity-internal") -> APIClient:
    now = int(time.time())
    token = jwt.encode(
        {"iss": "feed", "aud": audience, "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def _all() -> dict[str, dict]:
    client, out, after = _client(), {}, None
    while True:
        params = {"limit": 1, **({"after": after} if after else {})}
        resp = client.get(URL, params)
        assert resp.status_code == 200
        data = resp.json()["data"]
        out.update({i["id"]: i["payload"] for i in data["items"]})
        after = data["next"]
        if after is None:
            return out


def _suspend(account: Account) -> None:
    account_admin.suspend(
        account.id,
        actor_id=uuid.uuid4(),
        reason="staff note",
        until=None,
        idempotency_key=f"intel-{uuid.uuid4().hex}",
    )


def test_the_route_is_mounted():
    assert reverse("intel-export-accounts") == URL


def test_only_inactive_accounts_are_listed_with_their_flags():
    active = _account()
    pending = _account(Account.Status.PENDING)
    deactivated = _account(Account.Status.DEACTIVATED)
    suspended = _account()
    _suspend(suspended)
    both = _account(Account.Status.DEACTIVATED)
    _suspend(both)  # lifting it goes back to deactivated
    deleted = _account(Account.Status.DELETED)

    items = _all()

    assert set(items) == {str(deactivated.id), str(suspended.id), str(both.id)}
    assert items[str(deactivated.id)] == {
        "account_id": str(deactivated.id),
        "deactivated": True,
        "suspended": False,
    }
    assert items[str(suspended.id)]["deactivated"] is False
    assert items[str(suspended.id)]["suspended"] is True
    assert items[str(both.id)]["deactivated"] is True
    assert items[str(both.id)]["suspended"] is True
    for account in (active, pending, deleted):
        assert str(account.id) not in items


def test_ids_and_flags_only():
    _account(Account.Status.DEACTIVATED)
    (payload,) = _all().values()
    assert set(payload) == {"account_id", "deactivated", "suspended"}


def test_no_query_per_account(django_assert_max_num_queries):
    for _ in range(4):
        _suspend(_account())
    with django_assert_max_num_queries(4):
        resp = _client().get(URL, {"limit": 50})
    assert len(resp.json()["data"]["items"]) == 4


@pytest.mark.parametrize("audience", ["post-internal", "identity.roles"])
def test_a_token_for_another_audience_is_refused(audience):
    assert _client(audience).get(URL).status_code == 401


def test_no_token_is_refused():
    assert APIClient().get(URL).status_code == 401
