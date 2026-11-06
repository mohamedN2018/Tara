"""Experiments on group suggestions (Tara Intelligence WP 5.5): profile buckets the
viewer with ``tara_common.bucketing.assign_variant``, as feed does, so an account
gets the same variant everywhere."""

import json
from pathlib import Path

import pytest
from profiles.models import OutboxEvent

from groups import intel_config
from groups.models import IntelExposureSeen
from groups.tests.test_intel_config import EXPERIMENT, FIXTURES, T0, _get, publish, world  # noqa: F401
from tara_common.bucketing import assign_variant

pytestmark = pytest.mark.django_db
SCHEMAS = Path("/opt/tara/libs/tara_events/tara_events/schemas")


def test_variant_assignment_meta_and_one_exposure(auth_client, world):  # noqa: F811
    publish(3, {}, T0, experiment=EXPERIMENT)
    variant = assign_variant(world, EXPERIMENT)
    assert intel_config.served(world).variant == variant
    for _ in range(2):
        body = _get(auth_client(world))
        assert body["meta"] == {"variant": variant}
        assert len(body["data"]) == (2 if variant == "short" else 20)
    rows = [
        r.payload["payload"]
        for r in OutboxEvent.objects.filter(event_type="intel.experiment.exposed")
    ]
    assert len(rows) == 1
    assert rows[0]["variant"] == variant and rows[0]["surface"] == "discovery"
    assert IntelExposureSeen.objects.count() == 1
    if SCHEMAS.exists():
        import jsonschema

        schema = json.loads((SCHEMAS / "intel.experiment.exposed.v1.json").read_text())
        jsonschema.validate(rows[0], schema, format_checker=jsonschema.FormatChecker())


def test_same_variant_as_assign_variant_on_fixed_fixtures():
    publish(3, {}, T0, experiment=EXPERIMENT)
    for account_id, expected in FIXTURES.items():
        assert assign_variant(account_id, EXPERIMENT) == expected
        assert intel_config.served(account_id).variant == expected


def test_exposure_flag_off(auth_client, world, settings):  # noqa: F811
    settings.INTEL_EMIT_EXPOSURE_EVENTS = False
    publish(3, {}, T0, experiment=EXPERIMENT)
    assert _get(auth_client(world))["meta"]["variant"] == assign_variant(world, EXPERIMENT)
    assert not OutboxEvent.objects.filter(event_type="intel.experiment.exposed").exists()
