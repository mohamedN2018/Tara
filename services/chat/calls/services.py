"""Call lifecycle: start or join, accept, decline, end, ring timeouts, webhooks, kicks.

States: a call starts ``ringing``; the first callee who accepts makes it
``active``; it finishes ``ended`` (talked, declined, or everyone left) or
``missed`` (nobody answered: the ring timed out or the caller gave up).

Rules (roadmap 3.7, 3.8):

* Only active members of a DM, group or marketplace conversation may call; a
  blocked pair cannot call each other, and a conversation the caller cannot
  see answers 404 like everywhere in Tara.
* The room name is generated here and bound to the call id. A client never
  names a room, and a token never grants more than that one room.
* Every state change takes the conversation row lock first, then the call row
  lock (the same order everywhere, so concurrent requests, webhooks and the
  sweeper cannot deadlock). One live call per conversation follows from that
  lock, with a partial unique index as a backstop.
* Events go through the outbox in the same transaction. LiveKit server API
  calls (kick, close a room) run in Celery tasks after the commit.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from chat import events
from chat import services as chat
from chat.models import BlockedPair, Conversation, ConversationMember, Message
from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from tara_common.exceptions import TaraAPIError
from tara_events.envelope import uuid7

from . import livekit
from .models import LIVE_STATES, Call, CallParticipant, LiveKitWebhookEvent

logger = logging.getLogger("tara.chat.calls")

CALLABLE_TYPES = (
    Conversation.Type.DM,
    Conversation.Type.GROUP,
    Conversation.Type.MARKETPLACE,
)
PAIR_TYPES = (Conversation.Type.DM, Conversation.Type.MARKETPLACE)
P = CallParticipant.State
WEBHOOK_KEEP = timedelta(days=2)
SWEEP_BATCH = 200


def _error(message: str, code: str, status: int) -> TaraAPIError:
    return TaraAPIError(message, code=code, http_status_code=status)


def _conversation_not_found() -> TaraAPIError:
    return _error("Conversation not found.", "not_found", 404)


def _call_not_found() -> TaraAPIError:
    return _error("Call not found.", "not_found", 404)


def require_enabled() -> None:
    if not livekit.enabled():
        raise _error("Calls are not available.", "calls_unavailable", 503)


def config() -> dict:
    return {
        "enabled": livekit.enabled(),
        "ring_timeout_s": settings.CALL_RING_TIMEOUT_SECONDS,
        "max_participants": settings.CALL_MAX_PARTICIPANTS,
    }


# ---- who may call --------------------------------------------------------------


def _pair_blocked(conversation: Conversation, actor_id: str) -> bool:
    others = [m for m in chat.member_ids(conversation) if m != str(actor_id)]
    return bool(others) and chat.is_blocked(str(actor_id), others[0])


def _member_for_call(actor_id: str, conversation_id) -> ConversationMember:
    """The caller's active membership; 404 when hidden, left or blocked (DM)."""
    member = (
        ConversationMember.objects.select_related("conversation")
        .filter(conversation_id=conversation_id, account_id=actor_id, left_at__isnull=True)
        .first()
    )
    if member is None:
        raise _conversation_not_found()
    conversation = member.conversation
    if conversation.type in PAIR_TYPES and _pair_blocked(conversation, actor_id):
        raise _conversation_not_found()
    return member


def _visible_call(actor_id: str, call_id) -> Call:
    call = Call.objects.filter(id=call_id).first()
    if call is None:
        raise _call_not_found()
    try:
        _member_for_call(actor_id, call.conversation_id)
    except TaraAPIError as exc:
        raise _call_not_found() from exc
    return call


def _blocked_with(account_id: str) -> set[str]:
    pairs = BlockedPair.objects.filter(
        Q(blocker_id=account_id) | Q(blocked_id=account_id)
    ).values_list("blocker_id", "blocked_id")
    return {str(x) for pair in pairs for x in pair} - {str(account_id)}


def _callees(conversation: Conversation, initiator_id: str) -> list[str]:
    """Who rings: the other active members. In a group, never someone with a
    block either way with the caller."""
    others = [m for m in chat.member_ids(conversation) if m != str(initiator_id)]
    if conversation.type == Conversation.Type.GROUP:
        blocked = _blocked_with(str(initiator_id))
        others = [o for o in others if o not in blocked]
    return others


def _lock(conversation_id, actor_id: str | None = None) -> Conversation:
    """Take the conversation row lock (membership changes take it too) and
    re-check membership under it."""
    conversation = Conversation.objects.select_for_update().get(id=conversation_id)
    if (
        actor_id is not None
        and not conversation.members.filter(account_id=actor_id, left_at__isnull=True).exists()
    ):
        raise _conversation_not_found()
    return conversation


