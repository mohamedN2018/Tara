"""Chat business logic. Object-level rule: only active members touch a conversation."""

from __future__ import annotations

import uuid

from django.db import transaction
from django.db.models import Prefetch, Q
from django.db.models.functions import Coalesce
from django.utils import timezone

from tara_common.exceptions import Conflict, TaraAPIError

from . import events
from .models import (
    MESSAGE_REACTION_TYPES,
    BlockedPair,
    Conversation,
    ConversationMember,
    Message,
    MessageAttachment,
    MessageReaction,
    PinnedMessage,
)


def _dm_key(a: str, b: str) -> str:
    x, y = sorted([str(uuid.UUID(str(a))), str(uuid.UUID(str(b)))])
    return f"{x}:{y}"


def is_blocked(a: str, b: str) -> bool:
    return BlockedPair.objects.filter(
        Q(blocker_id=a, blocked_id=b) | Q(blocker_id=b, blocked_id=a)
    ).exists()


def member_ids(conversation: Conversation) -> list[str]:
    return [
        str(m)
        for m in conversation.members.filter(left_at__isnull=True).values_list(
            "account_id", flat=True
        )
    ]


def require_member(account_id: str, conversation_id: str) -> ConversationMember:
    member = (
        ConversationMember.objects.select_related("conversation")
        .filter(conversation_id=conversation_id, account_id=account_id, left_at__isnull=True)
        .first()
    )
    if member is None:
        # Don't disclose conversations the caller isn't part of.
        raise TaraAPIError("Conversation not found.", code="not_found", http_status_code=404)
    return member


# ---- conversations ----------------------------------------------------------


def create_or_get_dm(actor_id: str, other_id: str) -> Conversation:
    if str(actor_id) == str(other_id):
        raise TaraAPIError("Cannot DM yourself.", code="validation_error", http_status_code=400)
    if is_blocked(actor_id, other_id):
        raise TaraAPIError("Action not allowed.", code="permission_denied", http_status_code=403)
    key = _dm_key(actor_id, other_id)
    existing = Conversation.objects.filter(dm_key=key).first()
    if existing:
        return existing
    with transaction.atomic():
        conversation = Conversation.objects.create(
            type=Conversation.Type.DM, created_by=actor_id, dm_key=key
        )
        ConversationMember.objects.bulk_create(
            [
                ConversationMember(conversation=conversation, account_id=actor_id),
                ConversationMember(conversation=conversation, account_id=other_id),
            ]
        )
    return conversation


def create_marketplace_conversation(buyer_id: str, seller_id: str, listing_id: str) -> Conversation:
    """Create (idempotently) a buyer↔seller conversation for a listing.

    Driven by the `marketplace.contact.requested` event (doc 01 §2.10). Keyed so
    repeated contact requests reuse the same thread.
    """
    if is_blocked(buyer_id, seller_id):
        raise TaraAPIError("Action not allowed.", code="permission_denied", http_status_code=403)
    if str(buyer_id) == str(seller_id):
        return None  # nothing to do
    key = f"mkt:{listing_id}:{buyer_id}:{seller_id}"
    existing = Conversation.objects.filter(dm_key=key).first()
    if existing:
        return existing
    with transaction.atomic():
        conversation = Conversation.objects.create(
            type=Conversation.Type.MARKETPLACE,
            created_by=buyer_id,
            listing_id=listing_id,
            dm_key=key,
        )
        ConversationMember.objects.bulk_create(
            [
                ConversationMember(conversation=conversation, account_id=buyer_id),
                ConversationMember(conversation=conversation, account_id=seller_id),
            ]
        )
    return conversation


def create_group(actor_id: str, member_account_ids: list[str], title: str = "") -> Conversation:
    if any(is_blocked(actor_id, mid) for mid in member_account_ids):
        raise TaraAPIError("Action not allowed.", code="permission_denied", http_status_code=403)
    with transaction.atomic():
        conversation = Conversation.objects.create(
            type=Conversation.Type.GROUP, created_by=actor_id, title=title
        )
        members = {str(actor_id): ConversationMember.Role.ADMIN}
        for mid in member_account_ids:
            members.setdefault(str(mid), ConversationMember.Role.MEMBER)
        ConversationMember.objects.bulk_create(
            [
                ConversationMember(conversation=conversation, account_id=mid, role=role)
                for mid, role in members.items()
            ]
        )
        events.emit(
            "conversation.member.changed",
            subject_id=str(conversation.id),
            payload={"action": "created", "members": list(members)},
            actor_id=str(actor_id),
            partition_key=f"conversation:{conversation.id}",
        )
    return conversation


def with_members(queryset):
    """Load active members up front; the serializer reads ``active_members``."""
    return queryset.prefetch_related(
        Prefetch(
            "members",
            queryset=ConversationMember.objects.filter(left_at__isnull=True).order_by("joined_at"),
            to_attr="active_members",
        )
    )


def list_conversations(account_id: str):
    """The inbox, most recent activity first. A thread with no messages yet sorts
    by creation time: the cursor position cannot be null."""
    conv_ids = ConversationMember.objects.filter(
        account_id=account_id, left_at__isnull=True
    ).values("conversation_id")
    return with_members(
        Conversation.objects.filter(id__in=conv_ids)
        .annotate(activity_at=Coalesce("last_message_at", "created_at"))
        .order_by("-activity_at", "-id")
    )


