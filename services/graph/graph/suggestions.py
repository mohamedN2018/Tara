"""People you may know and suggested pages (roadmap 1.6, plan 08 track 2D).

People are friends of friends, ranked by how many friends they share with the
viewer. A friend only counts as a bridge while their friend list is visible to
the viewer (so ``only_me`` never leaks through a suggestion), and only the
mutual count is ever shown, never who the mutual friends are. Accounts that
follow the viewer fill in after them (mutual count 0), when they accept
requests from everyone.

Never suggested: the viewer, their friends, anyone with a pending request
either way, anyone with a block either way, accounts with
``searchable=false``, and anything the viewer dismissed.

Pages: published, live pages the viewer neither follows, owns nor dismissed,
whose owner has no block with the viewer, most followed first.
"""

from __future__ import annotations

import uuid

from django.db import IntegrityError, transaction
from django.db.models import Count, IntegerField, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce

from .models import (
    AccountRef,
    BlockRelation,
    DismissedSuggestion,
    FollowRelation,
    Friendship,
    ListVisibility,
    PageRef,
    RelationshipSettings,
)

MAX_LIMIT = 30
#: Upper bound on the bridges and candidates looked at per request.
MAX_BRIDGES = 500
MAX_CANDIDATES = 2000


def _limit(raw: str | None, default: int) -> int:
    return min(max(int(raw), 1), MAX_LIMIT) if raw and raw.isdecimal() else default


def _dismissed(viewer: str, target_type: str) -> set[str]:
    return {
        str(x)
        for x in DismissedSuggestion.objects.filter(
            account_id=viewer, target_type=target_type
        ).values_list("target_id", flat=True)
    }


def _blocked_any(viewer: str) -> set[str]:
    rows = BlockRelation.objects.filter(Q(blocker_id=viewer) | Q(blocked_id=viewer)).values_list(
        "blocker_id", "blocked_id"
    )
    return {str(x) for pair in rows for x in pair} - {viewer}


def people(viewer_id: str, limit: int = 10) -> list[dict]:
    from .services import list_friend_ids

    viewer = str(uuid.UUID(str(viewer_id)))
    blocked = _blocked_any(viewer)
    friends = set(list_friend_ids(viewer))
    pending: set[str] = set()
    for low, high in Friendship.objects.filter(
        Q(account_low_id=viewer) | Q(account_high_id=viewer), status=Friendship.Status.PENDING
    ).values_list("account_low_id", "account_high_id"):
        pending.update({str(low), str(high)})
    excluded = {viewer} | friends | pending | blocked | _dismissed(viewer, "user")

    # Bridges: friends whose friend list the viewer may see (public or friends;
    # the viewer is their friend, so only ``only_me`` hides it).
    hidden = {
        str(x)
        for x in RelationshipSettings.objects.filter(
            account_id__in=list(friends), friends_list_visibility=ListVisibility.ONLY_ME
        ).values_list("account_id", flat=True)
    }
    bridges = sorted(friends - hidden)[:MAX_BRIDGES]

    mutual: dict[str, set[str]] = {}
    if bridges:
        rows = Friendship.objects.filter(
            Q(account_low_id__in=bridges) | Q(account_high_id__in=bridges),
            status=Friendship.Status.ACCEPTED,
        ).values_list("account_low_id", "account_high_id")[: MAX_CANDIDATES * 4]
        bridge_set = set(bridges)
        for low, high in rows:
            low, high = str(low), str(high)
            for bridge, other in ((low, high), (high, low)):
                if bridge in bridge_set and other not in excluded:
                    mutual.setdefault(other, set()).add(bridge)
        # A stale edge between a bridge and a candidate that block each other
        # (a request racing block()) does not count.
        if mutual:
            for blocker, blocked_id in BlockRelation.objects.filter(
                Q(blocker_id__in=bridges, blocked_id__in=list(mutual))
                | Q(blocked_id__in=bridges, blocker_id__in=list(mutual))
            ).values_list("blocker_id", "blocked_id"):
                a, b = str(blocker), str(blocked_id)
                mutual.get(a, set()).discard(b)
                mutual.get(b, set()).discard(a)
            mutual = {k: v for k, v in mutual.items() if v}

    followers = [
        str(x)
        for x in FollowRelation.objects.filter(
            target_id=viewer, target_type=FollowRelation.TargetType.USER
        )
        .order_by("-created_at")
        .values_list("follower_id", flat=True)[:MAX_CANDIDATES]
    ]
    fans = [f for f in followers if f not in excluded and f not in mutual]
    if fans:
        closed = {
            str(x)
            for x in RelationshipSettings.objects.filter(
                account_id__in=fans,
                friend_requests_from=RelationshipSettings.RequestsFrom.FRIENDS_OF_FRIENDS,
            ).values_list("account_id", flat=True)
        }
        fans = [f for f in fans if f not in closed]

    candidates = set(mutual) | set(fans)
    if candidates:
        undiscoverable = {
            str(x)
            for x in AccountRef.objects.filter(
                account_id__in=list(candidates), searchable=False
            ).values_list("account_id", flat=True)
        }
    else:
        undiscoverable = set()

    ranked = sorted(
        (c for c in mutual if c not in undiscoverable),
        key=lambda c: (-len(mutual[c]), c),
    )
    out = [
        {"account_id": c, "mutual_count": len(mutual[c]), "reason": "mutual_friends"}
        for c in ranked
    ]
    out += [
        {"account_id": f, "mutual_count": 0, "reason": "follows_you"}
        for f in fans
        if f not in undiscoverable
    ]
    return out[:limit]


def pages(viewer_id: str, limit: int = 5) -> list[dict]:
    viewer = str(uuid.UUID(str(viewer_id)))
    followed = FollowRelation.objects.filter(
        follower_id=viewer, target_type=FollowRelation.TargetType.PAGE
    ).values_list("target_id", flat=True)
    blocked = _blocked_any(viewer)
    qs = (
        PageRef.objects.filter(status="published", deleted=False)
        .exclude(page_id__in=followed)
        .exclude(page_id__in=list(_dismissed(viewer, "page")))
        .exclude(owner_id=viewer)
    )
    if blocked:
        qs = qs.exclude(owner_id__in=list(blocked))
    followers = (
        FollowRelation.objects.filter(
            target_id=OuterRef("page_id"), target_type=FollowRelation.TargetType.PAGE
        )
        .values("target_id")
        .annotate(n=Count("id"))
        .values("n")
    )
    rows = qs.annotate(
        followers_count=Coalesce(Subquery(followers, output_field=IntegerField()), 0)
    ).order_by("-followers_count", "-created_at", "page_id")[:limit]
    return [
        {
            "page_id": str(p.page_id),
            "handle": p.handle,
            "name": p.name,
            "category": p.category,
            "avatar_media_id": str(p.avatar_media_id) if p.avatar_media_id else None,
            "followers_count": p.followers_count,
        }
        for p in rows
    ]


def dismiss(viewer_id: str, target_id: str, target_type: str) -> None:
    """Idempotent: a second dismiss of the same suggestion changes nothing."""
    try:
        with transaction.atomic():
            DismissedSuggestion.objects.get_or_create(
                account_id=viewer_id, target_id=target_id, target_type=target_type
            )
    except IntegrityError:  # raced with the same dismiss
        pass


def undismiss(viewer_id: str, target_id: str, target_type: str) -> None:
    DismissedSuggestion.objects.filter(
        account_id=viewer_id, target_id=target_id, target_type=target_type
    ).delete()