def _lock_call(call_id) -> Call:
    return Call.objects.select_for_update().get(id=call_id)


# ---- events, logs and LiveKit side effects ----------------------------------------


def _emit(event_type: str, call: Call, actor_id: str | None = None, **payload) -> None:
    events.emit(
        event_type,
        subject_id=str(call.id),
        payload={
            "call_id": str(call.id),
            "conversation_id": str(call.conversation_id),
            "kind": call.kind,
            **payload,
        },
        actor_id=str(actor_id) if actor_id else None,
        partition_key=f"conversation:{call.conversation_id}",
    )


def _log(conversation: Conversation, call: Call, code: str) -> None:
    """The call-log line in the conversation (a ``system`` message)."""
    chat._record_message(
        str(conversation.id), str(call.initiator_id), body=code, message_type=Message.Type.SYSTEM
    )


def _after_commit(task_name: str, *args: str) -> None:
    def enqueue() -> None:
        from . import tasks

        try:
            getattr(tasks, task_name).delay(*args)
        except Exception:  # noqa: BLE001 - the state change is already committed
            logger.warning("could not queue %s", task_name, exc_info=True)

    transaction.on_commit(enqueue)


def _kick(call: Call, account_id: str) -> None:
    _after_commit("kick", call.room, str(account_id))


def _close_room(call: Call) -> None:
    _after_commit("close_room", call.room)


def _ids(values) -> list[str]:
    return sorted({str(v) for v in values})


def _audience(conversation: Conversation, call: Call) -> list[str]:
    """Members now, plus anyone who took part (a removed member's UI must clear too)."""
    return _ids(
        [*chat.member_ids(conversation), *call.participants.values_list("account_id", flat=True)]
    )


# ---- state changes -------------------------------------------------------------------


def _create(conversation: Conversation, actor_id: str, kind: str) -> Call:
    callees = _callees(conversation, actor_id)
    if not callees:
        raise _error("There is nobody to call here.", "validation_error", 400)
    call_id = uuid7()
    call = Call.objects.create(
        id=call_id,
        conversation=conversation,
        room=f"call_{call_id.hex}_{secrets.token_urlsafe(18)}",
        kind=kind,
        initiator_id=actor_id,
    )
    now = timezone.now()
    CallParticipant.objects.bulk_create(
        [CallParticipant(call=call, account_id=actor_id, state=P.ACCEPTED, accepted_at=now)]
        + [CallParticipant(call=call, account_id=c) for c in callees]
    )
    ring_ends = call.created_at + timedelta(seconds=settings.CALL_RING_TIMEOUT_SECONDS)
    _emit(
        "call.started",
        call,
        actor_id,
        conversation_type=conversation.type,
        initiator=str(actor_id),
        recipients=callees,
        ring_expires_at=ring_ends.isoformat(),
    )
    return call


def _accept(call: Call, conversation: Conversation, actor_id: str) -> None:
    """Take (or keep) a seat in the call. A callee's first accept answers it."""
    participant = (
        CallParticipant.objects.select_for_update().filter(call=call, account_id=actor_id).first()
    )
    if participant is not None and participant.state == P.ACCEPTED:
        return  # a rejoin or a second tab: only a fresh token
    if call.participants.filter(state=P.ACCEPTED).count() >= settings.CALL_MAX_PARTICIPANTS:
        raise _error("This call is full.", "call_full", 409)
    now = timezone.now()
    if participant is None:  # joined the group after the call started
        participant = CallParticipant(call=call, account_id=actor_id)
    participant.state = P.ACCEPTED
    participant.accepted_at = now
    participant.left_at = None
    participant.save()
    if str(actor_id) == str(call.initiator_id):
        return
    if call.state == Call.State.RINGING:
        call.state = Call.State.ACTIVE
        call.answered_at = now
    call.save()
    _emit(
        "call.answered",
        call,
        actor_id,
        account=str(actor_id),
        recipients=_audience(conversation, call),
    )


