"""Voice and video calls on LiveKit (roadmap 3.7, 3.8). Lives in chat's database.

A call belongs to one conversation. At most one call per conversation is live
(ringing or active): the conversation row lock serialises starts, and a partial
unique index backs it up. The LiveKit room name is generated here, never taken
from a client.
"""

from __future__ import annotations

from django.db import models

from tara_events.envelope import uuid7

LIVE_STATES = ("ringing", "active")


class Call(models.Model):
    class Kind(models.TextChoices):
        AUDIO = "audio", "Audio"
        VIDEO = "video", "Video"

    class State(models.TextChoices):
        RINGING = "ringing", "Ringing"
        ACTIVE = "active", "Active"
        ENDED = "ended", "Ended"
        MISSED = "missed", "Missed"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    conversation = models.ForeignKey(
        "chat.Conversation", on_delete=models.CASCADE, related_name="calls"
    )
    # "call_<id hex>_<random>": bound to this call and unguessable.
    room = models.CharField(max_length=96, unique=True)
    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.AUDIO)
    state = models.CharField(max_length=8, choices=State.choices, default=State.RINGING)
    initiator_id = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)
    answered_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    # hangup | declined | cancelled | timeout | left | lost | revoked
    end_reason = models.CharField(max_length=16, blank=True, default="")
    # Last state change or webhook; the reconcile job looks at quiet live calls.
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "call"
        constraints = [
            models.UniqueConstraint(
                fields=["conversation"],
                condition=models.Q(state__in=LIVE_STATES),
                name="call_one_live_per_conversation",
            ),
        ]
        indexes = [
            models.Index(fields=["state", "created_at"], name="call_state_idx"),
            models.Index(fields=["conversation", "-created_at"], name="call_conversation_idx"),
        ]

    @property
    def is_live(self) -> bool:
        return self.state in LIVE_STATES

    @property
    def duration_s(self) -> int:
        if not self.answered_at or not self.ended_at:
            return 0
        return max(0, int((self.ended_at - self.answered_at).total_seconds()))


class CallParticipant(models.Model):
    class State(models.TextChoices):
        RINGING = "ringing", "Ringing"
        ACCEPTED = "accepted", "Accepted"  # holds a join token, has not left
        DECLINED = "declined", "Declined"
        MISSED = "missed", "Missed"
        LEFT = "left", "Left"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    call = models.ForeignKey(Call, on_delete=models.CASCADE, related_name="participants")
    account_id = models.UUIDField()
    state = models.CharField(max_length=8, choices=State.choices, default=State.RINGING)
    invited_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    left_at = models.DateTimeField(null=True, blank=True)
    # From LiveKit webhooks (the event's own time), so a crashed client still leaves.
    room_joined_at = models.DateTimeField(null=True, blank=True)
    room_left_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "call_participant"
        constraints = [
            models.UniqueConstraint(fields=["call", "account_id"], name="call_participant_uniq"),
        ]
        indexes = [
            models.Index(fields=["account_id"], name="call_participant_account_idx"),
            models.Index(fields=["state", "invited_at"], name="call_participant_state_idx"),
        ]

    @property
    def in_room(self) -> bool:
        if self.room_joined_at is None:
            return False
        return self.room_left_at is None or self.room_left_at < self.room_joined_at


class LiveKitWebhookEvent(models.Model):
    """A webhook already applied (LiveKit retries; ids make replays a no-op)."""

    event_id = models.CharField(max_length=64, primary_key=True)
    event = models.CharField(max_length=32)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "livekit_webhook_event"
        indexes = [models.Index(fields=["received_at"], name="livekit_webhook_received_idx")]
