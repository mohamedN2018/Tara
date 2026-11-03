"""Content that goes away takes its notifications (or their previews) with it."""

import uuid

import pytest
from django.db import connection

from notifications import handlers, services
from notifications.models import Notification, OutboxEvent
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _event(event_type, payload, *, subject_id=None, actor_id=None):
    return EventEnvelope(
        event_type=event_type,
        subject_id=subject_id or str(uuid.uuid4()),
        producer="test",
        payload=payload,
        actor_id=actor_id,
    )


# ---- messages: a deleted or edited message leaves no preview behind ----------------


def _message(conversation, sender, recipient, text) -> str:
    message_id = str(uuid.uuid4())
    handlers.on_message_created(
        _event(
            "message.created",
            {
                "conversation_id": conversation,
                "message_id": message_id,
                "sender": sender,
                "type": "text",
                "recipients": [sender, recipient],
                "muted": [],
                "preview": text,
            },
            subject_id=message_id,
            actor_id=sender,
        )
    )
    return message_id


def _changed(event_type, conversation, message_id, recipients, scope="everyone"):
    handler = {
        "message.deleted": handlers.on_message_deleted,
        "message.edited": handlers.on_message_edited,
    }[event_type]
    handler(
        _event(
            event_type,
            {
                "conversation_id": conversation,
                "message_id": message_id,
                "recipients": recipients,
                "scope": scope,
            },
            subject_id=message_id,
        )
    )


def _rows(recipient, conversation):
    return Notification.objects.filter(
        recipient_id=recipient, kind="message", subject_ref=f"conversation:{conversation}"
    )


def _row(recipient, conversation) -> Notification:
    return _rows(recipient, conversation).get()


@pytest.mark.parametrize("scope", ["everyone", "moderation"])
def test_a_deleted_only_message_takes_its_notification(scope):
    sender, recipient, conversation = _acct(), _acct(), _acct()
    message_id = _message(conversation, sender, recipient, "my new address is ...")
    row = _row(recipient, conversation)
    assert row.data["message_id"] == message_id
    OutboxEvent.objects.all().delete()

    _changed("message.deleted", conversation, message_id, [sender, recipient], scope)

    assert not _rows(recipient, conversation).exists()
    (event,) = OutboxEvent.objects.all()
    assert event.event_type == "notification.deleted"
    assert event.payload["payload"] == {
        "recipient": recipient,
        "notification_ids": [str(row.id)],
    }
    assert "address" not in str(event.payload)  # never message text on the bus


def test_deleting_the_latest_of_several_blanks_the_preview_and_keeps_the_row():
    sender, recipient, conversation = _acct(), _acct(), _acct()
    _message(conversation, sender, recipient, "first")
    latest = _message(conversation, sender, recipient, "second")
    assert _row(recipient, conversation).data["message_count"] == 2
    OutboxEvent.objects.all().delete()

    _changed("message.deleted", conversation, latest, [sender, recipient])

    row = _row(recipient, conversation)
    assert (row.body, row.actor_count) == ("", 1)
    assert not OutboxEvent.objects.filter(event_type="notification.deleted").exists()


def test_a_redelivered_delete_changes_nothing_more():
    sender, recipient, conversation = _acct(), _acct(), _acct()
    message_id = _message(conversation, sender, recipient, "oops")
    _changed("message.deleted", conversation, message_id, [sender, recipient])
    OutboxEvent.objects.all().delete()
    _changed("message.deleted", conversation, message_id, [sender, recipient])
    assert not OutboxEvent.objects.exists()


def test_an_edited_message_loses_its_preview_but_not_its_row():
    sender, recipient, conversation = _acct(), _acct(), _acct()
    message_id = _message(conversation, sender, recipient, "typo'd text")
    _changed("message.edited", conversation, message_id, [sender, recipient])
    assert _row(recipient, conversation).body == ""


def test_deleting_an_older_message_keeps_the_latest_preview():
    sender, recipient, conversation = _acct(), _acct(), _acct()
    older = _message(conversation, sender, recipient, "first")
    _message(conversation, sender, recipient, "second")
    _changed("message.deleted", conversation, older, [sender, recipient])
    assert _row(recipient, conversation).body == "second"


def test_other_conversations_keep_their_previews():
    sender, recipient, here, there = _acct(), _acct(), _acct(), _acct()
    message_id = _message(here, sender, recipient, "here")
    _message(there, sender, recipient, "there")
    _changed("message.deleted", here, message_id, [sender, recipient])
    assert _row(recipient, there).body == "there"


def test_a_row_from_before_message_ids_is_blanked_not_deleted():
    recipient, conversation = _acct(), _acct()
    legacy = Notification.objects.create(
        recipient_id=recipient,
        kind="message",
        subject_ref=f"conversation:{conversation}",
        body="old text",
        data={"conversation_id": conversation},
    )
    _changed("message.deleted", conversation, str(uuid.uuid4()), [recipient])
    legacy.refresh_from_db()
    assert legacy.body == ""


# ---- comments ----------------------------------------------------------------------


