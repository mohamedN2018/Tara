"""Chat business logic. Object-level rule: only active members touch a conversation.

Visibility of a message to a member (``visible_messages``): not removed by
moderation, not hidden by that member ("delete for me"), and created after the
member's ``cleared_at``. Anything else answers 404, exactly like a message that
does not exist. A message deleted for everyone stays visible as a tombstone.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Exists, F, OuterRef, Prefetch, Q
from django.db.models.functions import Coalesce, Greatest
from django.utils import timezone

from tara_common.exceptions import Conflict, TaraAPIError

from . import events, media_client, text
from .models import (
    MESSAGE_REACTION_TYPES,
    BlockedPair,
    Conversation,
    ConversationMember,
    Message,
    MessageAttachment,
    MessageEdit,
    MessageHidden,
    MessageReaction,
    PinnedMessage,
)

MAX_GROUP_MEMBERS = 256
MAX_ATTACHMENTS = 10
MAX_FORWARD_TARGETS = 5
MIN_SEARCH_CHARS = 2
# Kinds a client may send; `system` and `share` are written by the server only.
CLIENT_MESSAGE_TYPES = {"text", "image", "video", "file", "audio", "voice"}
# Attachment kind -> media kinds it may point at.
ATTACHMENT_MEDIA_KINDS = {
    "image": {"image"},
    "video": {"video"},
    "file": {"file"},
    "audio": {"audio"},
    "voice": {"voice", "audio"},
}
# Shared-media panel filters -> attachment kinds.
MEDIA_PANEL_KINDS = {
    "image": ["image"],
    "video": ["video"],
    "voice": ["voice", "audio"],
    "file": ["file"],
}


def _not_found(what: str = "Message") -> TaraAPIError:
    return TaraAPIError(f"{what} not found.", code="not_found", http_status_code=404)


def _denied(message: str = "Action not allowed.") -> TaraAPIError:
    return TaraAPIError(message, code="permission_denied", http_status_code=403)


def _invalid(message: str) -> TaraAPIError:
    return TaraAPIError(message, code="validation_error", http_status_code=400)


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
    others = {str(m) for m in member_account_ids} - {str(actor_id)}
    if not others:
        raise TaraAPIError(
            "A group needs at least one other member.",
            code="validation_error",
            http_status_code=400,
        )
    if any(is_blocked(actor_id, mid) for mid in others):
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
            payload={
                "conversation_id": str(conversation.id),
                "action": "created",
                "recipients": list(members),
            },
            actor_id=str(actor_id),
            partition_key=f"conversation:{conversation.id}",
        )
    return conversation


def _require_group_admin(actor_id: str, conversation_id: str) -> ConversationMember:
    member = _require_group_member(actor_id, conversation_id)
    if member.role != ConversationMember.Role.ADMIN:
        raise TaraAPIError(
            "Only group admins can do this.", code="permission_denied", http_status_code=403
        )
    return member


def _require_group_member(actor_id: str, conversation_id: str) -> ConversationMember:
    member = require_member(actor_id, conversation_id)
    if member.conversation.type != Conversation.Type.GROUP:
        raise TaraAPIError(
            "Only group conversations have this.", code="validation_error", http_status_code=400
        )
    return member


def _emit_changed(conversation: Conversation, actor_id: str, action: str, extra=()) -> None:
    """Tell members (and anyone just removed) to refresh this conversation."""
    events.emit(
        "conversation.member.changed",
        subject_id=str(conversation.id),
        payload={
            "conversation_id": str(conversation.id),
            "action": action,
            "recipients": sorted({*member_ids(conversation), *(str(e) for e in extra)}),
        },
        actor_id=str(actor_id),
        partition_key=f"conversation:{conversation.id}",
    )


def rename_group(actor_id: str, conversation_id: str, title: str) -> None:
    member = _require_group_admin(actor_id, conversation_id)
    with transaction.atomic():
        Conversation.objects.filter(id=conversation_id).update(title=title)
        _emit_changed(member.conversation, actor_id, "renamed")


def add_members(actor_id: str, conversation_id: str, account_ids: list[str]) -> None:
    member = _require_group_admin(actor_id, conversation_id)
    conversation = member.conversation
    new_ids = {str(a) for a in account_ids} - set(member_ids(conversation))
    if any(is_blocked(actor_id, account) for account in new_ids):
        raise TaraAPIError("Action not allowed.", code="permission_denied", http_status_code=403)
    if len(member_ids(conversation)) + len(new_ids) > MAX_GROUP_MEMBERS:
        raise TaraAPIError("This group is full.", code="validation_error", http_status_code=400)
    with transaction.atomic():
        for account in new_ids:
            # Someone who left comes back as an ordinary member, on the same row.
            ConversationMember.objects.update_or_create(
                conversation=conversation,
                account_id=account,
                defaults={"left_at": None, "role": ConversationMember.Role.MEMBER},
            )
        _emit_changed(conversation, actor_id, "added")


def remove_member(actor_id: str, conversation_id: str, account_id: str) -> None:
    """Admins remove anyone; everyone can leave. The group always keeps an admin."""
    if str(actor_id) == str(account_id):
        member = _require_group_member(actor_id, conversation_id)
    else:
        _require_group_admin(actor_id, conversation_id)
        member = require_member(account_id, conversation_id)
    conversation = member.conversation
    with transaction.atomic():
        member.left_at = timezone.now()
        member.role = ConversationMember.Role.MEMBER
        member.save(update_fields=["left_at", "role"])
        active = conversation.members.filter(left_at__isnull=True)
        if not active.filter(role=ConversationMember.Role.ADMIN).exists():
            successor = active.order_by("joined_at").first()
            if successor:
                successor.role = ConversationMember.Role.ADMIN
                successor.save(update_fields=["role"])
        _emit_changed(conversation, actor_id, "removed", extra=[account_id])


def set_member_role(actor_id: str, conversation_id: str, account_id: str, role: str) -> None:
    member = _require_group_admin(actor_id, conversation_id)
    target = require_member(account_id, conversation_id)
    conversation = member.conversation
    with transaction.atomic():
        target.role = role
        target.save(update_fields=["role"])
        if not conversation.members.filter(
            left_at__isnull=True, role=ConversationMember.Role.ADMIN
        ).exists():
            raise TaraAPIError(
                "A group needs an admin.", code="validation_error", http_status_code=400
            )
        _emit_changed(conversation, actor_id, "role_changed")


def with_state(queryset):
    """Load members and pins up front; the serializer reads these attributes."""
    return queryset.prefetch_related(
        Prefetch(
            "members",
            queryset=ConversationMember.objects.filter(left_at__isnull=True).order_by("joined_at"),
            to_attr="active_members",
        ),
        Prefetch(
            "pins",
            queryset=PinnedMessage.objects.filter(
                message__deleted_at__isnull=True, message__moderation_removed_at__isnull=True
            )
            .select_related("message")
            .order_by("-created_at"),
            to_attr="active_pins",
        ),
    )


def get_conversation(account_id: str, conversation_id: str) -> Conversation:
    require_member(account_id, conversation_id)
    return with_state(Conversation.objects.filter(id=conversation_id)).get()


def list_conversations(account_id: str, *, archived: bool = False):
    """The inbox (or the archived folder), most recent activity first. A thread
    with no messages yet sorts by creation time: the cursor position cannot be null.
    """
    conv_ids = ConversationMember.objects.filter(
        account_id=account_id, left_at__isnull=True, archived_at__isnull=not archived
    ).values("conversation_id")
    return with_state(
        Conversation.objects.filter(id__in=conv_ids)
        .annotate(activity_at=Coalesce("last_message_at", "created_at"))
        .order_by("-activity_at", "-id")
    )


def legacy_unread(member: ConversationMember) -> int:
    """Unread count for a conversation whose messages are not numbered yet."""
    qs = (
        visible_messages(member)
        .filter(deleted_at__isnull=True)
        .exclude(sender_id=member.account_id)
    )
    if member.last_read_message_id:
        pointer = Message.objects.filter(id=member.last_read_message_id).first()
        if pointer is not None:
            qs = qs.filter(created_at__gt=pointer.created_at)
    return qs.count()


def unread_for(member: ConversationMember, conversation: Conversation) -> int:
    if conversation.seq_ready:
        return max(0, conversation.last_seq - member.last_read_seq)
    return legacy_unread(member)


def unread_summary(account_id: str) -> dict:
    """The badge: unread messages and conversations, archived and muted ones left out."""
    now = timezone.now()
    members = (
        ConversationMember.objects.filter(
            account_id=account_id, left_at__isnull=True, archived_at__isnull=True
        )
        .filter(Q(muted_until__isnull=True) | Q(muted_until__lte=now))
        .select_related("conversation")
    )
    ready = members.filter(
        conversation__seq_ready=True, last_read_seq__lt=F("conversation__last_seq")
    ).values_list("conversation__last_seq", "last_read_seq")
    counts = [last - read for last, read in ready]
    for member in members.filter(conversation__seq_ready=False):
        counts.append(legacy_unread(member))
    counts = [c for c in counts if c > 0]
    return {"messages": sum(counts), "conversations": len(counts)}


def set_archived(actor_id: str, conversation_id: str, archived: bool) -> None:
    member = require_member(actor_id, conversation_id)
    member.archived_at = timezone.now() if archived else None
    member.save(update_fields=["archived_at"])


def clear_for_me(actor_id: str, conversation_id: str) -> None:
    """Hide everything sent so far from this member only; nothing is left unread."""
    with transaction.atomic():
        member = require_member(actor_id, conversation_id)
        conversation = Conversation.objects.select_for_update().get(id=conversation_id)
        member.cleared_at = timezone.now()
        member.last_read_seq = max(member.last_read_seq, conversation.last_seq)
        member.last_delivered_seq = max(member.last_delivered_seq, conversation.last_seq)
        member.save(update_fields=["cleared_at", "last_read_seq", "last_delivered_seq"])


def presence_peers(account_id: str) -> list[str]:
    """Who may see this account's presence, from chat's side: its DM peers.

    Group co-members are deliberately left out (roadmap 3.6: shared groups would
    expose people to strangers). Blocked pairs are never peers.
    """
    dm_ids = ConversationMember.objects.filter(
        account_id=account_id, left_at__isnull=True, conversation__type=Conversation.Type.DM
    ).values("conversation_id")
    peers = {
        str(p)
        for p in ConversationMember.objects.filter(conversation_id__in=dm_ids, left_at__isnull=True)
        .exclude(account_id=account_id)
        .values_list("account_id", flat=True)
    }
    blocked = set()
    for blocker, blocked_id in BlockedPair.objects.filter(
        Q(blocker_id=account_id) | Q(blocked_id=account_id)
    ).values_list("blocker_id", "blocked_id"):
        blocked.add(str(blocker))
        blocked.add(str(blocked_id))
    return sorted(peers - blocked)


# ---- messages ---------------------------------------------------------------


def _forbid_if_blocked(conversation: Conversation, actor_id: str) -> None:
    if conversation.type in (Conversation.Type.DM, Conversation.Type.MARKETPLACE):
        others = [m for m in member_ids(conversation) if m != str(actor_id)]
        if others and is_blocked(actor_id, others[0]):
            raise _denied()


def visible_messages(member: ConversationMember):
    """Messages of the member's conversation that this member may see."""
    hidden = MessageHidden.objects.filter(message=OuterRef("pk"), account_id=member.account_id)
    qs = Message.objects.filter(
        conversation_id=member.conversation_id, moderation_removed_at__isnull=True
    ).filter(~Exists(hidden))
    if member.cleared_at:
        qs = qs.filter(created_at__gt=member.cleared_at)
    return qs