# ---- messages ---------------------------------------------------------------


def send_message(
    actor_id: str,
    conversation_id: str,
    *,
    body: str = "",
    message_type: str = Message.Type.TEXT,
    reply_to_id: str | None = None,
    attachments: list[dict] | None = None,
) -> Message:
    require_member(actor_id, conversation_id)
    conversation = Conversation.objects.get(id=conversation_id)

    if (
        reply_to_id
        and not Message.objects.filter(
            id=reply_to_id, conversation_id=conversation_id, deleted_at__isnull=True
        ).exists()
    ):
        raise TaraAPIError(
            "The message being replied to was not found.",
            code="validation_error",
            http_status_code=400,
        )

    if conversation.type in (Conversation.Type.DM, Conversation.Type.MARKETPLACE):
        others = [m for m in member_ids(conversation) if m != str(actor_id)]
        if others and is_blocked(actor_id, others[0]):
            raise TaraAPIError(
                "Action not allowed.", code="permission_denied", http_status_code=403
            )

    if not body and not attachments:
        raise TaraAPIError("Message is empty.", code="validation_error", http_status_code=400)

    with transaction.atomic():
        message = Message.objects.create(
            conversation=conversation,
            sender_id=actor_id,
            type=message_type,
            body=body,
            reply_to_id=reply_to_id,
        )
        for att in attachments or []:
            MessageAttachment.objects.create(
                message=message,
                media_id=att["media_id"],
                kind=att.get("kind", "file"),
                duration_ms=att.get("duration_ms"),
            )
        conversation.last_message_at = message.created_at
        conversation.save(update_fields=["last_message_at"])
        events.emit(
            "message.created",
            subject_id=str(message.id),
            payload={
                "conversation_id": str(conversation.id),
                "message_id": str(message.id),
                "sender": str(actor_id),
                "type": message_type,
                "recipients": member_ids(conversation),
                "preview": body[:140],
            },
            actor_id=str(actor_id),
            partition_key=f"conversation:{conversation.id}",
        )
    return message


def remove_message(message_id: str) -> None:
    """A moderator removed this message."""
    Message.objects.filter(id=message_id, deleted_at__isnull=True).update(deleted_at=timezone.now())


def list_messages(actor_id: str, conversation_id: str):
    require_member(actor_id, conversation_id)
    return (
        Message.objects.filter(conversation_id=conversation_id, deleted_at__isnull=True)
        .prefetch_related("attachments")
        .order_by("-created_at")
    )


def react_message(actor_id: str, message_id: str, reaction_type: str) -> MessageReaction:
    if reaction_type not in MESSAGE_REACTION_TYPES:
        raise TaraAPIError("Invalid reaction.", code="validation_error", http_status_code=400)
    message = Message.objects.select_related("conversation").filter(id=message_id).first()
    if message is None:
        raise TaraAPIError("Message not found.", code="not_found", http_status_code=404)
    require_member(actor_id, str(message.conversation_id))
    reaction, _ = MessageReaction.objects.update_or_create(
        message=message, account_id=actor_id, defaults={"type": reaction_type}
    )
    events.emit(
        "message.reacted",
        subject_id=str(message.id),
        payload={
            "conversation_id": str(message.conversation_id),
            "message_id": str(message.id),
            "reactor": str(actor_id),
            "type": reaction_type,
            "recipients": member_ids(message.conversation),
        },
        actor_id=str(actor_id),
        partition_key=f"conversation:{message.conversation_id}",
    )
    return reaction


def mark_read(actor_id: str, conversation_id: str, up_to_message_id: str) -> None:
    member = require_member(actor_id, conversation_id)
    if not Message.objects.filter(id=up_to_message_id, conversation_id=conversation_id).exists():
        raise TaraAPIError("Message not found.", code="not_found", http_status_code=404)
    member.last_read_message_id = up_to_message_id
    member.save(update_fields=["last_read_message_id"])
    events.emit(
        "message.read",
        subject_id=str(conversation_id),
        payload={
            "conversation_id": str(conversation_id),
            "reader": str(actor_id),
            "up_to_message_id": str(up_to_message_id),
            "recipients": member_ids(member.conversation),
        },
        actor_id=str(actor_id),
        partition_key=f"conversation:{conversation_id}",
    )


def set_mute(actor_id: str, conversation_id: str, until) -> None:
    member = require_member(actor_id, conversation_id)
    member.muted_until = until
    member.save(update_fields=["muted_until"])


def pin_message(actor_id: str, conversation_id: str, message_id: str) -> PinnedMessage:
    member = require_member(actor_id, conversation_id)
    if (
        member.conversation.type == Conversation.Type.GROUP
        and member.role != ConversationMember.Role.ADMIN
    ):
        raise TaraAPIError(
            "Only admins can pin in groups.", code="permission_denied", http_status_code=403
        )
    if not Message.objects.filter(id=message_id, conversation_id=conversation_id).exists():
        raise TaraAPIError("Message not found.", code="not_found", http_status_code=404)
    pin, created = PinnedMessage.objects.get_or_create(
        conversation_id=conversation_id, message_id=message_id, defaults={"pinned_by": actor_id}
    )
    if not created:
        raise Conflict("Already pinned.", code="conflict")
    return pin
