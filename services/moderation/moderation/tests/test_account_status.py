"""The member's own view of moderation (account status, support inbox) and the
console's case filters, report drill-down and summary (track T7)."""

import uuid

import pytest
from django.urls import reverse

from moderation import services
from moderation.models import ModerationCase, OutboxEvent

pytestmark = pytest.mark.django_db

MOD = ["moderator"]


def _acct() -> str:
    return str(uuid.uuid4())


def _case(owner: str | None = None, target_type: str = "post", reporter: str | None = None):
    return services.ingest_report(
        reporter_id=reporter or _acct(),
        target_type=target_type,
        target_id=str(uuid.uuid4()),
        reason="spam",
        owner_id=owner,
    )


# ---- my cases ---------------------------------------------------------------


def test_my_cases_lists_only_my_visible_decisions(client_for):
    me, other = _acct(), _acct()
    removed = _case(owner=me)
    services.take_action(str(removed.id), _acct(), "remove", "Spam links")
    warned = _case(owner=me)
    services.take_action(str(warned.id), _acct(), "warn")
    dismissed = _case(owner=me)
    services.take_action(str(dismissed.id), _acct(), "dismiss")
    shadowed = _case(owner=me, target_type="user")
    services.take_action(str(shadowed.id), _acct(), "shadow")
    _case(owner=me)  # still open: being reported is not news to the reported
    theirs = _case(owner=other)
    services.take_action(str(theirs.id), _acct(), "remove")

    resp = client_for(me).get(reverse("moderation:my-cases"))
    assert resp.status_code == 200
    rows = resp.json()["data"]
    assert {r["id"] for r in rows} == {str(removed.id), str(warned.id)}
    by_id = {r["id"]: r for r in rows}
    assert by_id[str(removed.id)]["decision"] == "remove"
    assert by_id[str(removed.id)]["reason"] == "Spam links"
    assert by_id[str(removed.id)]["can_appeal"] is True
    assert by_id[str(removed.id)]["appeal_status"] is None
    # Nothing about who reported or who decided.
    assert set(rows[0]) == {
        "id",
        "target_type",
        "target_id",
        "decision",
        "reason",
        "decided_at",
        "appeal_status",
        "appealed_at",
        "can_appeal",
    }


def test_my_cases_shows_the_appeal_and_its_outcome(client_for):
    me = _acct()
    case = _case(owner=me)
    services.take_action(str(case.id), _acct(), "remove")
    resp = client_for(me).post(
        reverse("moderation:case-appeal", args=[case.id]),
        {"text": "It was not spam"},
        format="json",
    )
    assert resp.status_code == 201
    row = client_for(me).get(reverse("moderation:my-cases")).json()["data"][0]
    assert (row["appeal_status"], row["can_appeal"]) == ("open", False)

    appeal = case.appeals.get()
    services.resolve_appeal(str(appeal.id), _acct(), "overturned")
    row = client_for(me).get(reverse("moderation:my-cases")).json()["data"][0]
    assert row["appeal_status"] == "overturned"


def test_my_cases_requires_sign_in():
    from rest_framework.test import APIClient

    assert APIClient().get(reverse("moderation:my-cases")).status_code in (401, 403)


# ---- my reports -------------------------------------------------------------


def test_my_reports_shows_state_and_coarse_outcome(client_for):
    me = _acct()
    pending = _case(reporter=me)
    removed = _case(reporter=me)
    services.take_action(str(removed.id), _acct(), "remove", "secret moderator note")
    dismissed = _case(reporter=me)
    services.take_action(str(dismissed.id), _acct(), "dismiss")
    _case()  # someone else's report

    resp = client_for(me).get(reverse("moderation:my-reports"))
    assert resp.status_code == 200
    rows = {r["target_id"]: r for r in resp.json()["data"]}
    assert len(rows) == 3
    assert (rows[pending.target_id]["state"], rows[pending.target_id]["outcome"]) == ("open", None)
    assert rows[removed.target_id]["outcome"] == "actioned"
    assert rows[dismissed.target_id]["outcome"] == "no_action"
    assert "secret" not in resp.content.decode()
    assert "reporter_id" not in rows[pending.target_id]