def get_visible_message(actor_id: str, message_id: str) -> tuple[Message, ConversationMember]:
    """The message and the caller's membership, or 404 when the caller cannot see it."""
    message = Message.objects.select_related("conversation").filter(id=message_id).first()
    if message is None:
        raise _not_found()
    member = (
        ConversationMember.objects.filter(
            conversation_id=message.conversation_id, account_id=actor_id, left_at__isnull=True
        )
        .select_related("conversation")
        .first()
    )
    if member is None or not visible_messages(member).filter(id=message.id).exists():
        raise _not_found()
    return message, member


def _clean_name(name: str | None) -> str:
    """A display label only: never used in a header or a storage key."""
    name = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    return "".join(ch for ch in name if ch.isprintable()).strip()[:200]


def _validate_attachments(sender_id: str, items: list[dict]) -> list[dict]:
    """Check every attachment with media: the sender's own private upload, of the
    right kind, finished uploading and within chat's size cap. Fails closed (503)
    when media cannot answer."""
    if len(items) > MAX_ATTACHMENTS:
        raise _invalid(f"A message can have at most {MAX_ATTACHMENTS} attachments.")
    if not items:
        return []
    ids = [str(i["media_id"]) for i in items]
    if len(set(ids)) != len(ids):
        raise _invalid("An attachment is listed twice.")
    for item in items:
        if (item.get("kind") or "file") not in ATTACHMENT_MEDIA_KINDS:
            raise _invalid("Unsupported attachment kind.")
    found = media_client.lookup(ids)
    caps = settings.CHAT_ATTACHMENT_MAX_BYTES
    resolved = []
    for position, item in enumerate(items):
        kind = item.get("kind") or "file"
        info = found.get(str(item["media_id"]))
        # Someone else's upload looks exactly like one that does not exist.
        if info is None or info.owner_id != str(sender_id):
            raise _invalid("Attachment not found.")
        if info.kind not in ATTACHMENT_MEDIA_KINDS[kind]:
            raise _invalid("The attachment kind does not match the upload.")
        if info.status not in ("processing", "ready"):
            raise _invalid("The attachment has not finished uploading.")
        if info.visibility != "private":
            raise _invalid("Chat attachments must be uploaded as private.")
        if caps.get(kind) and info.bytes > caps[kind]:
            raise _invalid("The attachment is too large.")
        resolved.append(
            {
                "media_id": info.id,
                "kind": kind,
                "duration_ms": item.get("duration_ms"),
                "mime": info.mime,
                "bytes": info.bytes,
                "file_name": _clean_name(item.get("file_name")),
                "position": position,
            }
        )
    return resolved


