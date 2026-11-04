"""Stories (1.9): ``story.reacted`` -> ``story.reaction`` for the author,
aggregated per story; ``story.deleted`` purges them."""

import uuid

import pytest

from notifications import handlers, registry, story_handlers
from notifications.models import Notification
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _reacted(story_id, author, reactor, reaction="love"):
    return EventEnvelope(
        event_type="story.reacted",
        subject_id=story_id,
        producer="post-service",
        payload={
            "story_id": story_id,
            "author_id": author,
            "reactor": reactor,
            "reaction_type": reaction,
        },
        actor_id=reactor,
    )


def test_reactions_reach_the_author_as_one_row_per_story():
    story_id, author, a, b = _acct(), _acct(), _acct(), _acct()
    story_handlers.on_story_reacted(_reacted(story_id, author, a))
    story_handlers.on_story_reacted(_reacted(story_id, author, b, "haha"))
    (row,) = Notification.objects.filter(kind="story.reaction")
    assert str(row.recipient_id) == author
    assert row.subject_ref == f"story:{story_id}"
    assert row.actor_count == 2
    assert row.data["story_id"] == story_id
    assert registry.url_for(row) == f"/stories/{story_id}"
    assert registry.category_of("story.reaction") == "social"


def test_handlers_are_registered_with_the_consumer():
    from tara_events.dispatch import handlers_for

    assert handlers  # imported for its side effect: story_handlers registers
    assert any(h is story_handlers.on_story_reacted for h in handlers_for("story.reacted"))
    assert any(h is story_handlers.on_story_deleted for h in handlers_for("story.deleted"))


def test_a_deleted_story_takes_its_notifications():
    story_id, author = _acct(), _acct()
    story_handlers.on_story_reacted(_reacted(story_id, author, _acct()))
    story_handlers.on_story_deleted(
        EventEnvelope(
            event_type="story.deleted",
            subject_id=story_id,
            producer="post-service",
            payload={"story_id": story_id, "author_id": author, "by": "moderation"},
        )
    )
    assert not Notification.objects.filter(kind="story.reaction").exists()
