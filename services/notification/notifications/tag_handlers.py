"""People tagged in a post (wave 2C): ``post.tagged`` -> a ``post.tag`` notification.

Post emits one ``post.tagged`` per tagged person, only once the post is
published, and only to someone who can open it and is not blocked either way
with the author. Imported by ``handlers`` so the consumer registers it.
"""

from __future__ import annotations

from tara_events import on_event
from tara_events.envelope import EventEnvelope

from .services import notify


@on_event("post.tagged")
def on_post_tagged(e: EventEnvelope) -> None:
    p = e.payload
    notify(
        p["recipient"],
        "post.tag",
        actor_id=p.get("author_id") or e.actor_id,
        subject_ref=f"post:{p['post_id']}",
        body="tagged you in a post",
        data={"post_id": p["post_id"]},
    )