def _message_type(attachments: list[dict]) -> str:
    """Derived on the server: what the client claims is never trusted."""
    if not attachments:
        return Message.Type.TEXT
    kinds = {a["kind"] for a in attachments}
    return kinds.pop() if len(kinds) == 1 else Message.Type.FILE


def _receipt_recipients(
    conversation: Conversation, actor_id: str, old_seq: int, new_seq: int
) -> list[str]:
    """Who hears about a read/delivered pointer move.

    A DM tells both sides. A group tells only the reader (other tabs) and the
    senders of the messages the pointer passed, so receipts do not fan out to
    every member for every read (roadmap 3.4).
    """
    if conversation.type != Conversation.Type.GROUP:
        return member_ids(conversation)
    senders = {
        str(s)
        for s in Message.objects.filter(
            conversation=conversation, seq__gt=old_seq, seq__lte=new_seq
        )
        .exclude(sender_id=actor_id)
        .values_list("sender_id", flat=True)
        .distinct()
    }
    return sorted({str(actor_id)} | (senders & set(member_ids(conversation))))


def _after_send(conversation: Conversation, message: Message, actor_id: str) -> None:
    now = timezone.now()
    mine = {"archived_at": None, "last_read_message_id": message.id, "last_read_at": now}
    if message.seq is not None:
        # Sending reads everything before it.
        mine["last_read_seq"] = Greatest(F("last_read_seq"), message.seq)
        mine["last_delivered_seq"] = Greatest(F("last_delivered_seq"), message.seq)
    ConversationMember.objects.filter(conversation=conversation, account_id=actor_id).update(**mine)
    # A new message brings an archived thread back to the inbox, unless the
    # member muted it: muting is how you say "keep this out of my way".
    ConversationMember.objects.filter(
        conversation=conversation, left_at__isnull=True, archived_at__isnull=False
    ).exclude(account_id=actor_id).filter(
        Q(muted_until__isnull=True) | Q(muted_until__lte=now)
    ).update(archived_at=None)


