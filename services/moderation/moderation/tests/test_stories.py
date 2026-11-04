"""Story reports (post service, roadmap 1.9): ``story.reported`` opens a case
owned by the author; ``remove`` goes back to post with ``target_type=story``,
and an overturned appeal approves the story again."""

import uuid

import pytest

from moderation import services
from moderation.handlers import on_story_reported
from moderation.models import ModerationCase, OutboxEvent, Report
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _reported(story_id: str, reporter: str, owner: str, reason: str = "harassment") -> None:
    on_story_reported(
        EventEnvelope(
            event_type="story.reported",
            subject_id=story_id,
            producer="post-service",
            payload={
                "story_id": story_id,
                "reporter": reporter,
                "reason": reason,
                "owner_id": owner,
            },
        )
    )


def _actioned() -> list[tuple[str, str, str]]:
    rows = OutboxEvent.objects.filter(event_type="moderation.actioned").order_by("created_at", "id")
    return [
        (
            r.payload["payload"]["target_type"],
            r.payload["payload"]["target_id"],
            r.payload["payload"]["action"],
        )
        for r in rows
    ]


def test_a_story_report_opens_a_case_owned_by_the_author():
    story, author, reporter = _acct(), _acct(), _acct()
    _reported(story, reporter, author)
    _reported(story, reporter, author)  # the same reporter again
    _reported(story, _acct(), author)
    case = ModerationCase.objects.get(target_type="story", target_id=story)
    assert str(case.owner_id) == author
    assert case.report_count == 2
    assert Report.objects.filter(target_type="story", target_id=story).count() == 2


def test_remove_then_overturn_round_trips_to_post():
    story, author = _acct(), _acct()
    _reported(story, _acct(), author)
    case = ModerationCase.objects.get(target_id=story)
    services.take_action(str(case.id), _acct(), "remove")
    appeal = services.file_appeal(str(case.id), author, "it was a holiday photo")
    services.resolve_appeal(str(appeal.id), _acct(), "overturned")
    assert _actioned() == [("story", story, "remove"), ("story", story, "approve")]
