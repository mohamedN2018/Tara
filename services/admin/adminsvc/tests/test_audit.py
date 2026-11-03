"""Unified audit (8.1): entries from events, the read API, and the CSV export."""

import csv
import io
import uuid
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

import adminsvc.handlers  # noqa: F401 - registers the @on_event handlers
from adminsvc import audit
from adminsvc.models import AuditEntry, ProcessedEvent
from tara_events.envelope import EventEnvelope
from tara_events.worker import EventWorker

pytestmark = pytest.mark.django_db

ADMIN_CAPS = ["admin.audit.view", "admin.audit.export"]


def _acct() -> str:
    return str(uuid.uuid4())


def _deliver(env: EventEnvelope) -> None:
    """What admin-consumer does with a message: idempotent dispatch to the handlers."""
    worker = EventWorker(
        None,
        exchange_name="tara.events",
        queue_name="admin.events",
        processed_model=ProcessedEvent,
        consumer_name="admin",
    )
    worker._dispatch(env)


def _env(event_type: str, payload: dict, *, actor=None, producer="x-service", **extra):
    return EventEnvelope(
        event_type=event_type,
        payload=payload,
        subject_id=str(extra.pop("subject_id", uuid.uuid4())),
        producer=producer,
        actor_id=actor,
        **extra,
    )


# ---- entries from events ----------------------------------------------------

EVENT_CASES = [
    (
        "account.role.granted",
        {"account_id": "11111111-1111-1111-1111-111111111111", "role": "moderator"},
        ("role.granted", "account", "11111111-1111-1111-1111-111111111111", {"role": "moderator"}),
    ),
    (
        "account.role.revoked",
        {"account_id": "11111111-1111-1111-1111-111111111111", "role": "analyst"},
        ("role.revoked", "account", "11111111-1111-1111-1111-111111111111", {"role": "analyst"}),
    ),
    (
        "capability.matrix.changed",
        {
            "role": "analyst",
            "capability": "admin.monitor.view",
            "state": "grant",
            "previous": "default",
        },
        (
            "capability.changed",
            "role",
            "analyst",
            {"capability": "admin.monitor.view", "state": "grant", "previous": "default"},
        ),
    ),
    (
        "moderation.actioned",
        {"case_id": "c1", "target_type": "post", "target_id": "p1", "action": "remove"},
        ("moderation.actioned", "post", "p1", {"case_id": "c1", "action": "remove"}),
    ),
    (
        "appeal.resolved",
        {
            "appeal_id": "a1",
            "case_id": "c1",
            "target_type": "post",
            "status": "upheld",
            "reversal": None,
        },
        (
            "appeal.resolved",
            "appeal",
            "a1",
            {"case_id": "c1", "target_type": "post", "status": "upheld", "reversal": None},
        ),
    ),
    (
        "ad.review.decided",
        {"creative_id": "cr1", "decision": "approved"},
        ("ad.review.decided", "ad_creative", "cr1", {"decision": "approved"}),
    ),
]


@pytest.mark.parametrize(("event_type", "payload", "expected"), EVENT_CASES)
def test_each_audit_worthy_event_becomes_one_entry(event_type, payload, expected):
    actor = _acct()
    env = _env(event_type, payload, actor=actor, correlation_id="req_abc123")
    _deliver(env)
    entry = AuditEntry.objects.get()
    action, target_type, target_id, detail = expected
    assert (entry.action, entry.target_type, entry.target_id) == (action, target_type, target_id)
    assert entry.detail == detail
    assert str(entry.actor_id) == actor and entry.actor_kind == "account"
    assert entry.request_id == "req_abc123"
    assert entry.occurred_at.isoformat().startswith(env.occurred_at[:19])


def test_the_same_event_delivered_twice_creates_one_entry():
    env = _env("ad.review.decided", {"creative_id": "cr1", "decision": "rejected"}, actor=_acct())
    _deliver(env)
    _deliver(env)
    assert AuditEntry.objects.count() == 1
    # Even past the ProcessedEvent guard (e.g. its row was purged), the event id is unique.
    ProcessedEvent.objects.all().delete()
    _deliver(env)
    assert AuditEntry.objects.count() == 1


def test_a_system_actor_is_recorded_without_errors():
    _deliver(
        _env(
            "moderation.actioned",
            {"case_id": "c1", "target_type": "listing", "target_id": "l1", "action": "approve"},
            actor=None,
            producer="moderation-service",
        )
    )
    entry = AuditEntry.objects.get()
    assert entry.actor_kind == "system"
    assert entry.actor_id is None
    assert entry.actor_name == "moderation-service"