def _record_message(
    conversation_id: str,
    actor_id: str,
    *,
    body: str,
    message_type: str,
    reply_to_id: str | None = None,
    attachments: list[dict] = (),
    forwarded_from: str | None = None,
) -> Message:
    """Write a message under the conversation row lock and tell the members.

    The lock makes ``seq`` gap-free and unique per conversation (doc 05 §7.3).
    The caller has already checked membership, blocks and attachments.
    """
    with transaction.atomic():
        conversation = Conversation.objects.select_for_update().get(id=conversation_id)
        seq = conversation.last_seq + 1 if conversation.seq_ready else None
        message = Message.objects.create(
            conversation=conversation,
            sender_id=actor_id,
            type=message_type,
            body=body,
            body_norm=text.normalize(body),
            seq=seq,
            reply_to_id=reply_to_id,
            forwarded_from_message_id=forwarded_from,
        )
        MessageAttachment.objects.bulk_create(
            [
                MessageAttachment(
                    message=message,
                    media_id=a["media_id"],
                    kind=a["kind"],
                    duration_ms=a.get("duration_ms"),
                    mime=a.get("mime") or "",
                    bytes=a.get("bytes"),
                    file_name=a.get("file_name") or "",
                    position=a.get("position", i),
                )
                for i, a in enumerate(attachments)
            ]
        )
        conversation.last_message_at = message.created_at
        fields = ["last_message_at"]
        if seq is not None:
            conversation.last_seq = seq
            fields.append("last_seq")
        conversation.save(update_fields=fields)
        _after_send(conversation, message, actor_id)
        events.emit(
            "message.created",
            subject_id=str(message.id),
            payload={
                "conversation_id": str(conversation.id),
                "message_id": str(message.id),
                "sender": str(actor_id),
                "type": message_type,
                "seq": seq,
                "recipients": member_ids(conversation),
                "muted": _muted_ids(conversation),
                "preview": body[:140],
            },
            actor_id=str(actor_id),
            partition_key=f"conversation:{conversation.id}",
        )
    return message