def test_a_new_report_after_a_decision_joins_the_new_case(client_for):
    me, first = _acct(), _acct()
    case = _case(reporter=first)
    services.take_action(str(case.id), _acct(), "dismiss")
    services.ingest_report(
        reporter_id=me, target_type=case.target_type, target_id=case.target_id, reason="again"
    )
    row = client_for(me).get(reverse("moderation:my-reports")).json()["data"][0]
    assert (row["state"], row["outcome"]) == ("open", None)


# ---- console: filters, drill-down, summary ------------------------------------


def test_queue_filters_by_state_and_assignee(client_for):
    mod = _acct()
    mine = _case()
    services.assign(str(mine.id), mod)
    open_case = _case()
    resolved = _case()
    services.take_action(str(resolved.id), mod, "dismiss")
    client = client_for(mod, roles=MOD)

    def ids(**params):
        resp = client.get(reverse("moderation:cases"), params)
        assert resp.status_code == 200
        return {r["id"] for r in resp.json()["data"]}

    assert ids() == {str(mine.id), str(open_case.id)}
    assert ids(state="open") == {str(open_case.id)}
    assert ids(state="in_review") == {str(mine.id)}
    assert ids(state="resolved") == {str(resolved.id)}
    assert ids(assigned="me") == {str(mine.id)}
    assert client.get(reverse("moderation:cases"), {"state": "nope"}).status_code == 400
    assert client.get(reverse("moderation:cases"), {"assigned": _acct()}).status_code == 400


def test_reports_of_one_case(client_for):
    case = _case()
    services.ingest_report(
        reporter_id=_acct(), target_type="post", target_id=case.target_id, reason="scam"
    )
    _case()  # another target
    client = client_for(_acct(), roles=MOD)
    resp = client.get(reverse("moderation:reports"), {"case": str(case.id)})
    assert resp.status_code == 200
    rows = resp.json()["data"]
    assert len(rows) == 2 and {r["target_id"] for r in rows} == {case.target_id}
    by_target = client.get(
        reverse("moderation:reports"), {"target_type": "post", "target_id": case.target_id}
    )
    assert len(by_target.json()["data"]) == 2
    assert client.get(reverse("moderation:reports"), {"case": "junk"}).status_code == 404
    assert client.get(reverse("moderation:reports"), {"case": _acct()}).status_code == 404
    assert client.get(reverse("moderation:reports"), {"target_type": "post"}).status_code == 400
    # Members never see the raw reports.
    assert client_for(_acct()).get(reverse("moderation:reports")).status_code == 403


def test_summary_counts(client_for):
    mod = _acct()
    services.assign(str(_case().id), mod)
    _case()
    owner = _acct()
    appealed = _case(owner=owner)
    services.take_action(str(appealed.id), mod, "remove")
    services.file_appeal(str(appealed.id), owner, "please")

    data = client_for(mod, roles=MOD).get(reverse("moderation:summary")).json()["data"]
    assert data == {"open": 1, "in_review": 1, "assigned_to_me": 1, "open_appeals": 1}
    # Without the appeal capability the appeal count is left out.
    only_cases = client_for(mod, caps=["moderation.case.view"]).get(reverse("moderation:summary"))
    assert "open_appeals" not in only_cases.json()["data"]
    assert client_for(_acct()).get(reverse("moderation:summary")).status_code == 403


# ---- events carry who the decision is about -----------------------------------


def test_actioned_event_names_the_owner_and_resolved_names_the_appellant():
    owner = _acct()
    case = _case(owner=owner)
    services.take_action(str(case.id), _acct(), "remove")
    actioned = OutboxEvent.objects.get(event_type="moderation.actioned")
    assert actioned.payload["payload"]["owner_id"] == owner

    appeal = services.file_appeal(str(case.id), owner, "please")
    services.resolve_appeal(str(appeal.id), _acct(), "upheld")
    resolved = OutboxEvent.objects.get(event_type="appeal.resolved")
    assert resolved.payload["payload"]["account_id"] == owner