def _finish(call: Call, conversation: Conversation, state: str, reason: str) -> None:
    """End a live call once: tell everyone, log it, close the LiveKit room."""
    now = timezone.now()
    ringing = _ids(call.participants.filter(state=P.RINGING).values_list("account_id", flat=True))
    call.participants.filter(state=P.RINGING).update(state=P.MISSED, left_at=now)
    call.participants.filter(state=P.ACCEPTED).update(state=P.LEFT, left_at=now)
    call.state = state
    call.ended_at = now
    call.end_reason = reason
    call.save()
    audience = _audience(conversation, call)
    if state == Call.State.MISSED:
        _emit(
            "call.missed",
            call,
            initiator=str(call.initiator_id),
            missed=ringing,
            final=True,
            reason=reason,
            recipients=audience,
        )
        _log(conversation, call, f"call:missed:{call.kind}")
    else:
        _emit(
            "call.ended",
            call,
            reason=reason,
            duration_s=call.duration_s,
            ringing=ringing,
            recipients=audience,
        )
        if ringing and call.answered_at:
            # Group members still ringing when the call ended missed it.
            _emit(
                "call.missed",
                call,
                initiator=str(call.initiator_id),
                missed=ringing,
                final=False,
                reason="ended",
                recipients=ringing,
            )
        if call.answered_at:
            _log(conversation, call, f"call:ended:{call.kind}:{call.duration_s}")
        elif reason == "declined":
            _log(conversation, call, f"call:declined:{call.kind}")
        else:
            _log(conversation, call, f"call:missed:{call.kind}")
    _close_room(call)


def _decline(call: Call, conversation: Conversation, participant: CallParticipant) -> None:
    participant.state = P.DECLINED
    participant.left_at = timezone.now()
    participant.save()
    _emit(
        "call.declined",
        call,
        participant.account_id,
        account=str(participant.account_id),
        recipients=_audience(conversation, call),
    )
    if conversation.type != Conversation.Type.GROUP:
        _finish(call, conversation, Call.State.ENDED, "declined")
    elif (
        call.state == Call.State.RINGING and not call.participants.filter(state=P.RINGING).exists()
    ):
        _finish(call, conversation, Call.State.ENDED, "declined")


def _leave(
    call: Call, conversation: Conversation, participant: CallParticipant, reason: str, kick=True
) -> None:
    """A group participant leaves; the call ends with the last one."""
    if participant.state == P.ACCEPTED:
        participant.state = P.LEFT
        participant.left_at = timezone.now()
        participant.save()
        if kick:
            _kick(call, participant.account_id)
    if not call.participants.filter(state=P.ACCEPTED).exists():
        if call.state == Call.State.RINGING:
            _finish(call, conversation, Call.State.MISSED, "cancelled")
        else:
            _finish(call, conversation, Call.State.ENDED, reason)


def _hang_up(call: Call, conversation: Conversation, participant: CallParticipant, reason: str):
    if participant.state == P.RINGING:
        _decline(call, conversation, participant)
    elif participant.state != P.ACCEPTED:
        return
    elif conversation.type != Conversation.Type.GROUP:
        if call.state == Call.State.RINGING:
            _finish(call, conversation, Call.State.MISSED, "cancelled")
        else:
            _finish(call, conversation, Call.State.ENDED, reason)
    else:
        _leave(call, conversation, participant, reason)


# ---- API -------------------------------------------------------------------------------


def _grant(call: Call, actor_id: str) -> dict:
    return {
        "call_id": str(call.id),
        "room": call.room,
        "token": livekit.mint_token(call.room, str(actor_id)),
        "url": settings.LIVEKIT_URL,
        "call": call,
    }


def start_call(actor_id: str, conversation_id, kind: str) -> tuple[dict, bool]:
    """Start a call, or join the live one. Returns ``(grant, created)``."""
    require_enabled()
    if kind not in Call.Kind.values:
        raise _error("kind must be audio or video.", "validation_error", 400)
    member = _member_for_call(actor_id, conversation_id)
    if member.conversation.type not in CALLABLE_TYPES:
        raise _error("This conversation cannot have calls.", "validation_error", 400)
    with transaction.atomic():
        conversation = _lock(conversation_id, actor_id)
        live = (
            Call.objects.select_for_update()
            .filter(conversation=conversation, state__in=LIVE_STATES)
            .first()
        )
        if live is not None:
            _accept(live, conversation, actor_id)
            return _grant(live, actor_id), False
        return _grant(_create(conversation, actor_id, kind), actor_id), True


def join_call(actor_id: str, call_id) -> dict:
    """Accept a ringing call, join a live one late, or get a fresh token."""
    require_enabled()
    call = _visible_call(actor_id, call_id)
    with transaction.atomic():
        conversation = _lock(call.conversation_id, actor_id)
        call = _lock_call(call.id)
        if not call.is_live:
            raise _error("This call has ended.", "call_ended", 409)
        _accept(call, conversation, actor_id)
    return _grant(call, actor_id)


