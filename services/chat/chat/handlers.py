"""Event consumers for the Chat service."""

from __future__ import annotations

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from tara_common.exceptions import TaraAPIError
from tara_events import on_event
from tara_events.envelope import EventEnvelope

from . import services
from .models import (
    BlockedPair,
    Conversation,
    ConversationMember,
    Message,
    MessageAttachment,
    MessageEdit,
    MessageHidden,
    MessageReaction,
)


@on_event("marketplace.contact.requested")
def on_marketplace_contact(event: EventEnvelope) -> None:
    """A buyer contacted a seller -> open (or reuse) their marketplace thread."""
    p = event.payload
    try:
        services.create_marketplace_conversation(
            p["buyer_id"],
            p["seller_id"],
            p["listing_id"],
            title=p.get("title"),
            cover_media_id=p.get("cover_media_id"),
        )
    except TaraAPIError:
        # A blocked pair gets no thread; retrying would only dead-letter the event.
        return


@on_event("listing.updated")
@on_event("listing.status.changed")
def on_listing_changed(event: EventEnvelope) -> None:
    """The listing's threads keep its current title and cover (Marketplace folder)."""
    p = event.payload
    if p.get("listing_id"):
        services.refresh_listing_snapshot(
            p["listing_id"],
            title=p.get("title"),
            cover_media_id=p.get("cover_media_id"),
            status=p.get("status") or p.get("to"),
        )


@on_event("user.blocked")
def on_user_blocked(event: EventEnvelope) -> None:
    p = event.payload
    _, created = BlockedPair.objects.get_or_create(
        blocker_id=p["blocker_id"], blocked_id=p["blocked_id"]
    )
    if created:
        services.revoke_pair_subscriptions(p["blocker_id"], p["blocked_id"])


@on_event("friendship.accepted")
def on_friendship_accepted(event: EventEnvelope) -> None:
    """Friends now: a pending (or declined) message request between them is
    an ordinary conversation. Idempotent: a replay updates nothing."""
    p = event.payload
    a, b = p.get("a"), p.get("b")
    if a and b:
        services.accept_pair_requests(a, b)


@on_event("user.unblocked")
def on_user_unblocked(event: EventEnvelope) -> None:
    p = event.payload
    BlockedPair.objects.filter(blocker_id=p["blocker_id"], blocked_id=p["blocked_id"]).delete()


@on_event("moderation.actioned")
def on_moderation_actioned(event: EventEnvelope) -> None:
    p = event.payload
    if p.get("target_type") != "message":
        return
    if p.get("action") == "remove":
        services.remove_message(p["target_id"])
    elif p.get("action") in ("approve", "restore"):
        # An overturned removal arrives as `approve` (doc 04, moderation.actioned).
        services.restore_message(p["target_id"])


@on_event("account.deleted")
def on_account_deleted(event: EventEnvelope) -> None:
    """Erase what the account said in chat, idempotently (identity 3C).

    Its messages become the same tombstone as "deleted for everyone" (body,
    search copy, attachments and edit history gone; the row keeps its place in
    the sequence so the others' history stays whole). Its reactions and
    per-message hides are deleted, it leaves every group, page and support
    conversation, and its block rows go.

    What remains: its membership row in one-to-one and marketplace
    conversations (the other person's thread needs it; the account has no
    profile any more, so it shows as an unknown user) and its read markers.
    """
    account_id = str(event.payload.get("account_id") or event.subject_id)
    now = timezone.now()
    with transaction.atomic():
        sent = Message.objects.filter(sender_id=account_id)
        MessageAttachment.objects.filter(message__in=sent).delete()
        MessageEdit.objects.filter(message__in=sent).delete()
        sent.update(body="", body_norm="", forwarded_from_message_id=None)
        sent.filter(deleted_at__isnull=True).update(deleted_at=now, deleted_by=account_id)
        MessageReaction.objects.filter(account_id=account_id).delete()
        MessageHidden.objects.filter(account_id=account_id).delete()
        ConversationMember.objects.filter(
            account_id=account_id,
            left_at__isnull=True,
            conversation__type__in=[
                Conversation.Type.GROUP,
                Conversation.Type.PAGE,
                Conversation.Type.SUPPORT,
            ],
        ).update(left_at=now)
        BlockedPair.objects.filter(Q(blocker_id=account_id) | Q(blocked_id=account_id)).delete()
