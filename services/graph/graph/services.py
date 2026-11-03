"""Social Graph business logic: friends, follows, blocks.

All relationship actions are idempotent (DB unique constraints + get_or_create).
Blocking severs existing friendship/follows and emits the same removal events an
explicit unfriend/unfollow would. Every relationship list leaves out accounts that
have a block, in either direction, with the list owner or the viewer. Symmetric
friendships are stored once with account_low_id < account_high_id.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from django.db import IntegrityError, transaction
from django.db.models import Case, Exists, F, OuterRef, Q, QuerySet, UUIDField, When
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


def _unblocked(ref: str, parties: Iterable[str | None]) -> Exists:
    """SQL condition: the account in column/annotation ``ref`` has no block, in
    either direction, with any of ``parties``.

    Applied in SQL (not after fetching) so a later cursor paginator pages over
    the filtered rows and never returns short pages.
    """
    ids = sorted({str(p) for p in parties if p})
    return ~Exists(
        BlockRelation.objects.filter(
            Q(blocker_id__in=ids, blocked_id=OuterRef(ref))
            | Q(blocked_id__in=ids, blocker_id=OuterRef(ref))
        )
    )


def _with_other_id(qs: QuerySet[Friendship], account_id: str) -> QuerySet[Friendship]:
    """Annotate each friendship row with the account on the other side."""
    return qs.annotate(
        other_id=Case(
            When(account_low_id=account_id, then=F("account_high_id")),
            default=F("account_low_id"),
            output_field=UUIDField(),
        )
    )


def ensure_lists_visible(viewer_id: str, owner_id: str) -> None:
    """The one visibility gate for another account's relationship lists
    (friends, followers, mutual friends).

    A block in either direction hides every list with 404, never 403 (the same
    answer as a hidden profile). Milestone 1.6 adds the owner's list-visibility
    settings here, so every list keeps using this one resolver.
    """
    if str(viewer_id) != str(owner_id) and is_blocked(viewer_id, owner_id):
        raise TaraAPIError("Resource not found.", code="not_found", http_status_code=404)


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
    # A request that slipped past a concurrent block() must never become a
    # friendship; to the recipient it simply no longer exists.
    if is_blocked(friendship.account_low_id, friendship.account_high_id):
        raise TaraAPIError("Request not found.", code="not_found", http_status_code=404)
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
    with transaction.atomic():
        # Only the request that actually went away emits, so a cancel racing a
        # reject (or a double click) cannot announce the withdrawal twice.
        deleted, _ = Friendship.objects.filter(
            id=friendship.id, status=Friendship.Status.PENDING
        ).delete()
        if deleted and str(friendship.requested_by) == str(actor_id):
            # The requester took it back: the recipient's notification resolves.
            # A reject by the recipient emits nothing (the requester was never told).
            other = (
                friendship.account_high_id
                if str(friendship.account_low_id) == str(actor_id)
                else friendship.account_low_id
            )
            events.emit(
                "friendship.request.withdrawn",
                subject_id=str(friendship.id),
                payload={"from": str(actor_id), "to": str(other)},
                actor_id=str(actor_id),
            )


def _end_friendship(low: str, high: str, *, actor_id: str, reason: str) -> None:
    """Delete the pair's friendship row (accepted or pending), if any.

    Emits ``friendship.removed`` only for an accepted friendship. The row is
    locked first, so its status is the committed one and two concurrent callers
    (an unfriend racing a block, or both sides blocking) emit the event once.
    """
    friendship = (
        Friendship.objects.select_for_update()
        .filter(account_low_id=low, account_high_id=high)
        .first()
    )
    if friendship is None:
        return
    # Read before delete(): Django sets the instance's pk to None once it is
    # deleted, which used to emit subject_id "None" (and one shared partition).
    friendship_id = str(friendship.id)
    was_accepted = friendship.status == Friendship.Status.ACCEPTED
    friendship.delete()
    if was_accepted:
        events.emit(
            "friendship.removed",
            subject_id=friendship_id,
            payload={"a": str(low), "b": str(high), "reason": reason},
            actor_id=str(actor_id),
        )


def unfriend(actor_id: str, other_id: str) -> None:
    low, high = _order(actor_id, other_id)
    with transaction.atomic():
        if not Friendship.objects.filter(
            account_low_id=low, account_high_id=high, status=Friendship.Status.ACCEPTED
        ).exists():
            return  # idempotent; a pending request is cancelled through reject/
        _end_friendship(low, high, actor_id=actor_id, reason="unfriend")


def list_friend_ids(account_id: str, *, viewer_id: str | None = None) -> list[str]:
    """Accepted friends of ``account_id`` as returned to ``viewer_id`` (default:
    the owner). Accounts with a block, either way, with the owner or the viewer
    are left out, so a stale edge (a request racing a block) never surfaces."""
    account_id = str(account_id)
    qs = (
        _with_other_id(
            Friendship.objects.filter(
                Q(account_low_id=account_id) | Q(account_high_id=account_id),
                status=Friendship.Status.ACCEPTED,
            ),
            account_id,
        )
        .filter(_unblocked("other_id", (account_id, viewer_id)))
        .values_list("other_id", flat=True)
    )
    return [str(x) for x in qs]


def list_requests(account_id: str, *, outgoing: bool) -> list[Friendship]:
    account_id = str(account_id)
    qs = _with_other_id(
        Friendship.objects.filter(
            Q(account_low_id=account_id) | Q(account_high_id=account_id),
            status=Friendship.Status.PENDING,
        ),
        account_id,
    ).filter(_unblocked("other_id", (account_id,)))
    if outgoing:
        return [f for f in qs if str(f.requested_by) == str(account_id)]
    return [f for f in qs if str(f.requested_by) != str(account_id)]


def are_friends(a: str, b: str) -> bool:
    low, high = _order(a, b)
    return Friendship.objects.filter(
        account_low_id=low, account_high_id=high, status=Friendship.Status.ACCEPTED
    ).exists()


def mutual_friends(a: str, b: str) -> list[str]:
    """Friends ``a`` and ``b`` share, minus anyone with a block toward either.

    Callers gate this with ``ensure_lists_visible``: the intersection reveals
    part of ``b``'s friend list, so it is hidden whenever that list is.
    """
    return sorted(set(list_friend_ids(a, viewer_id=b)) & set(list_friend_ids(b, viewer_id=a)))


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


def _end_follow(
    follower_id: str, target_id: str, target_type: str, *, actor_id: str, reason: str
) -> None:
    """Delete one follow edge and emit ``user.unfollowed`` if a row went away.

    The delete's row count is the guard: a concurrent caller that loses the race
    deletes nothing and emits nothing.
    """
    deleted, _ = FollowRelation.objects.filter(
        follower_id=follower_id, target_id=target_id, target_type=target_type
    ).delete()
    if deleted:
        events.emit(
            "user.unfollowed",
            subject_id=str(target_id),
            payload={
                "follower": str(follower_id),
                "target": str(target_id),
                "target_type": str(target_type),
                "reason": reason,
            },
            actor_id=str(actor_id),
        )


def unfollow(actor_id: str, target_id: str, target_type: str = "user") -> None:
    with transaction.atomic():
        _end_follow(actor_id, target_id, target_type, actor_id=actor_id, reason="unfollow")


def follower_ids(
    target_id: str, target_type: str = "user", *, viewer_id: str | None = None
) -> list[str]:
    """Followers of ``target_id`` as returned to ``viewer_id`` (default: the
    target itself), minus accounts with a block toward either of them."""
    qs = (
        FollowRelation.objects.filter(target_id=target_id, target_type=target_type)
        .filter(_unblocked("follower_id", (target_id, viewer_id)))
        .values_list("follower_id", flat=True)
    )
    return [str(x) for x in qs]


def following(account_id: str, *, viewer_id: str | None = None) -> list[FollowRelation]:
    """What ``account_id`` follows, minus accounts with a block toward the
    owner or the viewer (page ids never appear in a block row)."""
    return list(
        FollowRelation.objects.filter(follower_id=account_id).filter(
            _unblocked("target_id", (account_id, viewer_id))
        )
    )


def follows(a: str, b: str) -> bool:
    return FollowRelation.objects.filter(follower_id=a, target_id=b, target_type="user").exists()


# ---- blocks -----------------------------------------------------------------


def block(actor_id: str, target_id: str) -> BlockRelation:
    """Block ``target_id`` and sever every edge between the two accounts.

    In one transaction with the block row, the outbox gets ``user.blocked``,
    then ``friendship.removed`` (if they were friends) and one
    ``user.unfollowed`` per follow direction, each with ``reason="block"``, so
    consumers that only listen to the removal events (feed today; chat and
    notification read models later) react exactly as to an unfriend/unfollow.
    A pending request is deleted silently. Re-blocking emits nothing.
    """
    _ensure_not_self(actor_id, target_id)
    actor_id, target_id = str(actor_id), str(target_id)
    with transaction.atomic():
        relation, created = BlockRelation.objects.get_or_create(
            blocker_id=actor_id, blocked_id=target_id
        )
        if not created:
            return relation
        events.emit(
            "user.blocked",
            subject_id=target_id,
            payload={"blocker_id": actor_id, "blocked_id": target_id},
            actor_id=actor_id,
        )
        low, high = _order(actor_id, target_id)
        _end_friendship(low, high, actor_id=actor_id, reason="block")
        for follower, target in ((actor_id, target_id), (target_id, actor_id)):
            _end_follow(
                follower,
                target,
                FollowRelation.TargetType.USER,
                actor_id=actor_id,
                reason="block",
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