def decline_call(actor_id: str, call_id) -> Call:
    require_enabled()
    call = _visible_call(actor_id, call_id)
    with transaction.atomic():
        conversation = _lock(call.conversation_id, actor_id)
        call = _lock_call(call.id)
        participant = call.participants.select_for_update().filter(account_id=actor_id).first()
        if call.is_live and participant is not None and participant.state == P.RINGING:
            _decline(call, conversation, participant)
    return call


def end_call(actor_id: str, call_id) -> Call:
    """Hang up. A DM call ends for both; in a group the caller leaves. Idempotent."""
    require_enabled()
    call = _visible_call(actor_id, call_id)
    with transaction.atomic():
        conversation = _lock(call.conversation_id, actor_id)
        call = _lock_call(call.id)
        participant = call.participants.select_for_update().filter(account_id=actor_id).first()
        if call.is_live and participant is not None:
            _hang_up(call, conversation, participant, "hangup")
    return call


def active_call(actor_id: str, conversation_id) -> Call | None:
    require_enabled()
    _member_for_call(actor_id, conversation_id)
    return (
        Call.objects.filter(conversation_id=conversation_id, state__in=LIVE_STATES)
        .prefetch_related("participants")
        .first()
    )


def with_participants(call: Call) -> Call:
    return Call.objects.prefetch_related("participants").get(id=call.id)


# ---- access revoked (member removed, or a block) ------------------------------------


def revoke_access(conversation: Conversation, accounts: list[str]) -> None:
    """Called by chat under the conversation lock when ``accounts`` lose access.

    A DM or marketplace call ends (a block). In a group the removed member is
    kicked from the LiveKit room and the call goes on without them.
    """
    with transaction.atomic():
        _lock(conversation.id)
        live = (
            Call.objects.select_for_update()
            .filter(conversation_id=conversation.id, state__in=LIVE_STATES)
            .first()
        )
        if live is None:
            return
        if conversation.type != Conversation.Type.GROUP:
            if live.state == Call.State.RINGING:
                _finish(live, conversation, Call.State.MISSED, "cancelled")
            else:
                _finish(live, conversation, Call.State.ENDED, "hangup")
            return
        revoked = []
        for participant in live.participants.select_for_update().filter(account_id__in=accounts):
            if participant.state == P.ACCEPTED:
                _kick(live, participant.account_id)
            elif participant.state != P.RINGING:
                continue
            participant.state = P.LEFT
            participant.left_at = timezone.now()
            participant.save()
            revoked.append(str(participant.account_id))
        if not revoked:
            return
        if not live.participants.filter(state=P.ACCEPTED).exists():
            _finish(live, conversation, live_end_state(live), live_end_reason(live))
        else:
            # Only the removed accounts hear it: their call UI and ringing clear.
            _emit(
                "call.ended",
                live,
                reason="revoked",
                duration_s=0,
                ringing=revoked,
                recipients=revoked,
            )


def live_end_state(call: Call) -> str:
    return Call.State.MISSED if call.state == Call.State.RINGING else Call.State.ENDED


def live_end_reason(call: Call) -> str:
    return "cancelled" if call.state == Call.State.RINGING else "hangup"


# ---- ring timeouts and reconcile (beat) -------------------------------------------


def sweep_ringing(now: datetime | None = None) -> int:
    """Calls nobody answered within the ring timeout become missed, exactly once;
    group members still ringing on an answered call miss it too."""
    now = now or timezone.now()
    cutoff = now - timedelta(seconds=settings.CALL_RING_TIMEOUT_SECONDS)
    done = 0
    stale = Call.objects.filter(state=Call.State.RINGING, created_at__lt=cutoff).values_list(
        "id", "conversation_id"
    )[:SWEEP_BATCH]
    for call_id, conversation_id in list(stale):
        with transaction.atomic():
            conversation = _lock(conversation_id)
            call = _lock_call(call_id)
            if call.state != Call.State.RINGING or call.created_at >= cutoff:
                continue  # answered, ended or swept meanwhile
            _finish(call, conversation, Call.State.MISSED, "timeout")
            done += 1
    ringing = (
        CallParticipant.objects.filter(
            state=P.RINGING, invited_at__lt=cutoff, call__state=Call.State.ACTIVE
        )
        .values_list("call_id", "call__conversation_id")
        .distinct()[:SWEEP_BATCH]
    )
    for call_id, conversation_id in list(ringing):
        with transaction.atomic():
            _lock(conversation_id)
            call = _lock_call(call_id)
            if call.state != Call.State.ACTIVE:
                continue
            late = call.participants.select_for_update().filter(
                state=P.RINGING, invited_at__lt=cutoff
            )
            missed = _ids(late.values_list("account_id", flat=True))
            if not missed:
                continue
            late.update(state=P.MISSED, left_at=now)
            _emit(
                "call.missed",
                call,
                initiator=str(call.initiator_id),
                missed=missed,
                final=False,
                reason="timeout",
                recipients=missed,
            )
            done += 1
    LiveKitWebhookEvent.objects.filter(received_at__lt=now - WEBHOOK_KEEP).delete()
    return done