def send_message(
    actor_id: str,
    conversation_id: str,
    *,
    body: str = "",
    message_type: str = Message.Type.TEXT,
    reply_to_id: str | None = None,
    attachments: list[dict] | None = None,
) -> Message:
    member = require_member(actor_id, conversation_id)
    conversation = member.conversation
    if message_type not in CLIENT_MESSAGE_TYPES:
        raise _invalid("This message type cannot be sent.")
    if (
        reply_to_id
        and not visible_messages(member).filter(id=reply_to_id, deleted_at__isnull=True).exists()
    ):
        raise _invalid("The message being replied to was not found.")

    _forbid_if_blocked(conversation, actor_id)

    if not body and not attachments:
        raise _invalid("Message is empty.")
    resolved = _validate_attachments(actor_id, attachments or [])
    return _record_message(
        conversation_id,
        actor_id,
        body=body,
        message_type=_message_type(resolved),
        reply_to_id=reply_to_id,
        attachments=resolved,
    )


def _muted_ids(conversation: Conversation) -> list[str]:
    """Members who should get the message but no alert."""
    return [
        str(m)
        for m in conversation.members.filter(
            left_at__isnull=True, muted_until__gt=timezone.now()
        ).values_list("account_id", flat=True)
    ]


def _emit_message_event(event_type: str, message: Message, actor_id: str | None, **extra) -> None:
    events.emit(
        event_type,
        subject_id=str(message.id),
        payload={
            "conversation_id": str(message.conversation_id),
            "message_id": str(message.id),
            "recipients": member_ids(message.conversation),
            **extra,
        },
        actor_id=str(actor_id) if actor_id else None,
        partition_key=f"conversation:{message.conversation_id}",
    )


def _wipe(message: Message, deleted_by: str) -> None:
    """Delete for everyone: a tombstone stays, every copy of the content goes."""
    message.deleted_at = timezone.now()
    message.deleted_by = deleted_by
    message.body = ""
    message.body_norm = ""
    message.save(update_fields=["deleted_at", "deleted_by", "body", "body_norm"])
    message.attachments.all().delete()
    message.reactions.all().delete()
    message.edits.all().delete()
    PinnedMessage.objects.filter(message=message).delete()


def remove_message(message_id: str) -> None:
    """A moderator removed this message. Reversible (``restore_message``)."""
    message = (
        Message.objects.select_related("conversation")
        .filter(id=message_id, moderation_removed_at__isnull=True)
        .first()
    )
    if message is None:
        return
    with transaction.atomic():
        message.moderation_removed_at = timezone.now()
        message.save(update_fields=["moderation_removed_at"])
        _emit_message_event("message.deleted", message, None, scope="moderation")


def restore_message(message_id: str) -> None:
    """Moderation reversed its removal (an upheld appeal)."""
    Message.objects.filter(id=message_id).update(moderation_removed_at=None)


def list_messages(actor_id: str, conversation_id: str):
    member = require_member(actor_id, conversation_id)
    return _with_message_state(visible_messages(member)).order_by("-created_at")


def _with_message_state(queryset):
    return queryset.select_related("reply_to").prefetch_related("attachments", "reactions")


def get_message(actor_id: str, message_id: str) -> Message:
    message, _ = get_visible_message(actor_id, message_id)
    return _with_message_state(Message.objects.filter(id=message.id)).get()


def edit_message(actor_id: str, message_id: str, body: str) -> Message:
    message, member = get_visible_message(actor_id, message_id)
    if str(message.sender_id) != str(actor_id):
        raise _denied("Only the sender can edit a message.")
    if message.deleted_at:
        raise Conflict("This message was deleted.", code="conflict")
    if message.type == Message.Type.SYSTEM or message.forwarded_from_message_id:
        raise _denied("This message cannot be edited.")
    window = timedelta(seconds=settings.CHAT_EDIT_WINDOW_SECONDS)
    if timezone.now() - message.created_at > window:
        raise TaraAPIError(
            "Messages can only be edited shortly after sending.",
            code="edit_window_expired",
            http_status_code=403,
        )
    _forbid_if_blocked(member.conversation, actor_id)
    if not body and not message.attachments.exists():
        raise _invalid("Message is empty.")
    if body != message.body:
        with transaction.atomic():
            MessageEdit.objects.create(message=message, previous_body=message.body)
            message.body = body
            message.body_norm = text.normalize(body)
            message.edited_at = timezone.now()
            message.save(update_fields=["body", "body_norm", "edited_at"])
            _emit_message_event("message.edited", message, actor_id, editor=str(actor_id))
    return get_message(actor_id, message_id)