def test_no_free_text_or_private_content_reaches_the_log():
    _deliver(
        _env(
            "appeal.resolved",
            {
                "appeal_id": "a1",
                "case_id": "c1",
                "status": "overturned",
                "text": "رسالة خاصة جدا",
                "reason": "private words",
                "nested": {"body": "secret"},
            },
            actor=_acct(),
        )
    )
    entry = AuditEntry.objects.get()
    blob = str(entry.detail)
    assert "رسالة" not in blob and "private" not in blob and "secret" not in blob


def test_a_malformed_request_id_or_actor_is_dropped_not_fatal():
    _deliver(
        _env(
            "account.role.granted",
            {"account_id": "x", "role": "admin"},
            actor="not-a-uuid",
            correlation_id="<script>alert(1)</script>",
        )
    )
    entry = AuditEntry.objects.get()
    assert entry.request_id == ""
    assert entry.actor_kind == "system"


def test_a_non_dict_payload_does_not_dead_letter():
    env = EventEnvelope(
        event_type="ad.review.decided", payload=[], subject_id="cr9", producer="ads-service"
    )
    _deliver(env)
    assert AuditEntry.objects.get().target_id == "cr9"


# ---- read API ---------------------------------------------------------------


def _entry(action="role.granted", *, actor=None, minutes_ago=0, **fields):
    return audit.record(
        action,
        actor_id=actor,
        actor_name="identity-service" if actor is None else "",
        occurred_at=timezone.now() - timedelta(minutes=minutes_ago),
        **fields,
    )


def test_audit_list_requires_the_capability(client_for):
    url = reverse("adminsvc:audit")
    assert client_for(_acct()).get(url).status_code == 403
    assert client_for(_acct(), roles=["moderator"]).get(url).status_code == 403
    # A role in the token is not enough when the token's caps say otherwise.
    assert client_for(_acct(), roles=["admin"], caps=[]).get(url).status_code == 403
    assert client_for(_acct(), caps=["admin.audit.view"]).get(url).status_code == 200


def test_a_token_without_caps_falls_back_to_its_roles(client_for):
    """Tokens minted before 8.12 carry only roles: admin keeps every capability."""
    _entry()
    resp = client_for(_acct(), roles=["admin"]).get(reverse("adminsvc:audit"))
    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 1


def test_audit_list_filters(client_for):
    me, other = _acct(), _acct()
    _entry("role.granted", actor=me, target_type="account", target_id="t1", minutes_ago=30)
    _entry("feature_flag.changed", actor=other, target_type="feature_flag", target_id="beta")
    _entry("moderation.actioned", actor=None, target_type="post", target_id="p1", minutes_ago=5)
    client = client_for(_acct(), caps=["admin.audit.view"])
    url = reverse("adminsvc:audit")

    def actions(**params):
        resp = client.get(url, params)
        assert resp.status_code == 200, resp.content
        return [row["action"] for row in resp.json()["data"]]

    assert actions(actor=me) == ["role.granted"]
    assert actions(actor="system") == ["moderation.actioned"]
    assert actions(action="feature_flag.changed") == ["feature_flag.changed"]
    assert actions(target_type="post", target_id="p1") == ["moderation.actioned"]
    since = (timezone.now() - timedelta(minutes=10)).isoformat()
    assert actions(since=since) == ["feature_flag.changed", "moderation.actioned"]
    until = (timezone.now() - timedelta(minutes=10)).isoformat()
    assert actions(until=until) == ["role.granted"]


@pytest.mark.parametrize(
    "params",
    [
        {"actor": "nobody"},
        {"since": "yesterday"},
        {"action": "x" * 65},
        {"since": "2026-11-02T00:00:00Z", "until": "2026-11-01T00:00:00Z"},
    ],
)
def test_bad_filters_are_a_400_not_a_500(client_for, params):
    resp = client_for(_acct(), caps=["admin.audit.view"]).get(reverse("adminsvc:audit"), params)
    assert resp.status_code == 400