def reconcile_live(now: datetime | None = None) -> int:
    """Active calls quiet for a while are checked against LiveKit; an empty or
    missing room ends the call (a lost webhook must not leave it open forever)."""
    if not livekit.enabled():
        return 0
    now = now or timezone.now()
    quiet = now - timedelta(seconds=settings.CALL_RECONCILE_AFTER_SECONDS)
    ended = 0
    for call in list(Call.objects.filter(state=Call.State.ACTIVE, updated_at__lt=quiet)[:50]):
        try:
            identities = livekit.room_identities(call.room)
        except livekit.LiveKitUnavailable:
            return ended
        with transaction.atomic():
            conversation = _lock(call.conversation_id)
            locked = _lock_call(call.id)
            if locked.state != Call.State.ACTIVE or locked.updated_at >= quiet:
                continue
            if identities:
                locked.save(update_fields=["updated_at"])  # alive: look again later
                continue
            _finish(locked, conversation, Call.State.ENDED, "lost")
            ended += 1
    return ended


# ---- LiveKit webhooks ----------------------------------------------------------------------

HANDLED_WEBHOOKS = ("participant_joined", "participant_left", "room_finished")


def _account(identity: str) -> str | None:
    try:
        return str(uuid.UUID(str(identity)))
    except ValueError:
        return None


def _event_time(event) -> datetime:
    seconds = int(getattr(event, "created_at", 0) or 0)
    return datetime.fromtimestamp(seconds, UTC) if seconds > 0 else timezone.now()


def _may_be_in_room(
    call: Call, conversation: Conversation, account: str | None, participant
) -> bool:
    if account is None or participant is None or participant.state != P.ACCEPTED:
        return False
    if not call.is_live:
        return False
    if not conversation.members.filter(account_id=account, left_at__isnull=True).exists():
        return False
    return not (conversation.type in PAIR_TYPES and _pair_blocked(conversation, account))


def apply_webhook(event) -> str:
    """Apply one verified LiveKit webhook. Replays (same event id) are no-ops.

    ``participant_joined`` from someone who may not be there (removed, blocked,
    left, or the call is over: a token can outlive its seat by up to 10 minutes)
    gets them removed again through the server API.
    """
    kind = event.event
    if kind not in HANDLED_WEBHOOKS:
        return "ignored"
    room = event.room.name
    identity = event.participant.identity if kind != "room_finished" else ""
    event_id = (event.id or f"{kind}:{room}:{identity}:{event.created_at}")[:64]
    with transaction.atomic():
        try:
            with transaction.atomic():
                LiveKitWebhookEvent.objects.create(event_id=event_id, event=kind[:32])
        except IntegrityError:
            return "duplicate"
        found = Call.objects.filter(room=room).values_list("id", "conversation_id").first()
        if found is None:
            return "unknown_room"
        conversation = _lock(found[1])
        call = _lock_call(found[0])
        if kind == "room_finished":
            if call.is_live:
                _finish(call, conversation, live_end_state(call), live_end_reason(call))
            return "ok"
        account = _account(identity)
        participant = (
            call.participants.select_for_update().filter(account_id=account).first()
            if account
            else None
        )
        at = _event_time(event)
        if kind == "participant_joined":
            if not _may_be_in_room(call, conversation, account, participant):
                _after_commit("kick", call.room, str(identity))
                return "kicked"
            if participant.room_joined_at is None or at >= participant.room_joined_at:
                participant.room_joined_at = at
                participant.save()
            call.save()  # touches updated_at for the reconcile job
            return "ok"
        # participant_left
        if participant is None:
            return "ok"
        if participant.room_left_at is None or at >= participant.room_left_at:
            participant.room_left_at = at
            participant.save()
        if call.is_live and participant.state == P.ACCEPTED and not participant.in_room:
            if conversation.type == Conversation.Type.GROUP:
                _leave(call, conversation, participant, "left", kick=False)
            else:
                _hang_up(call, conversation, participant, "left")
        return "ok"
