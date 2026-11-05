"""Tara Intelligence WP 4.1: a ranking config change in feed becomes one AuditEntry."""

import json
import uuid
from pathlib import Path

import pytest

import adminsvc.handlers  # noqa: F401 - registers the @on_event handlers
from adminsvc.models import AuditEntry, ProcessedEvent
from tara_events.envelope import EventEnvelope
from tara_events.worker import EventWorker

pytestmark = pytest.mark.django_db

SCHEMA = Path("/opt/tara/libs/tara_events/tara_events/schemas/intel.config.changed.v1.json")


def _deliver(env: EventEnvelope) -> None:
    EventWorker(
        None,
        exchange_name="tara.events",
        queue_name="admin.events",
        processed_model=ProcessedEvent,
        consumer_name="admin",
    )._dispatch(env)


def _env(payload: dict, actor=None) -> EventEnvelope:
    return EventEnvelope(
        event_type="intel.config.changed",
        payload=payload,
        subject_id=f"{payload['surface']}@{payload['to_version']}",
        producer="feed-service",
        actor_id=actor,
    )


PAYLOAD = {
    "surface": "home",
    "action": "activated",
    "from_version": 1,
    "to_version": 2,
    "experiment": None,
    "reason_present": True,
}


def test_an_activation_is_audited_once_with_its_actor():
    staff = str(uuid.uuid4())
    env = _env(PAYLOAD, actor=staff)
    _deliver(env)
    _deliver(env)  # a redelivery adds nothing
    entry = AuditEntry.objects.get()
    assert entry.action == "intel.config.activated"
    assert entry.target_type == "ranking_config" and entry.target_id == "home@2"
    assert str(entry.actor_id) == staff and entry.actor_kind == "account"
    assert entry.detail == {
        "surface": "home",
        "from_version": 1,
        "to_version": 2,
        "experiment": None,
        "reason_present": True,
    }
    assert entry.reason == ""  # free text never travels in the event


def test_a_system_rollback_and_a_first_version():
    _deliver(_env({**PAYLOAD, "action": "rolled_back", "from_version": 2, "to_version": 1}))
    _deliver(_env({**PAYLOAD, "action": "created", "from_version": None, "to_version": 1}))
    actions = set(AuditEntry.objects.values_list("action", flat=True))
    assert actions == {"intel.config.rolled_back", "intel.config.created"}
    assert all(e.actor_id is None for e in AuditEntry.objects.all())


def test_the_payload_matches_the_json_schema():
    if not SCHEMA.exists():
        pytest.skip("schemas are copied into the image at /opt/tara/libs")
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(PAYLOAD, json.loads(SCHEMA.read_text(encoding="utf-8")))
