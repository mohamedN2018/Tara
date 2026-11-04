"""Stories (post service, roadmap 1.9): ``story.reacted`` becomes a
``story.reaction`` notification for the author, one row per story while it is
open; ``story.deleted`` (the author's delete or a moderator's removal) takes the
story's notifications with it. Imported by ``handlers`` so the consumer
registers them.
"""

from __future__ import annotations

from tara_events import on_event
from tara_events.envelope import EventEnvelope

from . import services
from .services import notify


@on_event("story.reacted")
def on_story_reacted(e: EventEnvelope) -> None:
    p = e.payload
    notify(
        p["author_id"],
        "story.reaction",
        actor_id=p.get("reactor") or e.actor_id,
        subject_ref=f"story:{p['story_id']}",
        body="reacted to your story",
        data={"story_id": p["story_id"], "reaction_type": p.get("reaction_type")},
    )


@on_event("story.deleted")
def on_story_deleted(e: EventEnvelope) -> None:
    story_id = e.payload.get("story_id") or e.subject_id
    if story_id:
        services.purge_subject(f"story:{story_id}")
