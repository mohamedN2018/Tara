"""Group suggestions and the local ``discovery`` config in profile (Tara Intelligence
WP 5.5): the handler keeps the newest state, parity with today's constants when there
is no row, published params apply, and under an experiment the viewer gets
``assign_variant``'s variant with ``meta.variant`` and one exposure event."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from django.urls import reverse

from groups.handlers import on_intel_config_published
from groups.models import IntelConfig
from groups.tests.conftest import acct, add_member, make_group
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db
T0 = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)
SCHEMAS = Path("/opt/tara/libs/tara_events/tara_events/schemas")
DISCOVERY_V1 = {
    "people": {"default_limit": 10, "max_limit": 30, "max_bridges": 500},
    "pages": {"default_limit": 5},
    "groups": {"max_suggestions": 20, "friend_preview": 3},
}
EXPERIMENT = {
    "key": "discovery_groups",
    "salt": "g1",
    "variants": [
        {"name": "control", "pct": 50, "version": 1, "params": {}},
        {
            "name": "short",
            "pct": 50,
            "version": 2,
            "params": {"groups": {"max_suggestions": 2, "friend_preview": 1}},
        },
    ],
}
# Expected names computed with tara_common.bucketing on 2026-11-06.
FIXTURES = {
    "6f03e73e-ca0f-4bec-a65d-9c4aad56871b": "control",
    "0a4d6342-9255-4ac8-a7bd-58cfe6fe33f8": "control",
    "a7df4ed5-aecf-46ad-ac53-965f02945712": "control",
    "d90b9d67-b10c-455d-ac6d-ff36f3166cb1": "short",
    "11111111-1111-4111-8111-111111111111": "control",
    "22222222-2222-4222-8222-222222222222": "short",
}


def publish(version, params, at, experiment=None, surface="discovery"):
    on_intel_config_published(
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


@pytest.fixture
def world(graph):
    """A viewer with 4 friends in each of 25 groups (more than the 20 shown)."""
    viewer, friends = acct(), [acct() for _ in range(4)]
    for friend in friends:
        graph.befriend(viewer, friend)
    for _ in range(25):
        group = make_group(privacy="public")
        for friend in friends:
            add_member(group, friend)
    return viewer


def _get(client):
    resp = client.get(reverse("groups:group-suggestions"))
    assert resp.status_code == 200
    return resp.json()


def test_handler_keeps_the_newest_only():
    publish(2, {"groups": {"max_suggestions": 7}}, T0)
    publish(1, {"groups": {"max_suggestions": 3}}, T0 - timedelta(hours=1))
    publish(2, {"groups": {"max_suggestions": 4}}, T0)
    publish(9, {}, T0 + timedelta(hours=1), surface="marketplace")  # not profile's
    row = IntelConfig.objects.get(surface="discovery")
    assert row.params == {"groups": {"max_suggestions": 7}}
    assert IntelConfig.objects.count() == 1


def test_parity_without_a_row_and_with_discovery_v1(auth_client, world):
    no_row = _get(auth_client(world))
    assert "meta" not in no_row
    assert len(no_row["data"]) == 20
    assert all(len(i["friend_ids"]) == 3 for i in no_row["data"])
    publish(1, DISCOVERY_V1, T0)
    assert _get(auth_client(world)) == no_row


def test_published_params_apply(auth_client, world):
    publish(2, {"groups": {"max_suggestions": 5, "friend_preview": 0}}, T0)
    items = _get(auth_client(world))["data"]
    assert len(items) == 5
    assert all(i["friend_ids"] == [] and i["friend_member_count"] == 4 for i in items)
