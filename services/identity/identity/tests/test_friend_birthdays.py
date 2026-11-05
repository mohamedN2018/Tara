"""Friends' birthdays (plan 08, social shell): GET /me/birthdays/."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from identity import account_center
from identity.models import Account

pytestmark = pytest.mark.django_db

PASSWORD = "DevPassw0rd!"
URL = "identity:me-birthdays"


def _auth(client, account):
    resp = client.post(
        reverse("identity:login"),
        {"identifier": account.email, "password": PASSWORD},
        format="json",
    )
    assert resp.status_code == 200, resp.content
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.json()['data']['access_token']}")


def _person(dob: date | None, **fields) -> Account:
    return Account.objects.create_user(
        email=f"b{Account.objects.count()}@tara.local",
        password=PASSWORD,
        status=Account.Status.ACTIVE,
        date_of_birth=dob,
        **fields,
    )


def _born(days_from_today: int, today: date, year: int = 1995) -> date:
    when = today + timedelta(days=days_from_today)
    return (
        when.replace(year=year) if not (when.month == 2 and when.day == 29) else date(1996, 2, 29)
    )


def _friends(monkeypatch, ids):
    calls = []

    def fake(account_id):
        calls.append(account_id)
        return [str(i) for i in ids] if ids is not None else None

    monkeypatch.setattr(account_center, "_friend_ids", fake)
    return calls


def test_lists_friends_sharing_their_birthday_soonest_first(
    api_client, active_account, monkeypatch
):
    today = timezone.now().date()
    born_today = _person(_born(0, today))
    in_three = _person(_born(3, today))
    next_month = _person(_born(20, today))
    only_me = _person(_born(0, today), birthday_visibility="only_me")
    no_dob = _person(None)
    stranger = _person(_born(0, today))  # not a friend: never listed
    left = _person(_born(1, today))
    left.status = Account.Status.DEACTIVATED
    left.save()
    calls = _friends(
        monkeypatch, [born_today.id, in_three.id, next_month.id, only_me.id, no_dob.id, left.id]
    )

    _auth(api_client, active_account)
    resp = api_client.get(reverse(URL))
    assert resp.status_code == 200, resp.content
    body = resp.json()["data"]
    assert calls == [str(active_account.id)]
    assert body["date"] == today.isoformat() and body["days"] == 7
    ids = [r["account_id"] for r in body["results"]]
    assert ids == [str(born_today.id), str(in_three.id)]
    assert str(stranger.id) not in ids
    first = body["results"][0]
    assert first == {
        "account_id": str(born_today.id),
        "month": born_today.date_of_birth.month,
        "day": born_today.date_of_birth.day,
        "days_until": 0,
    }  # never the year
    assert body["results"][1]["days_until"] == 3

    wide = api_client.get(reverse(URL), {"days": 31}).json()["data"]
    assert str(next_month.id) in [r["account_id"] for r in wide["results"]]


def test_local_date_within_a_day_is_honoured_otherwise_utc(api_client, active_account, monkeypatch):
    today = timezone.now().date()
    tomorrow = today + timedelta(days=1)
    friend = _person(_born(1, today))
    _friends(monkeypatch, [friend.id])
    _auth(api_client, active_account)

    body = api_client.get(reverse(URL), {"date": tomorrow.isoformat(), "days": 1}).json()["data"]
    assert body["date"] == tomorrow.isoformat()
    assert [r["days_until"] for r in body["results"]] == [0]

    far = (today + timedelta(days=40)).isoformat()
    assert api_client.get(reverse(URL), {"date": far}).json()["data"]["date"] == today.isoformat()
    assert api_client.get(reverse(URL), {"date": "nope"}).status_code == 400
    assert api_client.get(reverse(URL), {"days": "x"}).status_code == 400


def test_graph_down_is_503_not_an_empty_list(api_client, active_account, monkeypatch):
    _friends(monkeypatch, None)
    _auth(api_client, active_account)
    assert api_client.get(reverse(URL)).status_code == 503


def test_needs_sign_in(api_client):
    assert api_client.get(reverse(URL)).status_code == 401


def test_friend_lookup_fails_closed(settings):
    settings.GRAPH_INTERNAL_URL = "http://127.0.0.1:9"  # nothing listens there
    settings.GRAPH_CALL_TIMEOUT = 0.2
    assert account_center._friend_ids("00000000-0000-0000-0000-000000000001") is None


@pytest.mark.parametrize(
    ("dob", "today", "expected"),
    [
        (date(1990, 3, 10), date(2026, 3, 10), date(2026, 3, 10)),
        (date(1990, 1, 2), date(2026, 12, 30), date(2027, 1, 2)),
        (date(1992, 2, 29), date(2027, 2, 27), date(2027, 2, 28)),
        (date(1992, 2, 29), date(2028, 2, 27), date(2028, 2, 29)),
    ],
)
def test_next_birthday(dob, today, expected):
    assert account_center._next_birthday(dob, today) == expected
