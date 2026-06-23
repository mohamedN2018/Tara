"""Social Graph business logic: friends, follows, blocks.

All relationship actions are idempotent (DB unique constraints + get_or_create).
Blocking severs existing friendship/follows. Symmetric friendships are stored
once with account_low_id < account_high_id.
"""

from __future__ import annotations

import uuid

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from tara_common.exceptions import Conflict, TaraAPIError

from . import events
from .models import BlockRelation, FollowRelation, Friendship


def _order(a: str, b: str) -> tuple[str, str]:
    ua, ub = uuid.UUID(str(a)), uuid.UUID(str(b))
    return (str(ua), str(ub)) if ua < ub else (str(ub), str(ua))


def is_blocked(a: str, b: str) -> bool:
    return BlockRelation.objects.filter(
        Q(blocker_id=a, blocked_id=b) | Q(blocker_id=b, blocked_id=a)
    ).exists()


def _ensure_not_self(a: str, b: str) -> None:
    if str(a) == str(b):
        raise TaraAPIError(
            "You cannot do that to yourself.", code="validation_error", http_status_code=400
        )


# ---- friends ----------------------------------------------------------------


def send_friend_request(actor_id: str, target_id: str) -> Friendship:
    _ensure_not_self(actor_id, target_id)
    if is_blocked(actor_id, target_id):
        raise TaraAPIError("Action not allowed.", code="permission_denied", http_status_code=403)
    low, high = _order(actor_id, target_id)
    existing = Friendship.objects.filter(account_low_id=low, account_high_id=high).first()
    if existing:
        if existing.status == Friendship.Status.ACCEPTED:
            raise Conflict("Already friends.", code="conflict")
        raise Conflict("A friend request is already pending.", code="conflict")
    with transaction.atomic():
        try:
            friendship = Friendship.objects.create(
                account_low_id=low, account_high_id=high, requested_by=actor_id
            )
        except IntegrityError as exc:  # raced with a concurrent request
            raise Conflict("A friend request is already pending.", code="conflict") from exc
        events.emit(
            "friendship.requested",
            subject_id=str(friendship.id),
            payload={"from": str(actor_id), "to": str(target_id)},
            actor_id=str(actor_id),
        )
    return friendship


def _load_pending(friendship_id: str) -> Friendship:
    friendship = Friendship.objects.filter(
        id=friendship_id, status=Friendship.Status.PENDING
    ).first()
    if friendship is None:
        raise TaraAPIError("Request not found.", code="not_found", http_status_code=404)
    return friendship


def _is_member(friendship: Friendship, account_id: str) -> bool:
    return str(account_id) in (str(friendship.account_low_id), str(friendship.account_high_id))


def accept_friend_request(actor_id: str, friendship_id: str) -> Friendship:
    friendship = _load_pending(friendship_id)
    # Only the recipient (not the requester) may accept.
    if not _is_member(friendship, actor_id) or str(friendship.requested_by) == str(actor_id):
        raise TaraAPIError("Not permitted.", code="permission_denied", http_status_code=403)
    with transaction.atomic():
        friendship.status = Friendship.Status.ACCEPTED
        friendship.accepted_at = timezone.now()
        friendship.save(update_fields=["status", "accepted_at"])
        events.emit(
            "friendship.accepted",
            subject_id=str(friendship.id),
            payload={"a": str(friendship.account_low_id), "b": str(friendship.account_high_id)},
            actor_id=str(actor_id),
        )
    return friendship


def reject_or_cancel_request(actor_id: str, friendship_id: str) -> None:
    friendship = _load_pending(friendship_id)
    if not _is_member(friendship, actor_id):
        raise TaraAPIError("Not permitted.", code="permission_denied", http_status_code=403)
    friendship.delete()


def unfriend(actor_id: str, other_id: str) -> None:
    low, high = _order(actor_id, other_id)
    friendship = Friendship.objects.filter(
        account_low_id=low, account_high_id=high, status=Friendship.Status.ACCEPTED
    ).first()
    if friendship is None:
        return  # idempotent
    with transaction.atomic():
        friendship.delete()
        events.emit(
            "friendship.removed",
            subject_id=str(friendship.id),
            payload={"a": low, "b": high},
            actor_id=str(actor_id),
        )


def list_friend_ids(account_id: str) -> list[str]:
    qs = Friendship.objects.filter(
        Q(account_low_id=account_id) | Q(account_high_id=account_id),
        status=Friendship.Status.ACCEPTED,
    )
    out = []
    for f in qs:
        out.append(
            str(f.account_high_id)
            if str(f.account_low_id) == str(account_id)
            else str(f.account_low_id)
        )
    return out


