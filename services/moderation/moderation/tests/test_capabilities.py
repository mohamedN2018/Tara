"""Capabilities (8.12) on the moderation API, and the events admin audits (8.1)."""

import uuid

import pytest
from django.urls import reverse

from moderation import services
from moderation.models import Appeal, ModerationCase, OutboxEvent
from tara_common.auth import mint_internal_token

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _case(owner_id=None, target_type="post") -> ModerationCase:
    return services.ingest_report(
        reporter_id=_acct(), target_type=target_type, target_id=_acct(), owner_id=owner_id
    )


def _appeal(text="أرجو المراجعة") -> Appeal:
    owner = _acct()
    case = _case(owner_id=owner)
    services.take_action(str(case.id), _acct(), "remove")
    return services.file_appeal(str(case.id), owner, text)


def test_view_without_act_can_read_the_queue_but_not_act(client_for):
    _case()
    viewer = client_for(_acct(), caps=["moderation.case.view"])
    assert viewer.get(reverse("moderation:cases")).status_code == 200
    case = ModerationCase.objects.get()
    resp = viewer.post(reverse("moderation:case-action", args=[case.id]), {"action": "dismiss"})
    assert resp.status_code == 403
    assert viewer.post(reverse("moderation:case-assign", args=[case.id])).status_code == 403
    assert ModerationCase.objects.get().state == "open"


@pytest.mark.parametrize(
    ("roles", "caps", "status"),
    [
        (["moderator"], None, 200),  # a token from before caps: role defaults
        (["admin"], None, 200),
        (["ad_reviewer"], None, 403),
        (["moderator"], [], 403),  # caps present: they win over roles
        ([], ["moderation.appeal.view"], 200),
    ],
)
def test_appeal_queue_follows_capabilities(client_for, roles, caps, status):
    resp = client_for(_acct(), roles=roles, caps=caps).get(reverse("moderation:appeals"))
    assert resp.status_code == status


def test_resolving_needs_the_resolve_capability(client_for):
    appeal = _appeal()
    url = reverse("moderation:appeal-resolve", args=[appeal.id])
    viewer = client_for(_acct(), caps=["moderation.appeal.view"])
    assert viewer.post(url, {"status": "upheld"}).status_code == 403
    resolver = client_for(_acct(), caps=["moderation.appeal.resolve"])
    assert resolver.post(url, {"status": "upheld"}).status_code == 200


def test_an_upheld_appeal_emits_appeal_resolved_without_its_text(client_for):
    appeal = _appeal(text="نص الطعن الخاص")
    mod = _acct()
    resp = client_for(mod, roles=["moderator"]).post(
        reverse("moderation:appeal-resolve", args=[appeal.id]),
        {"status": "upheld"},
        HTTP_X_REQUEST_ID="edge-m1",
    )
    assert resp.status_code == 200
    event = OutboxEvent.objects.get(event_type="appeal.resolved")
    envelope = event.payload
    assert envelope["payload"] == {
        "appeal_id": str(appeal.id),
        "case_id": str(appeal.case_id),
        "target_type": "post",
        "status": "upheld",
        "reversal": None,
        "account_id": str(appeal.account_id),
    }
    assert envelope["actor_id"] == mod
    assert event.correlation_id == "edge-m1"
    assert "نص الطعن" not in str(envelope)


def test_an_overturn_records_its_reversal_on_appeal_resolved(client_for):
    appeal = _appeal()
    client_for(_acct(), roles=["moderator"]).post(
        reverse("moderation:appeal-resolve", args=[appeal.id]), {"status": "overturned"}
    )
    resolved = OutboxEvent.objects.get(event_type="appeal.resolved")
    assert resolved.payload["payload"]["status"] == "overturned"
    assert resolved.payload["payload"]["reversal"] == "approve"


def test_moderation_actioned_carries_the_request_id(client_for):
    case = _case()
    client_for(_acct(), roles=["moderator"]).post(
        reverse("moderation:case-action", args=[case.id]),
        {"action": "dismiss"},
        HTTP_X_REQUEST_ID="edge-m2",
    )
    event = OutboxEvent.objects.get(event_type="moderation.actioned")
    assert event.correlation_id == "edge-m2"


def test_appeal_resolved_can_be_switched_off(client_for, settings):
    settings.MODERATION_EMIT_AUDIT_EVENTS = False
    appeal = _appeal()
    client_for(_acct(), roles=["moderator"]).post(
        reverse("moderation:appeal-resolve", args=[appeal.id]), {"status": "upheld"}
    )
    assert not OutboxEvent.objects.filter(event_type="appeal.resolved").exists()


def test_stats_count_open_cases(client, settings):
    settings.TARA_INTERNAL_JWT_SECRET = "shared-internal-secret-every-service-holds-0123456789"
    _case()
    closed = _case()
    services.take_action(str(closed.id), _acct(), "dismiss")
    assert client.get("/internal/v1/stats/").status_code == 401
    token = mint_internal_token(issuer="admin", audience="moderation-internal")
    resp = client.get("/internal/v1/stats/", HTTP_AUTHORIZATION=f"Bearer {token}")
    assert resp.json()["data"]["stats"] == {"open_cases": 1}


def test_account_stats_count_open_cases_about_the_account(client, settings):
    """Admin's user console (8.6): cases about the user or their content, open only."""
    settings.TARA_INTERNAL_JWT_SECRET = "shared-internal-secret-every-service-holds-0123456789"
    owner = _acct()
    _case(owner_id=owner)
    services.ingest_report(reporter_id=_acct(), target_type="user", target_id=owner)
    closed = _case(owner_id=owner)
    services.take_action(str(closed.id), _acct(), "dismiss")
    _case(owner_id=_acct())
    url = f"/internal/v1/stats/accounts/{owner}/"
    assert client.get(url).status_code == 401
    token = mint_internal_token(issuer="admin", audience="moderation-internal")
    resp = client.get(url, HTTP_AUTHORIZATION=f"Bearer {token}")
    assert resp.json()["data"]["stats"] == {"open_cases": 2}
