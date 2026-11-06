"""Rule E9b in people suggestions (Tara Intelligence WP 4b.14 graph part; owner
decisions 9 and 37): only accounts whose **own** token said adult are suggested;
minor and unknown-age accounts are not, but stay friends and followers as before.
A minor viewer gets no people suggestions (decision 9a). Graph stores the class
only, never a date of birth."""

import uuid

import pytest
from django.urls import reverse

from graph import services
from graph.models import AccountRef

pytestmark = pytest.mark.django_db

ADULT = {"is_minor": False, "age_band": "25-34"}
MINOR = {"is_minor": True, "age_band": "13-17"}


def _acct() -> str:
    return str(uuid.uuid4())


def _befriend(a: str, b: str) -> None:
    request = services.send_friend_request(a, b)
    services.accept_friend_request(b, str(request.id))


def _people(client) -> list[str]:
    resp = client.get(reverse("graph:suggestions-people"))
    assert resp.status_code == 200
    return [r["account_id"] for r in resp.json()["data"]["results"]]


def _call_graph(client_for, account_id: str, claims: dict) -> None:
    """Any authenticated graph request records the caller's own class."""
    assert client_for(account_id, **claims).get(reverse("graph:friend-list")).status_code == 200


@pytest.fixture
def world(client_for):
    me, bridge, grown, kid, unknown = (_acct() for _ in range(5))
    _befriend(me, bridge)
    for other in (grown, kid, unknown):
        _befriend(other, bridge)
    _call_graph(client_for, grown, ADULT)
    _call_graph(client_for, kid, MINOR)
    _call_graph(client_for, unknown, {})  # no age claims: unknown, fails closed
    return me, bridge, grown, kid, unknown


def test_classes_come_from_each_account_own_token(world):
    _me, _bridge, grown, kid, unknown = world
    classes = dict(
        AccountRef.objects.filter(account_id__in=[grown, kid, unknown]).values_list(
            "account_id", "age_class"
        )
    )
    assert {str(k): v for k, v in classes.items()} == {
        grown: "adult",
        kid: "minor",
        unknown: "unknown",
    }
    columns = {f.name for f in AccountRef._meta.get_fields()}
    assert not columns & {"date_of_birth", "birthday", "dob", "age_band"}


def test_adult_viewer_is_suggested_adults_only(client_for, world):
    me, _bridge, grown, _kid, _unknown = world
    assert _people(client_for(me, **ADULT)) == [grown]


def test_followers_fill_is_adults_only_too(client_for):
    me, fan_kid, fan_adult = _acct(), _acct(), _acct()
    services.follow(fan_kid, me)
    services.follow(fan_adult, me)
    _call_graph(client_for, fan_kid, MINOR)
    _call_graph(client_for, fan_adult, ADULT)
    assert _people(client_for(me, **ADULT)) == [fan_adult]


def test_minor_stays_a_friend_and_a_follower(client_for, world):
    _me, bridge, _grown, kid, _unknown = world
    assert kid in services.list_friend_ids(bridge)
    other = _acct()
    services.follow(other, kid)
    assert other in {str(x) for x in services.follower_ids(kid)}


def test_a_class_change_is_followed(client_for, world):
    me, _bridge, grown, kid, _unknown = world
    from django.core.cache import cache

    cache.clear()  # the memo only saves a write
    _call_graph(client_for, kid, ADULT)  # turned 18: the next token says adult
    assert sorted(_people(client_for(me, **ADULT))) == sorted([grown, kid])


def test_minor_viewer_gets_no_people_suggestions(client_for, world):
    _me, _bridge, _grown, kid, _unknown = world
    assert _people(client_for(kid, **MINOR)) == []
