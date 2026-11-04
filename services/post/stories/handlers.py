"""Event consumers for stories. ``moderation.actioned`` for ``target_type=story``
is routed from ``posts.handlers`` (one handler per event type keeps its dedupe
key). Blocks hide stories through ``BlockedPair`` (posts' read model); these
handlers only clean the close friends lists."""

from __future__ import annotations

from tara_events import on_event
from tara_events.envelope import EventEnvelope

from . import services


@on_event("user.blocked")
def on_user_blocked_drop_close_friends(event: EventEnvelope) -> None:
    p = event.payload
    services.drop_between(str(p["blocker_id"]), str(p["blocked_id"]))


@on_event("friendship.removed")  # an unfriend, or the friendship a block ended
def on_friendship_removed_drop_close_friends(event: EventEnvelope) -> None:
    p = event.payload
    services.drop_after_unfriend(str(p["a"]), str(p["b"]))