def hide_for_me(actor_id: str, message_id: str) -> None:
    message, _ = get_visible_message(actor_id, message_id)
    MessageHidden.objects.get_or_create(message=message, account_id=actor_id)


def delete_for_everyone(actor_id: str, message_id: str) -> None:
    message, _ = get_visible_message(actor_id, message_id)
    if str(message.sender_id) != str(actor_id):
        raise _denied("Only the sender can delete a message for everyone.")
    if message.deleted_at:
        return
    window = timedelta(seconds=settings.CHAT_DELETE_WINDOW_SECONDS)
    if timezone.now() - message.created_at > window:
        raise TaraAPIError(
            "This message can no longer be deleted for everyone.",
            code="delete_window_expired",
            http_status_code=403,
        )
    with transaction.atomic():
        _wipe(message, deleted_by=actor_id)
        _emit_message_event("message.deleted", message, actor_id, scope="everyone")


def forward_message(actor_id: str, message_id: str, conversation_ids: list[str]) -> list[Message]:
    """Copy a message into other conversations the caller can post in.

    Attachments are copied by reference (the same media ids): chat mints URLs
    per conversation after its own membership check, so the copy is readable in
    the target without re-uploading. Every target is checked before any write.
    """
    source, _ = get_visible_message(actor_id, message_id)
    if source.deleted_at or source.type == Message.Type.SYSTEM:
        raise _invalid("This message cannot be forwarded.")
    targets = list(dict.fromkeys(str(c) for c in conversation_ids))
    if not targets or len(targets) > MAX_FORWARD_TARGETS:
        raise _invalid(f"Forward to between 1 and {MAX_FORWARD_TARGETS} conversations.")
    for conversation_id in targets:
        member = require_member(actor_id, conversation_id)
        _forbid_if_blocked(member.conversation, actor_id)
    attachments = [
        {
            "media_id": a.media_id,
            "kind": a.kind,
            "duration_ms": a.duration_ms,
            "mime": a.mime,
            "bytes": a.bytes,
            "file_name": a.file_name,
            "position": a.position,
        }
        for a in source.attachments.order_by("position", "id")
    ]
    message_type = source.type if source.type in CLIENT_MESSAGE_TYPES else Message.Type.TEXT
    return [
        _record_message(
            conversation_id,
            actor_id,
            body=source.body,
            message_type=message_type,
            attachments=attachments,
            forwarded_from=str(source.id),
        )
        for conversation_id in targets
    ]


# ---- search and shared media ------------------------------------------------


def _search_term(query: str) -> str:
    term = text.normalize(query)[:100]
    if len(term) < MIN_SEARCH_CHARS:
        raise _invalid(f"Search for at least {MIN_SEARCH_CHARS} characters.")
    return term


def search_conversation(actor_id: str, conversation_id: str, query: str):
    member = require_member(actor_id, conversation_id)
    term = _search_term(query)
    return _with_message_state(
        visible_messages(member).filter(deleted_at__isnull=True, body_norm__contains=term)
    ).order_by("-created_at")


def search_messages(actor_id: str, query: str):
    """Messages the caller can see, across every conversation they belong to."""
    term = _search_term(query)
    mine = ConversationMember.objects.filter(account_id=actor_id, left_at__isnull=True)
    still_visible = mine.filter(conversation_id=OuterRef("conversation_id")).filter(
        Q(cleared_at__isnull=True) | Q(cleared_at__lt=OuterRef("created_at"))
    )
    hidden = MessageHidden.objects.filter(message=OuterRef("pk"), account_id=actor_id)
    return _with_message_state(
        Message.objects.filter(
            conversation_id__in=mine.values("conversation_id"),
            moderation_removed_at__isnull=True,
            deleted_at__isnull=True,
            body_norm__contains=term,
        ).filter(Exists(still_visible), ~Exists(hidden))
    ).order_by("-created_at")


