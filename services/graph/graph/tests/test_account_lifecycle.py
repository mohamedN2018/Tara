"""account.deleted (identity 3C): every edge that names the account goes."""

import uuid

import pytest

from graph import handlers
from graph.models import (
    AccountRef,
    BlockRelation,
    FollowRelation,
    Friendship,
    MuteRelation,
    RelationshipSettings,
)
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


def test_deletion_erases_every_edge_of_the_account():
    gone, a, b = _acct(), _acct(), _acct()
    low, high = sorted([gone, a])
    Friendship.objects.create(
        account_low_id=low, account_high_id=high, status="accepted", requested_by=a
    )
    keep_low, keep_high = sorted([a, b])
    Friendship.objects.create(
        account_low_id=keep_low, account_high_id=keep_high, status="accepted", requested_by=a
    )
    FollowRelation.objects.create(follower_id=gone, target_id=a)
    FollowRelation.objects.create(follower_id=b, target_id=gone)
    BlockRelation.objects.create(blocker_id=a, blocked_id=gone)
    MuteRelation.objects.create(account_id=b, target_id=gone)
    RelationshipSettings.objects.create(account_id=gone)
    AccountRef.objects.create(account_id=gone)

    handlers.on_account_deleted(_deleted(gone))
    handlers.on_account_deleted(_deleted(gone))  # idempotent

    assert Friendship.objects.count() == 1  # a and b stay friends
    assert not FollowRelation.objects.exists()
    assert not BlockRelation.objects.exists()
    assert not MuteRelation.objects.exists()
    assert not RelationshipSettings.objects.filter(account_id=gone).exists()
    assert not AccountRef.objects.filter(account_id=gone).exists()