def test_actioned_event_without_owner_is_null():
    case = _case(owner=None)
    services.take_action(str(case.id), _acct(), "dismiss")
    assert ModerationCase.objects.get(id=case.id).owner_id is None
    event = OutboxEvent.objects.get(event_type="moderation.actioned")
    assert event.payload["payload"]["owner_id"] is None


def test_actioned_event_carries_the_reason_shared_with_the_owner():
    # Marketplace keeps it on a rejected/removed listing for the seller.
    listing = _case(owner=_acct(), target_type="listing")
    services.take_action(str(listing.id), _acct(), "remove", "Counterfeit item")
    quiet = _case(owner=_acct())
    services.take_action(str(quiet.id), _acct(), "warn")
    rows = OutboxEvent.objects.filter(event_type="moderation.actioned").order_by("created_at", "id")
    assert [r.payload["payload"]["reason"] for r in rows] == ["Counterfeit item", ""]


def test_actioned_payloads_match_the_json_schema():
    import json
    import os

    path = "/opt/tara/libs/tara_events/tara_events/schemas/moderation.actioned.v1.json"
    if not os.path.isfile(path):
        pytest.skip("schemas are copied into the image at /opt/tara/libs")
    with open(path, encoding="utf-8") as f:
        schema = json.load(f)
    owner = _acct()
    case = _case(owner=owner)
    services.take_action(str(case.id), _acct(), "remove", "Spam links")
    appeal = services.file_appeal(str(case.id), owner, "please")
    services.resolve_appeal(str(appeal.id), _acct(), "overturned")  # emits the reversal
    rows = list(OutboxEvent.objects.filter(event_type="moderation.actioned"))
    assert len(rows) == 2
    for row in rows:
        payload = row.payload["payload"]
        assert set(schema["required"]) <= set(payload) <= set(schema["properties"])
        assert payload["action"] in schema["properties"]["action"]["enum"]
        assert len(payload.get("reason", "")) <= schema["properties"]["reason"]["maxLength"]


# ---- evidence snapshot on message reports (decision 5.13) --------------------


def test_message_report_keeps_the_text_snapshot_for_moderators(client_for):
    message_id, owner, reporter = str(uuid.uuid4()), _acct(), _acct()
    services.ingest_report_event(
        "message.reported",
        {
            "message_id": message_id,
            "conversation_id": str(uuid.uuid4()),
            "reporter": reporter,
            "reason": "scam",
            "owner_id": owner,
            "snapshot": {
                "type": "text",
                "body": "send me your card number" + "x" * 2000,
                "created_at": "2026-11-04T10:00:00Z",
                "attachment_count": 1,
                "media_ids": ["never-kept"],
            },
        },
    )
    case = ModerationCase.objects.get(target_type="message", target_id=message_id)
    assert str(case.owner_id) == owner
    resp = client_for(_acct(), roles=MOD).get(reverse("moderation:reports"), {"case": str(case.id)})
    assert resp.status_code == 200
    [row] = resp.json()["data"]
    evidence = row["evidence"]
    assert set(evidence) == {"type", "body", "created_at", "attachment_count"}
    assert evidence["body"].startswith("send me your card number")
    assert len(evidence["body"]) == 1000
    assert evidence["attachment_count"] == 1


def test_reports_without_snapshot_have_empty_evidence(client_for):
    case = _case()
    resp = client_for(_acct(), roles=MOD).get(reverse("moderation:reports"), {"case": str(case.id)})
    assert resp.json()["data"][0]["evidence"] == {}


def test_a_case_lists_only_the_reports_it_gathered(client_for):
    reporter = _acct()
    first = _case(reporter=reporter, target_type="user")
    services.take_action(str(first.id), _acct(), "warn")
    second = services.ingest_report(
        reporter_id=reporter, target_type="user", target_id=first.target_id, reason="spam: again"
    )
    assert second.id != first.id
    client = client_for(_acct(), roles=MOD)

    def reasons(case):
        resp = client.get(reverse("moderation:reports"), {"case": str(case.id)})
        return [r["reason"] for r in resp.json()["data"]]

    assert reasons(first) == ["spam"]
    assert reasons(second) == ["spam: again"]
