"""Milestone 1.13: event (gathering) reports become cases; remove and approve reach post."""

import uuid

import pytest

from moderation import services
from moderation.handlers import on_gathering_reported
from moderation.models import ModerationCase, OutboxEvent, Report
from tara_common.exceptions import TaraAPIError
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _reported(gathering_id: str, reporter: str, owner: str, reason: str = "spam") -> None:
    on_gathering_reported(
        EventEnvelope(
            event_type="gathering.reported",
            subject_id=gathering_id,
            producer="post-service",
            payload={
                "gathering_id": gathering_id,
                "reporter": reporter,
                "reason": reason,
                "owner_id": owner,
            },
        )
    )


def _actioned() -> list[dict]:
    rows = OutboxEvent.objects.filter(event_type="moderation.actioned").order_by("created_at", "id")
    return [r.payload["payload"] for r in rows]


def test_a_gathering_report_opens_a_case_owned_by_the_host():
    gathering, host, reporter = _acct(), _acct(), _acct()
    _reported(gathering, reporter, host)
    _reported(gathering, reporter, host)  # the same reporter again
    _reported(gathering, _acct(), host)
    case = ModerationCase.objects.get(target_type="gathering", target_id=gathering)
    assert str(case.owner_id) == host
    assert case.report_count == 2
    assert Report.objects.filter(target_type="gathering", target_id=gathering).count() == 2


def test_remove_is_sent_to_post_with_the_gathering_target():
    gathering, host = _acct(), _acct()
    _reported(gathering, _acct(), host)
    case = ModerationCase.objects.get(target_id=gathering)
    services.take_action(str(case.id), _acct(), "remove")
    assert _actioned() == [
        {
            "case_id": str(case.id),
            "target_type": "gathering",
            "target_id": gathering,
            "action": "remove",
        }
    ]


def test_actions_outside_the_content_set_are_refused():
    gathering = _acct()
    _reported(gathering, _acct(), _acct())
    case = ModerationCase.objects.get(target_id=gathering)
    with pytest.raises(TaraAPIError):
        services.take_action(str(case.id), _acct(), "shadow")
    assert _actioned() == []


def test_an_overturned_removal_approves_the_gathering_again():
    gathering, host = _acct(), _acct()
    _reported(gathering, _acct(), host)
    case = ModerationCase.objects.get(target_id=gathering)
    services.take_action(str(case.id), _acct(), "remove")
    appeal = services.file_appeal(str(case.id), host, "it was a real event")
    services.resolve_appeal(str(appeal.id), _acct(), "overturned")
    assert [(a["target_type"], a["action"]) for a in _actioned()] == [
        ("gathering", "remove"),
        ("gathering", "approve"),
    ]
    assert services.REVERSALS[("gathering", "remove")] == "approve"


def test_a_report_without_a_gathering_id_is_dropped():
    on_gathering_reported(
        EventEnvelope(
            event_type="gathering.reported",
            subject_id=_acct(),
            producer="post-service",
            payload={"reporter": _acct(), "reason": "spam"},
        )
    )
    assert not ModerationCase.objects.exists()
