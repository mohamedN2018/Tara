"""Moderation: report intake, RBAC, actions/events, appeals."""

import uuid

import pytest
from django.urls import reverse

from moderation import services
from moderation.handlers import on_post_reported
from moderation.models import ModerationCase, OutboxEvent
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def test_reported_event_opens_one_case_and_counts():
    post_id = str(uuid.uuid4())
    for _ in range(3):  # three reports for the same target
        on_post_reported(
            EventEnvelope(
                event_type="post.reported",
                subject_id=post_id,
                producer="post-service",
                payload={"post_id": post_id, "reporter": _acct(), "reason": "spam"},
            )
        )
    cases = ModerationCase.objects.filter(target_type="post", target_id=post_id)
    assert cases.count() == 1  # deduped into a single open case
    assert cases.first().report_count == 3


def test_queue_requires_moderator_role(client_for):
    # Ordinary user -> 403; moderator -> 200.
    assert client_for(_acct()).get(reverse("moderation:cases")).status_code == 403
    assert (
        client_for(_acct(), roles=["moderator"]).get(reverse("moderation:cases")).status_code == 200
    )


def test_action_resolves_case_and_emits_event(client_for):
    case = services.ingest_report(
        reporter_id=_acct(), target_type="post", target_id="p1", reason="x"
    )
    mod = _acct()
    resp = client_for(mod, roles=["moderator"]).post(
        reverse("moderation:case-action", args=[case.id]),
        {"action": "remove", "reason": "violates policy"},
        format="json",
    )
    assert resp.status_code == 200
    case.refresh_from_db()
    assert case.state == ModerationCase.State.RESOLVED
    event = OutboxEvent.objects.get(event_type="moderation.actioned")
    assert event.payload["payload"]["action"] == "remove"
    assert event.payload["payload"]["target_id"] == "p1"


def test_appeal_flow(client_for):
    user = _acct()  # the author of the reported post
    case = services.ingest_report(
        reporter_id=_acct(), target_type="post", target_id="p2", owner_id=user
    )
    services.take_action(str(case.id), _acct(), "remove")
    # The affected user files an appeal (no moderator role needed).
    filed = client_for(user).post(
        reverse("moderation:case-appeal", args=[case.id]), {"text": "please review"}, format="json"
    )
    assert filed.status_code == 201
    from moderation.models import Appeal

    appeal = Appeal.objects.get()
    # Moderator overturns -> emits an approve action.
    resolved = client_for(_acct(), roles=["moderator"]).post(
        reverse("moderation:appeal-resolve", args=[appeal.id]),
        {"status": "overturned"},
        format="json",
    )
    assert resolved.status_code == 200
    assert OutboxEvent.objects.filter(event_type="moderation.actioned").count() == 2


def test_manual_report_any_user(client_for):
    resp = client_for(_acct()).post(
        reverse("moderation:report-file"),
        {"target_type": "user", "target_id": str(uuid.uuid4()), "reason": "harassment"},
        format="json",
    )
    assert resp.status_code == 202
    assert ModerationCase.objects.filter(target_type="user").count() == 1


def test_queue_sorts_by_report_count_and_pages_through_ties(client_for):
    busiest = services.ingest_report(reporter_id=_acct(), target_type="post", target_id=_acct())
    for _ in range(2):
        services.ingest_report(reporter_id=_acct(), target_type="post", target_id=busiest.target_id)
    others = [
        services.ingest_report(reporter_id=_acct(), target_type="post", target_id=_acct())
        for _ in range(5)
    ]
    client = client_for(_acct(), roles=["moderator"])

    seen, cursor = [], None
    for _ in range(8):
        params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        body = client.get(reverse("moderation:cases"), params).json()
        seen += [c["id"] for c in body["data"]]
        cursor = body["page"]["next_cursor"]
        if not cursor:
            break
    assert seen[0] == str(busiest.id)
    assert sorted(seen) == sorted(str(c.id) for c in [busiest, *others])
