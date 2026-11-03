"""Celery tasks: LiveKit server API side effects, the ring sweeper and the reconcile job."""

from __future__ import annotations

from celery import shared_task

from . import livekit, services


@shared_task(
    name="calls.kick",
    ignore_result=True,
    autoretry_for=(livekit.LiveKitUnavailable,),
    retry_backoff=2,
    max_retries=5,
)
def kick(room: str, identity: str) -> None:
    """Remove one participant from a LiveKit room (removed member, block, late join)."""
    livekit.remove_participant(room, identity)


@shared_task(
    name="calls.close_room",
    ignore_result=True,
    autoretry_for=(livekit.LiveKitUnavailable,),
    retry_backoff=2,
    max_retries=5,
)
def close_room(room: str) -> None:
    """Disconnect everyone still in the room of a call that ended."""
    livekit.delete_room(room)


@shared_task(name="calls.sweep", ignore_result=True)
def sweep() -> int:
    return services.sweep_ringing()


@shared_task(name="calls.reconcile", ignore_result=True)
def reconcile() -> int:
    return services.reconcile_live()
