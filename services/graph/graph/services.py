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
from django.db.models import Case, Count, Exists, F, OuterRef, Q, QuerySet, UUIDField, When
from django.utils import timezone

from tara_common.exceptions import Conflict, TaraAPIError

from . import events
from .models import (
    BlockRelation,
    FollowRelation,
    Friendship,
    ListVisibility,
    RelationshipSettings,
)


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


#: Which setting guards each kind of list: friends and mutual friends follow
#: ``friends_list_visibility``; followers and following follow
#: ``follow_lists_visibility``; the three counts follow ``counts_visibility``.
LIST_SETTING = {
    "friends": "friends_list_visibility",
    "follows": "follow_lists_visibility",
    "counts": "counts_visibility",
}


def relationship_settings(account_id: str) -> RelationshipSettings:
    """The account's settings; an unsaved row with every default when it has none."""
    return RelationshipSettings.objects.filter(account_id=account_id).first() or (
        RelationshipSettings(account_id=account_id)
    )


def update_relationship_settings(account_id: str, changes: dict) -> RelationshipSettings:
    row, _ = RelationshipSettings.objects.get_or_create(account_id=account_id)
    for field, value in changes.items():
        setattr(row, field, value)
    row.save()
    return row


def _level_allows(level: str, *, is_owner: bool, is_friend: bool) -> bool:
    if is_owner or level == ListVisibility.PUBLIC:
        return True
    return level == ListVisibility.FRIENDS and is_friend


def ensure_lists_visible(viewer_id: str, owner_id: str, kind: str = "friends") -> None:
    """The one visibility gate for another account's relationship lists
    (friends, followers, following, mutual friends) and counts.

    A block in either direction hides every list with 404, never 403 (the same
    answer as a hidden profile), and so does the owner's setting for ``kind``
    (``public``, ``friends`` or ``only_me``; see ``LIST_SETTING``).
    """
    if str(viewer_id) == str(owner_id):
        return
    if is_blocked(viewer_id, owner_id):
        raise TaraAPIError("Resource not found.", code="not_found", http_status_code=404)
    level = getattr(relationship_settings(owner_id), LIST_SETTING[kind])
    if level == ListVisibility.PUBLIC:
        return
    if not _level_allows(level, is_owner=False, is_friend=are_friends(viewer_id, owner_id)):
        raise TaraAPIError("Resource not found.", code="not_found", http_status_code=404)


def relationship_counts(owner_id: str, *, viewer_id: str) -> dict:
    """Friends, followers and following counts, counted exactly as the lists
    are returned to ``viewer_id`` (accounts with a block toward either side
    are left out). Callers gate this with ``ensure_lists_visible(..., "counts")``."""
    owner_id = str(owner_id)
    return {
        "friends_count": _friends_qs(owner_id, viewer_id).count(),
        "followers_count": FollowRelation.objects.filter(
            target_id=owner_id, target_type=FollowRelation.TargetType.USER
        )
        .filter(_unblocked("follower_id", (owner_id, viewer_id)))
        .count(),
        "following_count": FollowRelation.objects.filter(follower_id=owner_id)
        .filter(_unblocked("target_id", (owner_id, viewer_id)))
        .count(),
    }


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
    if not may_send_friend_request(actor_id, target_id):
        raise TaraAPIError(
            "This account only accepts friend requests from friends of friends.",
            code="friend_requests_restricted",
            http_status_code=403,
        )
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


def may_send_friend_request(actor_id: str, target_id: str) -> bool:
    """The target's ``friend_requests_from`` setting: ``everyone``, or only
    accounts that share at least one friend with them."""
    setting = relationship_settings(target_id).friend_requests_from
    if setting != RelationshipSettings.RequestsFrom.FRIENDS_OF_FRIENDS:
        return True
    return bool(mutual_friends(actor_id, target_id))


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
        # Conditional, so only one of two concurrent accepts emits, and an accept
        # racing a block() that deleted the request is a 404, not a 500.
        accepted_at = timezone.now()
        updated = Friendship.objects.filter(
            id=friendship.id, status=Friendship.Status.PENDING
        ).update(status=Friendship.Status.ACCEPTED, accepted_at=accepted_at)
        if not updated:
            raise TaraAPIError("Request not found.", code="not_found", http_status_code=404)
        friendship.status, friendship.accepted_at = Friendship.Status.ACCEPTED, accepted_at
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
    return [str(x) for x in _friends_qs(account_id, viewer_id).values_list("other_id", flat=True)]


def _friends_qs(account_id: str, viewer_id: str | None) -> QuerySet[Friendship]:
    account_id = str(account_id)
    return _with_other_id(
        Friendship.objects.filter(
            Q(account_low_id=account_id) | Q(account_high_id=account_id),
            status=Friendship.Status.ACCEPTED,
        ),
        account_id,
    ).filter(_unblocked("other_id", (account_id, viewer_id)))


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
        from .preferences import on_block

        on_block(actor_id, target_id)
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


MAX_BATCH = 50


def _uuids(values: Iterable[str]) -> list[str]:
    """Canonical UUID strings; anything else is dropped (search ids are free text)."""
    out = []
    for value in values:
        try:
            out.append(str(uuid.UUID(str(value))))
        except ValueError:
            continue
    return out


def blocked_with(viewer_id: str, owner_ids: Iterable[str]) -> set[str]:
    """The owners that have a block, in either direction, with ``viewer_id``."""
    owners = {str(o) for o in owner_ids}
    rows = BlockRelation.objects.filter(
        Q(blocker_id=viewer_id, blocked_id__in=owners)
        | Q(blocked_id=viewer_id, blocker_id__in=owners)
    ).values_list("blocker_id", "blocked_id")
    return ({str(x) for pair in rows for x in pair} - {str(viewer_id)}) & owners


