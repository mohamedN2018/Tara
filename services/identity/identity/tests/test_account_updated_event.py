"""``account.updated`` on a language change (Tara Intelligence WP 6.7).

PATCH /me/ records the event in its own transaction, only when the language
really changed, and the payload carries the language and nothing else: never
the date of birth or the gender.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from django.urls import reverse

from identity.models import OutboxEvent

pytestmark = pytest.mark.django_db

PASSWORD = "DevPassw0rd!"
SCHEMAS = Path("/opt/tara/libs/tara_events/tara_events/schemas")


def _auth(client, account):
    resp = client.post(
        reverse("identity:login"),
        {"identifier": account.email, "password": PASSWORD},
        format="json",
    )
    assert resp.status_code == 200, resp.content
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.json()['data']['access_token']}")


def _rows():
    return list(OutboxEvent.objects.filter(event_type="account.updated").order_by("created_at"))


def _patch(client, body):
    resp = client.patch(reverse("identity:me"), body, format="json")
    assert resp.status_code == 200, resp.content
    return resp


def test_language_change_emits_once_with_the_language_only(api_client, active_account):
    active_account.language = "en"
    active_account.save(update_fields=["language"])
    _auth(api_client, active_account)
    _patch(api_client, {"language": "ar"})
    rows = _rows()
    assert len(rows) == 1
    payload = rows[0].payload["payload"]
    assert payload == {
        "account_id": str(active_account.id),
        "changed": ["language"],
        "language": "ar",
    }
    assert rows[0].payload["subject_id"] == str(active_account.id)
    text = json.dumps(rows[0].payload)
    for forbidden in ("date_of_birth", "birthday", "gender", "email", "phone"):
        assert forbidden not in text


def test_no_event_on_a_no_op_or_another_field(api_client, active_account):
    active_account.language = "ar"
    active_account.save(update_fields=["language"])
    _auth(api_client, active_account)
    _patch(api_client, {"language": "ar"})  # unchanged
    _patch(api_client, {"theme": "dark", "gender": "female"})  # not the language
    assert _rows() == []


def test_flag_off_emits_nothing(api_client, active_account, settings):
    settings.IDENTITY_EMIT_ACCOUNT_UPDATED = False
    active_account.language = "en"
    active_account.save(update_fields=["language"])
    _auth(api_client, active_account)
    _patch(api_client, {"language": "ar"})
    assert _rows() == []


def test_failed_patch_emits_nothing(api_client, active_account):
    active_account.language = "en"
    active_account.save(update_fields=["language"])
    _auth(api_client, active_account)
    resp = api_client.patch(
        reverse("identity:me"), {"language": "ar", "theme": "neon"}, format="json"
    )
    assert resp.status_code == 400
    assert _rows() == []


def test_payload_matches_the_schema(api_client, active_account):
    if not SCHEMAS.exists():
        pytest.skip("schemas are copied into the image at /opt/tara/libs")
    import jsonschema

    active_account.language = "en"
    active_account.save(update_fields=["language"])
    _auth(api_client, active_account)
    _patch(api_client, {"language": "ar"})
    schema = json.loads((SCHEMAS / "account.updated.v1.json").read_text())
    jsonschema.validate(
        _rows()[0].payload["payload"], schema, format_checker=jsonschema.FormatChecker()
    )
