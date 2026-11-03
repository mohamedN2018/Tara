"""Milestone 1.11: group reports become cases; remove and approve reach profile."""

import uuid

import pytest

from moderation import services
from moderation.handlers import on_group_reported
from moderation.models import ModerationCase, OutboxEvent, Report
from tara_common.exceptions import TaraAPIError
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _reported(group_id: str, reporter: str, owner: str, reason: str = "spam") -> None:
    on_group_reported(
        EventEnvelope(
            event_type="group.reported",
            subject_id=group_id,
            producer="profile-service",
            payload={
                "group_id": group_id,
                "reporter": reporter,
                "reason": reason,
                "owner_id": owner,
            },
        )
    )


def _actioned() -> list[dict]:
    rows = OutboxEvent.objects.filter(event_type="moderation.actioned").order_by("created_at", "id")
    return [r.payload["payload"] for r in rows]


def test_a_group_report_opens_a_case_owned_by_the_groups_owner():
    group, owner, reporter = _acct(), _acct(), _acct()
    _reported(group, reporter, owner)
    _reported(group, reporter, owner)  # the same reporter again
    _reported(group, _acct(), owner, "hate")
    case = ModerationCase.objects.get(target_type="group", target_id=group)
    assert str(case.owner_id) == owner
    assert case.report_count == 2
    assert Report.objects.filter(target_type="group", target_id=group).count() == 2


def test_remove_then_an_overturned_appeal_round_trips_to_profile():
    group, owner = _acct(), _acct()
    _reported(group, _acct(), owner)
    case = ModerationCase.objects.get(target_id=group)
    services.take_action(str(case.id), _acct(), "remove")
    appeal = services.file_appeal(str(case.id), owner, "we follow the rules")
    services.resolve_appeal(str(appeal.id), _acct(), "overturned")
    assert [(a["target_type"], a["target_id"], a["action"]) for a in _actioned()] == [
        ("group", group, "remove"),
        ("group", group, "approve"),
    ]
    assert services.REVERSALS[("group", "remove")] == "approve"
    assert services.allowed_actions("group") == services.ACTIONS_BY_TARGET["group"]


def test_actions_outside_the_content_set_are_refused_for_groups():
    group = _acct()
    _reported(group, _acct(), _acct())
    case = ModerationCase.objects.get(target_id=group)
    with pytest.raises(TaraAPIError):
        services.take_action(str(case.id), _acct(), "restrict")
    assert _actioned() == []


def test_a_group_report_without_a_group_id_is_dropped():
    on_group_reported(
        EventEnvelope(
            event_type="group.reported",
            subject_id=_acct(),
            producer="profile-service",
            payload={"reporter": _acct(), "reason": "spam"},
        )
    )
    assert not ModerationCase.objects.exists()