def shared_media(actor_id: str, conversation_id: str, kind: str | None = None):
    member = require_member(actor_id, conversation_id)
    if kind and kind not in MEDIA_PANEL_KINDS:
        raise _invalid("Unknown media kind.")
    kinds = MEDIA_PANEL_KINDS[kind] if kind else sum(MEDIA_PANEL_KINDS.values(), [])
    shown = visible_messages(member).filter(deleted_at__isnull=True)
    # uuid7 ids grow with time, so "-id" is newest first and a stable cursor.
    return (
        MessageAttachment.objects.filter(message__in=shown, kind__in=kinds)
        .select_related("message")
        .order_by("-id")
    )


def attachment_url(actor_id: str, message_id: str, media_id: str) -> dict:
    """A presigned URL for one attachment, after the membership and visibility check."""
    message, _ = get_visible_message(actor_id, message_id)
    attachment = (
        message.attachments.filter(media_id=media_id).first() if not message.deleted_at else None
    )
    if attachment is None:
        raise _not_found("Attachment")
    try:
        asset = media_client.signed(str(attachment.media_id))
    except media_client.MediaNotFound as exc:
        raise _not_found("Attachment") from exc
    thumb = next(
        (v.get("url") for v in asset.get("variants") or [] if v.get("kind") == "thumb"), None
    )
    return {
        "media_id": str(attachment.media_id),
        "message_id": str(message.id),
        "kind": attachment.kind,
        "mime": asset.get("mime") or attachment.mime,
        "status": asset.get("status"),
        "url": asset.get("url"),
        "thumb_url": thumb,
        "file_name": attachment.file_name,
        "bytes": attachment.bytes,
        "duration_ms": attachment.duration_ms,
    }


# ---- reactions --------------------------------------------------------------


def react_message(actor_id: str, message_id: str, reaction_type: str) -> MessageReaction:
    if reaction_type not in MESSAGE_REACTION_TYPES:
        raise _invalid("Invalid reaction.")
    message = _reactable_message(actor_id, message_id)
    with transaction.atomic():
        reaction, _ = MessageReaction.objects.update_or_create(
            message=message, account_id=actor_id, defaults={"type": reaction_type}
        )
        _emit_reacted(message, actor_id, reaction_type)
    return reaction


def unreact_message(actor_id: str, message_id: str) -> None:
    message = _reactable_message(actor_id, message_id)
    with transaction.atomic():
        deleted, _ = MessageReaction.objects.filter(message=message, account_id=actor_id).delete()
        if deleted:
            _emit_reacted(message, actor_id, None)


def _reactable_message(actor_id: str, message_id: str) -> Message:
    message, member = get_visible_message(actor_id, message_id)
    if message.deleted_at:
        raise Conflict("This message was deleted.", code="conflict")
    _forbid_if_blocked(member.conversation, actor_id)
    return message


def _emit_reacted(message: Message, actor_id: str, reaction_type: str | None) -> None:
    """``type`` is null when the reaction was removed."""
    _emit_message_event(
        "message.reacted", message, actor_id, reactor=str(actor_id), type=reaction_type
    )


# ---- read and delivery state -------------------------------------------------


def mark_read(actor_id: str, conversation_id: str, up_to_message_id: str) -> None:
    """Move the caller's read pointer forward to a message they can see.

    Pointers never move backwards: a stale or replayed request changes nothing
    and emits nothing.
    """
    member = require_member(actor_id, conversation_id)
    message = visible_messages(member).filter(id=up_to_message_id).first()
    if message is None:
        raise _not_found()
    conversation = member.conversation
    now = timezone.now()
    with transaction.atomic():
        if message.seq is not None:
            moved = ConversationMember.objects.filter(
                pk=member.pk, last_read_seq__lt=message.seq
            ).update(
                last_read_seq=message.seq,
                last_delivered_seq=Greatest(F("last_delivered_seq"), message.seq),
                last_read_message_id=message.id,
                last_read_at=now,
            )
            if not moved:
                return
            recipients = _receipt_recipients(
                conversation, actor_id, member.last_read_seq, message.seq
            )
        else:
            current = (
                Message.objects.filter(id=member.last_read_message_id).first()
                if member.last_read_message_id
                else None
            )
            if current and (current.created_at, str(current.id)) >= (
                message.created_at,
                str(message.id),
            ):
                return
            member.last_read_message_id = message.id
            member.last_read_at = now
            member.save(update_fields=["last_read_message_id", "last_read_at"])
            recipients = member_ids(conversation)
        events.emit(
            "message.read",
            subject_id=str(conversation_id),
            payload={
                "conversation_id": str(conversation_id),
                "reader": str(actor_id),
                "up_to_message_id": str(message.id),
                "up_to_seq": message.seq,
                "recipients": recipients,
            },
            actor_id=str(actor_id),
            partition_key=f"conversation:{conversation_id}",
        )