def _levels(owner_ids: Iterable[str], kind: str) -> dict[str, str]:
    """Each owner's level for ``kind``; owners without a settings row are public."""
    field = LIST_SETTING[kind]
    rows = RelationshipSettings.objects.filter(account_id__in=list(owner_ids)).values_list(
        "account_id", field
    )
    return {str(owner): level for owner, level in rows}


def lists_visible_to(
    viewer_id: str,
    owner_ids: Iterable[str],
    kind: str = "friends",
    *,
    viewer_friends: set[str] | None = None,
) -> set[str]:
    """Bulk form of ``ensure_lists_visible``: the owners whose ``kind`` lists
    (for ``friends``, also the mutual friends) ``viewer_id`` may see.

    ``viewer_friends`` saves a query when the caller already knows them."""
    viewer = str(viewer_id)
    owners = {str(o) for o in owner_ids}
    hidden = blocked_with(viewer, owners)
    levels = _levels(owners - hidden - {viewer}, kind)
    if viewer_friends is None and ListVisibility.FRIENDS in levels.values():
        viewer_friends = set(list_friend_ids(viewer))
    visible = set()
    for owner in owners:
        if owner == viewer:
            visible.add(owner)
        elif owner not in hidden and _level_allows(
            levels.get(owner, ListVisibility.PUBLIC),
            is_owner=False,
            is_friend=owner in (viewer_friends or set()),
        ):
            visible.add(owner)
    return visible


def relationships_for(viewer_id: str, user_ids: Iterable[str], page_ids: Iterable[str]) -> dict:
    """The viewer's relationship with each account and page of a search page.

    A fixed number of queries whatever the batch size. Accounts in a block with
    the viewer, either way, are left out. ``mutual_count`` follows
    ``mutual_friends`` (friends shared, minus anyone blocked with either side)
    and is ``None`` where the target's lists are hidden from the viewer.
    """
    viewer = str(uuid.UUID(str(viewer_id)))
    users = [u for u in dict.fromkeys(_uuids(user_ids)) if u != viewer][:MAX_BATCH]
    pages = list(dict.fromkeys(_uuids(page_ids)))[:MAX_BATCH]
    out: dict[str, dict] = {}
    if users:
        blocked_users = blocked_with(viewer, users)
        levels = _levels(users, "friends")
        rows = Friendship.objects.filter(
            Q(account_low_id=viewer, account_high_id__in=users)
            | Q(account_high_id=viewer, account_low_id__in=users)
        ).values_list("id", "account_low_id", "account_high_id", "status", "requested_by")
        edges = {}
        for fid, low, high, status, requested_by in rows:
            other = str(high) if str(low) == viewer else str(low)
            edges[other] = (str(fid), status, str(requested_by))
        followed = {
            str(t)
            for t in FollowRelation.objects.filter(
                follower_id=viewer, target_id__in=users, target_type=FollowRelation.TargetType.USER
            ).values_list("target_id", flat=True)
        }
        mine = set(list_friend_ids(viewer))
        shared: dict[str, set[str]] = {u: set() for u in users}
        if mine:
            theirs = Friendship.objects.filter(
                Q(account_low_id__in=users, account_high_id__in=mine)
                | Q(account_high_id__in=users, account_low_id__in=mine),
                status=Friendship.Status.ACCEPTED,
            ).values_list("account_low_id", "account_high_id")
            for low, high in theirs:
                low, high = str(low), str(high)
                if low in shared and high in mine:
                    shared[low].add(high)
                if high in shared and low in mine:
                    shared[high].add(low)
            for blocker, blocked in BlockRelation.objects.filter(
                Q(blocker_id__in=users, blocked_id__in=mine)
                | Q(blocked_id__in=users, blocker_id__in=mine)
            ).values_list("blocker_id", "blocked_id"):
                blocker, blocked = str(blocker), str(blocked)
                shared.get(blocker, set()).discard(blocked)
                shared.get(blocked, set()).discard(blocker)
        for u in users:
            if u in blocked_users:
                continue  # a block either way: nothing about them
            fid, status, requested_by = edges.get(u, (None, None, None))
            if status == Friendship.Status.ACCEPTED:
                state = "friends"
            elif status == Friendship.Status.PENDING:
                state = "pending_out" if requested_by == viewer else "pending_in"
            else:
                state = "none"
            # The count discloses part of u's friend list: None while it is hidden.
            lists_ok = _level_allows(
                levels.get(u, ListVisibility.PUBLIC), is_owner=False, is_friend=state == "friends"
            )
            out[u] = {
                "state": state,
                "request_id": fid if state.startswith("pending") else None,
                "following": u in followed,
                "mutual_count": len(shared[u]) if lists_ok else None,
            }
    if pages:
        followed_pages = {
            str(t)
            for t in FollowRelation.objects.filter(
                follower_id=viewer, target_id__in=pages, target_type=FollowRelation.TargetType.PAGE
            ).values_list("target_id", flat=True)
        }
        counts = dict(
            FollowRelation.objects.filter(
                target_id__in=pages, target_type=FollowRelation.TargetType.PAGE
            )
            .values("target_id")
            .annotate(n=Count("id"))
            .values_list("target_id", "n")
        )
        for p in pages:
            out[p] = {
                "following": p in followed_pages,
                "followers_count": counts.get(uuid.UUID(p), 0),
            }
    return out