def test_audit_list_is_keyset_paginated_newest_first(client_for):
    same_time = timezone.now() - timedelta(minutes=1)
    ids = {str(audit.record("role.granted", occurred_at=same_time).id) for _ in range(5)}
    ids |= {str(_entry(minutes_ago=m).id) for m in (2, 3)}
    client = client_for(_acct(), caps=["admin.audit.view"])
    seen, cursor, pages = [], None, 0
    while True:
        params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        body = client.get(reverse("adminsvc:audit"), params).json()
        seen += [row["id"] for row in body["data"]]
        pages += 1
        cursor = body["page"]["next_cursor"]
        if not cursor:
            break
    assert len(seen) == len(set(seen)) == 7
    assert set(seen) == ids
    times = [AuditEntry.objects.get(id=i).occurred_at for i in seen]
    assert times == sorted(times, reverse=True)
    assert pages == 4


# ---- CSV export -------------------------------------------------------------


def _export(client, **params) -> tuple[object, str]:
    resp = client.get(reverse("adminsvc:audit-export"), params)
    body = b"".join(resp.streaming_content).decode("utf-8") if resp.status_code == 200 else ""
    return resp, body


def test_export_needs_its_own_capability(client_for):
    url = reverse("adminsvc:audit-export")
    assert client_for(_acct(), caps=["admin.audit.view"]).get(url).status_code == 403
    assert client_for(_acct(), roles=["moderator"]).get(url).status_code == 403
    assert client_for(_acct(), caps=["admin.audit.export"]).get(url).status_code == 200


def test_export_is_utf8_with_bom_and_keeps_arabic(client_for):
    _entry("feature_flag.changed", target_type="feature_flag", target_id="ميزة_جديدة")
    resp, body = _export(client_for(_acct(), caps=ADMIN_CAPS))
    assert resp["Content-Type"].startswith("text/csv")
    assert "attachment" in resp["Content-Disposition"]
    raw = body.encode("utf-8")
    assert raw.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(io.StringIO(body.removeprefix("﻿"), newline="")))
    assert rows[0] == list(audit.CSV_COLUMNS)
    assert any("ميزة_جديدة" in row for row in rows[1:])


@pytest.mark.parametrize(
    "payload", ['=HYPERLINK("http://x")', "+1+1", "-2+3", "@SUM(A1)", "\tcmd", "\rcmd"]
)
def test_export_neutralises_spreadsheet_formulas(client_for, payload):
    _entry("feature_flag.changed", target_type="feature_flag", target_id=payload)
    _, body = _export(client_for(_acct(), caps=ADMIN_CAPS), action="feature_flag.changed")
    rows = list(csv.reader(io.StringIO(body.removeprefix("﻿"), newline="")))
    target = rows[1][audit.CSV_COLUMNS.index("target_id")]
    assert target == "'" + payload


def test_csv_safe_leaves_ordinary_text_alone():
    assert audit.csv_safe("role.granted") == "role.granted"
    assert audit.csv_safe("مرحبا") == "مرحبا"
    assert audit.csv_safe(None) == ""


def test_export_has_a_hard_row_cap(client_for, settings):
    settings.ADMIN_AUDIT_EXPORT_MAX_ROWS = 3
    for minutes in range(5):
        _entry(minutes_ago=minutes + 1)
    resp, body = _export(client_for(_acct(), caps=ADMIN_CAPS), action="role.granted")
    rows = list(csv.reader(io.StringIO(body.removeprefix("﻿"), newline="")))
    assert len(rows) == 1 + 3
    assert resp["X-Export-Truncated"] == "true"


def test_the_export_itself_is_audited_with_the_edge_request_id(client_for):
    me = _acct()
    client = client_for(me, caps=ADMIN_CAPS)
    resp = client.get(
        reverse("adminsvc:audit-export"), {"action": "role.granted"}, HTTP_X_REQUEST_ID="edge-1"
    )
    b"".join(resp.streaming_content)
    entry = AuditEntry.objects.get(action="audit.exported")
    assert str(entry.actor_id) == me
    assert entry.request_id == "edge-1"
    assert entry.detail["action"] == "role.granted"
    assert entry.detail["truncated"] is False


def test_flag_changes_are_audited_in_the_same_transaction(client_for):
    me = _acct()
    resp = client_for(me, caps=["admin.flags.manage"]).patch(
        reverse("adminsvc:feature-flag-detail", args=["beta"]),
        {"enabled": True, "rollout_pct": 10},
        format="json",
        HTTP_X_REQUEST_ID="edge-2",
    )
    assert resp.status_code == 200
    entry = AuditEntry.objects.get(action="feature_flag.changed")
    assert (entry.target_id, str(entry.actor_id), entry.request_id) == ("beta", me, "edge-2")
    assert entry.detail == {"enabled": True, "rollout_pct": 10}
