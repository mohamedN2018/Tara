"""The local ``discovery`` config in graph (Tara Intelligence WP 5.5): the handler
keeps the newest published state, parity with today's constants when there is no
row, and the limits follow the published params."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from django.urls import reverse

from graph import handlers, intel_config, services
from graph.models import IntelConfig, OutboxEvent
from tara_events.envelope import EventEnvelope

from .ages import adult

pytestmark = pytest.mark.django_db
T0 = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)
DISCOVERY_V1 = {
    "people": {
        "default_limit": 10,
        "max_limit": 30,
        "max_bridges": 500,
        "max_candidates": 2000,
        "follower_fill": True,
    },
    "pages": {"default_limit": 5},
    "groups": {"max_suggestions": 20, "friend_preview": 3},
}


def _acct() -> str:
    return str(uuid.uuid4())


def publish(version: int, params: dict, at: datetime, experiment=None, surface="discovery"):
    handlers.on_intel_config_published(
        EventEnvelope(
            event_type="intel.config.published",
            subject_id=surface,
            producer="feed-service",
            payload={
                "surface": surface,
                "version": version,
                "params": params,
                "published_at": at.isoformat(),
                "experiment": experiment,
            },
        )
    )


def _befriend(a: str, b: str) -> None:
    request = services.send_friend_request(a, b)
    services.accept_friend_request(b, str(request.id))
    adult(a, b)


def _people(client, **params):
    resp = client.get(reverse("graph:suggestions-people"), params)
    assert resp.status_code == 200
    return resp.json()


@pytest.fixture
def twelve():
    """``me`` has 12 friends of friends (more than the default limit of 10) and 3 fans."""
    me, bridge = _acct(), _acct()
    _befriend(me, bridge)
    for _ in range(12):
        _befriend(_acct(), bridge)
    for _ in range(3):
        fan = _acct()
        services.follow(fan, me)
        adult(fan)
    return me


def test_handler_keeps_the_newest_and_ignores_older_or_equal():
    publish(2, {"people": {"default_limit": 7}}, T0)
    publish(1, {"people": {"default_limit": 3}}, T0 - timedelta(hours=1))  # older
    publish(2, {"people": {"default_limit": 4}}, T0)  # same state again
    row = IntelConfig.objects.get(surface="discovery")
    assert (row.version, row.params) == (2, {"people": {"default_limit": 7}})
    publish(2, {"people": {"default_limit": 8}}, T0 + timedelta(minutes=1))  # experiment change
    assert IntelConfig.objects.get(surface="discovery").params["people"]["default_limit"] == 8
    publish(3, {}, T0 + timedelta(minutes=2), surface="marketplace")  # not graph's
    assert list(IntelConfig.objects.values_list("surface", flat=True)) == ["discovery"]


def test_malformed_publish_is_dropped():
    publish(0, {}, T0)
    handlers.on_intel_config_published(
        EventEnvelope(
            event_type="intel.config.published",
            subject_id="discovery",
            producer="feed-service",
            payload={"surface": "discovery", "version": 1, "params": {}},
        )
    )
    assert IntelConfig.objects.count() == 0


def test_parity_without_a_row_and_with_discovery_v1(client_for, twelve):
    me = twelve
    assert intel_config.served(me).params == intel_config.resolve(DISCOVERY_V1)
    no_row = _people(client_for(me))
    assert "meta" not in no_row
    assert len(no_row["data"]["results"]) == 10
    wide = _people(client_for(me), limit=30)["data"]["results"]
    assert len(wide) == 15  # 12 friends of friends, then 3 fans
    publish(1, DISCOVERY_V1, T0)
    assert _people(client_for(me)) == no_row
    assert _people(client_for(me), limit=30)["data"]["results"] == wide
    assert OutboxEvent.objects.filter(event_type="intel.experiment.exposed").count() == 0


def test_published_params_change_the_limits(client_for, twelve):
    me = twelve
    publish(2, {"people": {"default_limit": 4, "max_limit": 6, "follower_fill": False}}, T0)
    assert len(_people(client_for(me))["data"]["results"]) == 4
    capped = _people(client_for(me), limit=30)["data"]["results"]
    assert len(capped) == 6
    assert all(r["reason"] == "mutual_friends" for r in capped)


def test_follower_fill_off_drops_the_fans(client_for, twelve):
    me = twelve
    publish(2, {"people": {"follower_fill": False}}, T0)
    rows = _people(client_for(me), limit=30)["data"]["results"]
    assert len(rows) == 12
    assert {r["reason"] for r in rows} == {"mutual_friends"}


def test_out_of_range_values_fall_back_to_the_defaults(client_for, twelve):
    me = twelve
    publish(2, {"people": {"default_limit": 10_000, "max_limit": "lots", "follower_fill": 1}}, T0)
    assert intel_config.served(me).params == intel_config.resolve()
    assert len(_people(client_for(me))["data"]["results"]) == 10


def test_page_limits_follow_the_config(client_for):
    me = _acct()
    for _ in range(4):
        handlers.on_page_changed(
            EventEnvelope(
                event_type="page.updated",
                payload={
                    "handle": "p" + _acct()[:6],
                    "name": "Page",
                    "owner": _acct(),
                    "category": "Food",
                    "location": "",
                    "status": "published",
                    "avatar_media_id": None,
                    "deleted": False,
                },
                subject_id=_acct(),
                producer="profile-service",
                occurred_at=T0.isoformat(),
            )
        )
    resp = client_for(me).get(reverse("graph:suggestions-pages")).json()
    assert len(resp["data"]["results"]) == 4
    publish(2, {"pages": {"default_limit": 2}}, T0)
    resp = client_for(me).get(reverse("graph:suggestions-pages")).json()
    assert len(resp["data"]["results"]) == 2