def _deleted_comment(post_id, comment_id, removed_ids):
    handlers.on_comment_deleted(
        _event(
            "comment.deleted",
            {"post_id": post_id, "comment_id": comment_id, "removed_ids": removed_ids},
            subject_id=comment_id,
        )
    )


def test_a_deleted_thread_takes_its_reply_and_mention_notifications():
    owner, author, replier, other = _acct(), _acct(), _acct(), _acct()
    post_id, root, reply, unrelated = (str(uuid.uuid4()) for _ in range(4))
    target = {"subject_ref": f"post:{post_id}"}
    services.notify(
        owner, "comment.reply", actor_id=replier, target_ref=f"comment:{reply}", **target
    )
    services.notify(other, "mention", actor_id=author, target_ref=f"comment:{root}", **target)
    keep = services.notify(
        owner, "comment.reply", actor_id=replier, target_ref=f"comment:{unrelated}", **target
    )
    OutboxEvent.objects.all().delete()

    _deleted_comment(post_id, root, [root, reply])

    assert list(Notification.objects.values_list("id", flat=True)) == [keep.id]
    deleted = OutboxEvent.objects.filter(event_type="notification.deleted")
    assert {e.payload["payload"]["recipient"] for e in deleted} == {owner, other}


def test_a_comment_aggregate_counting_other_people_stays():
    owner, first, second = _acct(), _acct(), _acct()
    post_id, c1, c2 = (str(uuid.uuid4()) for _ in range(3))
    services.notify(
        owner,
        "post.comment",
        actor_id=first,
        subject_ref=f"post:{post_id}",
        target_ref=f"comment:{c1}",
    )
    row = services.notify(
        owner,
        "post.comment",
        actor_id=second,
        subject_ref=f"post:{post_id}",
        target_ref=f"comment:{c2}",
    )
    _deleted_comment(post_id, c2, [c2])
    row.refresh_from_db()
    assert row.actor_count == 2


def test_a_comment_aggregate_of_only_that_comment_goes():
    owner, author = _acct(), _acct()
    post_id, comment = str(uuid.uuid4()), str(uuid.uuid4())
    services.notify(
        owner,
        "post.comment",
        actor_id=author,
        subject_ref=f"post:{post_id}",
        target_ref=f"comment:{comment}",
    )
    _deleted_comment(post_id, comment, [comment])
    assert not Notification.objects.exists()


def test_an_older_comment_deleted_event_without_removed_ids_still_works():
    owner, replier = _acct(), _acct()
    post_id, comment = str(uuid.uuid4()), str(uuid.uuid4())
    services.notify(
        owner,
        "comment.reply",
        actor_id=replier,
        subject_ref=f"post:{post_id}",
        target_ref=f"comment:{comment}",
    )
    handlers.on_comment_deleted(
        _event("comment.deleted", {"post_id": post_id, "comment_id": comment}, subject_id=comment)
    )
    assert not Notification.objects.exists()


# ---- friend requests are found by an index, not a table scan ------------------------


def test_resolving_a_friend_request_uses_its_index():
    request_id = str(uuid.uuid4())
    services.notify(_acct(), "friend.request", actor_id=_acct(), data={"request_id": request_id})
    qs = Notification.objects.filter(kind="friend.request", data__request_id=request_id)
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL enable_seqscan = off")
        plan = qs.explain()
    assert "notif_friend_request_idx" in plan
    assert services.resolve_friend_request(request_id, "accepted") == 1


# ---- blocks: cleanup runs both ways ----------------------------------------------------


def _request(sender, recipient) -> Notification:
    request_id = str(uuid.uuid4())
    handlers.on_friend_requested(
        _event(
            "friendship.requested",
            {"from": sender, "to": recipient},
            subject_id=request_id,
            actor_id=sender,
        )
    )
    return Notification.objects.get(recipient_id=recipient, kind="friend.request", actor_id=sender)


@pytest.mark.parametrize("who_blocks", ["sender", "recipient"])
def test_a_block_deletes_the_pending_friend_request_either_way(who_blocks):
    """Graph drops the request silently on a block. The notification goes too,
    deleted rather than resolved: "withdrawn" would tell the recipient about the block."""
    sender, recipient, bystander = _acct(), _acct(), _acct()
    row = _request(sender, recipient)
    kept = _request(bystander, recipient)
    sender_side = services.notify(sender, "follow", actor_id=recipient)  # blocked -> blocker too
    OutboxEvent.objects.all().delete()
    blocker, blocked = (sender, recipient) if who_blocks == "sender" else (recipient, sender)

    handlers.on_user_blocked(_event("user.blocked", {"blocker_id": blocker, "blocked_id": blocked}))

    remaining = set(Notification.objects.values_list("id", flat=True))
    assert row.id not in remaining and sender_side.id not in remaining
    assert kept.id in remaining
    assert not Notification.objects.filter(resolution="withdrawn").exists()
    deleted = {
        (e.payload["payload"]["recipient"], tuple(e.payload["payload"]["notification_ids"]))
        for e in OutboxEvent.objects.filter(event_type="notification.deleted")
    }
    assert deleted == {(recipient, (str(row.id),)), (sender, (str(sender_side.id),))}
    assert not OutboxEvent.objects.filter(event_type="notification.read").exists()
