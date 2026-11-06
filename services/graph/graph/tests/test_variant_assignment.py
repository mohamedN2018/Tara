"""Experiments on graph suggestions (Tara Intelligence WP 5.5): the viewer gets the
variant ``tara_common.bucketing.assign_variant`` gives (feed uses the same function),
that variant's params apply, ``meta.variant`` says which, and the exposure is
recorded once per account and experiment, behind INTEL_EMIT_EXPOSURE_EVENTS."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from django.urls import reverse

from graph import intel_config
from graph.models import IntelExposureSeen, OutboxEvent
from tara_common.bucketing import assign_variant

from .test_intel_config import publish, twelve  # noqa: F401 - the fixture

pytestmark = pytest.mark.django_db
T0 = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)
SCHEMAS = Path("/opt/tara/libs/tara_events/tara_events/schemas")

EXPERIMENT = {
    "key": "discovery_people",
    "salt": "s1",
    "variants": [
        {"name": "control", "pct": 50, "version": 1, "params": {}},
        {"name": "narrow", "pct": 50, "version": 2, "params": {"people": {"default_limit": 3}}},
    ],
}
# Fixed fixtures: the expected names were computed with tara_common.bucketing on
# 2026-11-06 (bucket % 10000 of "<id>:discovery_people:s1"; below 5000 is control).
FIXTURES = {
    "6f03e73e-ca0f-4bec-a65d-9c4aad56871b": "narrow",
    "0a4d6342-9255-4ac8-a7bd-58cfe6fe33f8": "narrow",
    "a7df4ed5-aecf-46ad-ac53-965f02945712": "control",
    "d90b9d67-b10c-455d-ac6d-ff36f3166cb1": "control",
    "11111111-1111-4111-8111-111111111111": "control",
    "22222222-2222-4222-8222-222222222222": "control",
    "33333333-3333-4333-8333-333333333333": "narrow",
    "44444444-4444-4444-8444-444444444444": "narrow",
}


def test_service_assignment_equals_assign_variant_on_fixtures():
    publish(5, {}, T0, experiment=EXPERIMENT)
    for account_id, expected in FIXTURES.items():
        assert assign_variant(account_id, EXPERIMENT) == expected
        assert intel_config.served(account_id).variant == expected


def test_partial_allocation_leaves_others_out():
    experiment = {**EXPERIMENT, "variants": [{**EXPERIMENT["variants"][1], "pct": 10}]}
    publish(5, {}, T0, experiment=experiment)
    outside = 0
    for account_id in FIXTURES:
        cfg = intel_config.served(account_id)
        assert cfg.variant == assign_variant(account_id, experiment)
        if cfg.variant is None:
            outside += 1
            assert cfg.params == intel_config.resolve()
    assert outside == 6


def test_variant_params_meta_and_one_exposure(client_for, twelve):  # noqa: F811
    me = twelve
    publish(5, {}, T0, experiment=EXPERIMENT)
    variant = assign_variant(me, EXPERIMENT)
    for _ in range(3):
        body = client_for(me).get(reverse("graph:suggestions-people")).json()
        assert body["meta"] == {"variant": variant}
        assert len(body["data"]["results"]) == (3 if variant == "narrow" else 10)
    client_for(me).get(reverse("graph:suggestions-pages"))  # same experiment, same surface
    rows = OutboxEvent.objects.filter(event_type="intel.experiment.exposed")
    assert rows.count() == 1
    payload = rows.get().payload["payload"]
    assert {k: payload[k] for k in ("experiment_key", "account_id", "variant", "surface")} == {
        "experiment_key": "discovery_people",
        "account_id": me,
        "variant": variant,
        "surface": "discovery",
    }
    assert IntelExposureSeen.objects.filter(account_id=me).count() == 1
    if SCHEMAS.exists():
        import jsonschema

        schema = json.loads((SCHEMAS / "intel.experiment.exposed.v1.json").read_text())
        jsonschema.validate(payload, schema, format_checker=jsonschema.FormatChecker())


def test_exposure_flag_off_records_nothing(client_for, twelve, settings):  # noqa: F811
    settings.INTEL_EMIT_EXPOSURE_EVENTS = False
    me = twelve
    publish(5, {}, T0, experiment=EXPERIMENT)
    body = client_for(me).get(reverse("graph:suggestions-people")).json()
    assert body["meta"]["variant"] == assign_variant(me, EXPERIMENT)
    assert not OutboxEvent.objects.filter(event_type="intel.experiment.exposed").exists()
    assert not IntelExposureSeen.objects.exists()


def test_stopped_experiment_serves_the_base_again(client_for, twelve):  # noqa: F811
    me = twelve
    publish(5, {}, T0, experiment=EXPERIMENT)
    publish(5, {}, datetime(2026, 11, 6, 10, 0, tzinfo=UTC), experiment=None)
    body = client_for(me).get(reverse("graph:suggestions-people")).json()
    assert "meta" not in body
    assert len(body["data"]["results"]) == 10


def test_minor_viewer_is_not_exposed(client_for):
    me = "6f03e73e-ca0f-4bec-a65d-9c4aad56871b"
    publish(5, {}, T0, experiment=EXPERIMENT)
    resp = client_for(me, is_minor=True, age_band="13-17").get(reverse("graph:suggestions-people"))
    assert resp.json() == {"data": {"results": []}}
    assert not OutboxEvent.objects.filter(event_type="intel.experiment.exposed").exists()