def list_requests(account_id: str, *, outgoing: bool) -> list[Friendship]:
    qs = Friendship.objects.filter(
        Q(account_low_id=account_id) | Q(account_high_id=account_id),
        status=Friendship.Status.PENDING,
    )
    if outgoing:
        return [f for f in qs if str(f.requested_by) == str(account_id)]
    return [f for f in qs if str(f.requested_by) != str(account_id)]


def are_friends(a: str, b: str) -> bool:
    low, high = _order(a, b)
    return Friendship.objects.filter(
        account_low_id=low, account_high_id=high, status=Friendship.Status.ACCEPTED
    ).exists()


def mutual_friends(a: str, b: str) -> list[str]:
    return sorted(set(list_friend_ids(a)) & set(list_friend_ids(b)))


# ---- follows ----------------------------------------------------------------


def follow(actor_id: str, target_id: str, target_type: str = "user") -> FollowRelation:
    if target_type == FollowRelation.TargetType.USER:
        _ensure_not_self(actor_id, target_id)
        if is_blocked(actor_id, target_id):
            raise TaraAPIError(
                "Action not allowed.", code="permission_denied", http_status_code=403
            )
    relation, created = FollowRelation.objects.get_or_create(
        follower_id=actor_id, target_id=target_id, target_type=target_type
    )
    if created:
        events.emit(
            "user.followed",
            subject_id=str(relation.id),
            payload={
                "follower": str(actor_id),
                "target": str(target_id),
                "target_type": target_type,
            },
            actor_id=str(actor_id),
        )
    return relation


def unfollow(actor_id: str, target_id: str, target_type: str = "user") -> None:
    deleted, _ = FollowRelation.objects.filter(
        follower_id=actor_id, target_id=target_id, target_type=target_type
    ).delete()
    if deleted:
        events.emit(
            "user.unfollowed",
            subject_id=str(target_id),
            payload={
                "follower": str(actor_id),
                "target": str(target_id),
                "target_type": target_type,
            },
            actor_id=str(actor_id),
        )


def follower_ids(target_id: str, target_type: str = "user") -> list[str]:
    return [
        str(x)
        for x in FollowRelation.objects.filter(
            target_id=target_id, target_type=target_type
        ).values_list("follower_id", flat=True)
    ]


def following(account_id: str) -> list[FollowRelation]:
    return list(FollowRelation.objects.filter(follower_id=account_id))


def follows(a: str, b: str) -> bool:
    return FollowRelation.objects.filter(follower_id=a, target_id=b, target_type="user").exists()


# ---- blocks -----------------------------------------------------------------


def block(actor_id: str, target_id: str) -> BlockRelation:
    _ensure_not_self(actor_id, target_id)
    with transaction.atomic():
        relation, created = BlockRelation.objects.get_or_create(
            blocker_id=actor_id, blocked_id=target_id
        )
        if not created:
            return relation
        # Sever existing relationships in both directions.
        low, high = _order(actor_id, target_id)
        Friendship.objects.filter(account_low_id=low, account_high_id=high).delete()
        FollowRelation.objects.filter(
            Q(follower_id=actor_id, target_id=target_id)
            | Q(follower_id=target_id, target_id=actor_id),
            target_type="user",
        ).delete()
        events.emit(
            "user.blocked",
            subject_id=str(target_id),
            payload={"blocker_id": str(actor_id), "blocked_id": str(target_id)},
            actor_id=str(actor_id),
        )
    return relation


def unblock(actor_id: str, target_id: str) -> None:
    deleted, _ = BlockRelation.objects.filter(blocker_id=actor_id, blocked_id=target_id).delete()
    if deleted:
        events.emit(
            "user.unblocked",
            subject_id=str(target_id),
            payload={"blocker_id": str(actor_id), "blocked_id": str(target_id)},
            actor_id=str(actor_id),
        )


def blocked_ids(actor_id: str) -> list[str]:
    return [
        str(x)
        for x in BlockRelation.objects.filter(blocker_id=actor_id).values_list(
            "blocked_id", flat=True
        )
    ]


# ---- relationship (internal) ------------------------------------------------


def relationship(a: str, b: str) -> dict:
    return {
        "are_friends": are_friends(a, b),
        "a_follows_b": follows(a, b),
        "b_follows_a": follows(b, a),
        "blocked_either_way": is_blocked(a, b),
    }
