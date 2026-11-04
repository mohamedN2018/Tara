"""Video pipeline (roadmap 5.2): "your video is ready" for its owner.

Media records ``media.processed`` for every finished upload; only a video it
transcoded (``kind=video`` with a ``purpose``) becomes a ``video.ready`` row.
The consumer's idempotency guard drops a redelivered event, and a second
``media.processed`` for the same video (a replay with a new envelope) finds
the row already there, so the owner is told once.
"""

from __future__ import annotations

from tara_events import on_event
from tara_events.envelope import EventEnvelope

from .models import Notification
from .services import notify


@on_event("media.processed")
def on_media_processed(e: EventEnvelope) -> None:
    p = e.payload
    owner = p.get("owner")
    if p.get("kind") != "video" or not p.get("purpose") or not owner:
        return
    ref = f"media:{e.subject_id}"
    if Notification.objects.filter(
        recipient_id=owner, kind="video.ready", subject_ref=ref
    ).exists():
        return
    # No actor: the owner is the one told (notify never tells an actor about itself).
    notify(owner, "video.ready", subject_ref=ref, body="your video is ready", data={})