MAX_DELIVERED_PER_CALL = 100


def mark_delivered(actor_id: str) -> int:
    """Everything that reached the caller's device so far is delivered.

    Called by the client when the inbox loads and when a message arrives over
    the socket. Returns how many conversations moved.
    """
    pending = list(
        ConversationMember.objects.filter(
            account_id=actor_id,
            left_at__isnull=True,
            conversation__seq_ready=True,
            last_delivered_seq__lt=F("conversation__last_seq"),
        ).select_related("conversation")[:MAX_DELIVERED_PER_CALL]
    )
    moved_count = 0
    for member in pending:
        conversation = member.conversation
        new_seq = conversation.last_seq
        with transaction.atomic():
            moved = ConversationMember.objects.filter(
                pk=member.pk, last_delivered_seq__lt=new_seq
            ).update(last_delivered_seq=new_seq)
            if not moved:
                continue
            moved_count += 1
            events.emit(
                "message.delivered",
                subject_id=str(conversation.id),
                payload={
                    "conversation_id": str(conversation.id),
                    "account": str(actor_id),
                    "up_to_seq": new_seq,
                    "recipients": _receipt_recipients(
                        conversation, actor_id, member.last_delivered_seq, new_seq
                    ),
                },
                actor_id=str(actor_id),
                partition_key=f"conversation:{conversation.id}",
            )
    return moved_count


def backfill_conversation_seq(conversation_id: str) -> bool:
    """Number one conversation's messages under the row lock new sends also take.

    Sends wait for the lock, so no message can be written between numbering and
    ``seq_ready=true`` (doc 05 §7.3). Returns False when there was nothing to do.
    """
    with transaction.atomic():
        conversation = Conversation.objects.select_for_update().get(id=conversation_id)
        if conversation.seq_ready:
            return False
        ids = list(
            Message.objects.filter(conversation=conversation)
            .order_by("created_at", "id")
            .values_list("id", flat=True)
        )
        Message.objects.filter(conversation=conversation).update(seq=None)
        seq_by_id = {message_id: n for n, message_id in enumerate(ids, start=1)}
        Message.objects.bulk_update(
            [Message(id=message_id, seq=n) for message_id, n in seq_by_id.items()],
            ["seq"],
            batch_size=1000,
        )
        for member in conversation.members.all():
            read = seq_by_id.get(member.last_read_message_id, 0)
            member.last_read_seq = max(member.last_read_seq, read)
            member.last_delivered_seq = max(member.last_delivered_seq, member.last_read_seq)
            member.save(update_fields=["last_read_seq", "last_delivered_seq"])
        conversation.last_seq = len(ids)
        conversation.seq_ready = True
        conversation.save(update_fields=["last_seq", "seq_ready"])
    return True


def set_mute(actor_id: str, conversation_id: str, until) -> None:
    member = require_member(actor_id, conversation_id)
    member.muted_until = until
    member.save(update_fields=["muted_until"])


def _require_pin_rights(actor_id: str, conversation_id: str) -> ConversationMember:
    member = require_member(actor_id, conversation_id)
    if (
        member.conversation.type == Conversation.Type.GROUP
        and member.role != ConversationMember.Role.ADMIN
    ):
        raise TaraAPIError(
            "Only admins can pin in groups.", code="permission_denied", http_status_code=403
        )
    return member


def pin_message(actor_id: str, conversation_id: str, message_id: str) -> PinnedMessage:
    member = _require_pin_rights(actor_id, conversation_id)
    if not visible_messages(member).filter(id=message_id, deleted_at__isnull=True).exists():
        raise _not_found()
    with transaction.atomic():
        pin, created = PinnedMessage.objects.get_or_create(
            conversation_id=conversation_id, message_id=message_id, defaults={"pinned_by": actor_id}
        )
        if not created:
            raise Conflict("Already pinned.", code="conflict")
        _emit_changed(member.conversation, actor_id, "pinned")
    return pin


def unpin_message(actor_id: str, conversation_id: str, message_id: str) -> None:
    member = _require_pin_rights(actor_id, conversation_id)
    with transaction.atomic():
        deleted, _ = PinnedMessage.objects.filter(
            conversation_id=conversation_id, message_id=message_id
        ).delete()
        if deleted:
            _emit_changed(member.conversation, actor_id, "unpinned")
