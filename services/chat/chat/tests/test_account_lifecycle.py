"""account.deleted (identity 3C): the account's messages become tombstones,
its reactions go, and it leaves group conversations."""

import uuid

import pytest

from chat import handlers, services
from chat.models import ConversationMember, Message, MessageEdit, MessageReaction
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _deleted(account_id: str) -> EventEnvelope:
    return EventEnvelope(
        event_type="account.deleted",
        subject_id=account_id,
        producer="identity-service",
        payload={"account_id": account_id},
    )


def test_deletion_wipes_messages_and_leaves_groups():
    gone, other, third = _acct(), _acct(), _acct()
    dm = services.create_or_get_dm(gone, other)
    mine = services.send_message(gone, str(dm.id), body="my secret words")
    theirs = services.send_message(other, str(dm.id), body="their words")
    MessageEdit.objects.create(message=mine, previous_body="older secret")
    MessageReaction.objects.create(message=theirs, account_id=gone, type="like")
    group = services.create_group(other, [gone, third], title="G")

    handlers.on_account_deleted(_deleted(gone))
    handlers.on_account_deleted(_deleted(gone))  # idempotent

    mine.refresh_from_db()
    assert (mine.body, mine.body_norm) == ("", "")
    assert mine.deleted_at is not None and str(mine.deleted_by) == gone
    assert mine.seq is not None  # keeps its place in the thread
    assert not MessageEdit.objects.filter(message=mine).exists()
    assert not MessageReaction.objects.filter(account_id=gone).exists()
    theirs.refresh_from_db()
    assert theirs.body == "their words" and theirs.deleted_at is None
    left = ConversationMember.objects.get(conversation=group, account_id=gone)
    assert left.left_at is not None
    # The one-to-one thread keeps both members, so the other side's history stays whole.
    assert ConversationMember.objects.get(conversation=dm, account_id=gone).left_at is None
    assert Message.objects.filter(conversation=dm).count() == 2
