"""Intelligence WP 3.3 (D5): a deactivated or suspended account leaves people
suggestions and fan-out, and comes back when it is active again. The two flags
are independent, and the newest event wins per flag."""

import time
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from django.conf import settings
from django.urls import reverse
from rest_framework.test import APIClient

from graph import handlers, services
from graph.models import AccountRef
from tara_events.envelope import EventEnvelope

from .ages import adult

pytestmark = pytest.mark.django_db

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


def _acct() -> str:
    return str(uuid.uuid4())


def _befriend(a: str, b: str) -> None:
    request = services.send_friend_request(a, b)
    services.accept_friend_request(b, str(request.id))


def _event(kind: str, account_id: str, at: datetime) -> None:
    payload: dict = {"account_id": account_id}
    if kind == "account.suspended":
        payload |= {"until": None, "suspension_id": _acct(), "source": "admin"}
    elif kind == "account.unsuspended":
        payload |= {"suspension_id": _acct(), "expired": False}
    handler = {
        "account.deactivated": handlers.on_account_deactivated,
        "account.reactivated": handlers.on_account_reactivated,
        "account.suspended": handlers.on_account_suspended,
        "account.unsuspended": handlers.on_account_unsuspended,
    }[kind]
    handler(
        EventEnvelope(
            event_type=kind,
            subject_id=account_id,
            producer="identity-service",
            payload=payload,
            occurred_at=at.isoformat(),
        )
    )


def _people(client) -> list[str]:
    resp = client.get(reverse("graph:suggestions-people"))
    assert resp.status_code == 200
    return [r["account_id"] for r in resp.json()["data"]["results"]]


def _fanout(author: str) -> dict:
    now = int(time.time())
    token = jwt.encode(
        {"iss": "feed", "aud": "graph-internal", "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    resp = client.get(reverse("fanout-audience", args=[author]))
    assert resp.status_code == 200
    return resp.json()["data"]


@pytest.fixture
def pymk():
    """``me`` is friends with ``bridge``; ``fof`` (a friend of the bridge) and
    ``fan`` (follows me) are suggested."""
    me, bridge, fof, fan = _acct(), _acct(), _acct(), _acct()
    _befriend(me, bridge)
    _befriend(fof, bridge)
    services.follow(fan, me)
    adult(fof, fan)  # E9b: only adults are suggested (R4)
    return me, fof, fan


@pytest.mark.parametrize(
    ("off", "on"),
    [
        ("account.deactivated", "account.reactivated"),
        ("account.suspended", "account.unsuspended"),
    ],
)
def test_an_inactive_account_leaves_pymk_and_returns(client_for, pymk, off, on):
    me, fof, fan = pymk
    assert set(_people(client_for(me))) == {fof, fan}

    _event(off, fof, T0)
    _event(off, fan, T0)
    assert _people(client_for(me)) == []

    _event(on, fof, T0 + timedelta(minutes=1))
    _event(on, fan, T0 + timedelta(minutes=1))
    assert set(_people(client_for(me))) == {fof, fan}


@pytest.mark.parametrize(
    ("off", "on"),
    [
        ("account.deactivated", "account.reactivated"),
        ("account.suspended", "account.unsuspended"),
    ],
)
def test_an_inactive_account_leaves_fanout_and_returns(off, on):
    author, follower, friend, other = _acct(), _acct(), _acct(), _acct()
    services.follow(follower, author)
    _befriend(author, friend)
    services.follow(other, author)

    _event(off, follower, T0)
    _event(off, friend, T0)
    data = _fanout(author)
    assert data["followers"] == [other]
    assert data["friends"] == []
    assert data["recipients"] == [other]

    _event(on, follower, T0 + timedelta(minutes=1))
    _event(on, friend, T0 + timedelta(minutes=1))
    data = _fanout(author)
    assert data["recipients"] == sorted([follower, friend, other])


def test_an_older_redelivery_does_not_undo_a_newer_state():
    account = _acct()
    _event("account.reactivated", account, T0 + timedelta(minutes=5))
    _event("account.deactivated", account, T0)  # late, older
    assert AccountRef.objects.get(account_id=account).active is True

    _event("account.deactivated", account, T0 + timedelta(minutes=6))
    _event("account.deactivated", account, T0 + timedelta(minutes=6))  # redelivered
    assert AccountRef.objects.get(account_id=account).active is False


def test_both_flags_must_clear_before_the_account_is_active():
    account = _acct()
    _event("account.deactivated", account, T0)
    _event("account.suspended", account, T0 + timedelta(minutes=1))
    _event("account.reactivated", account, T0 + timedelta(minutes=2))
    row = AccountRef.objects.get(account_id=account)
    assert (row.deactivated, row.suspended, row.active) == (False, True, False)

    _event("account.unsuspended", account, T0 + timedelta(minutes=3))
    assert AccountRef.objects.get(account_id=account).active is True


def test_an_inactive_account_keeps_its_relationships():
    # Deactivation is reversible: the edges stay, only the readers skip it.
    author, follower = _acct(), _acct()
    services.follow(follower, author)
    _event("account.deactivated", follower, T0)
    assert services.follower_ids(author) == [follower]


def test_an_unknown_account_counts_as_active():
    assert services.inactive_among([_acct(), _acct()]) == set()


def test_inactive_lookup_is_chunked(monkeypatch):
    monkeypatch.setattr(services, "_INACTIVE_CHUNK", 2)
    ids = [_acct() for _ in range(5)]
    for account in ids[::2]:
        _event("account.suspended", account, T0)
    assert services.inactive_among(ids) == set(ids[::2])
