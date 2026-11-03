"""Groups as post sees them: a read model fed by profile's ``group.*`` events,
a short negative cache, and a synchronous check against profile.

* **Reads** (a group's feed, one post, media of a group post) use the read
  model. A missing row is checked with profile once and a "not a member" answer
  is cached briefly, so strangers do not cost a call on every request.
* **Writes** (posting, commenting, the group staff's actions) are
  revocation-critical: they ask profile first, so a member removed or banned a
  moment ago cannot post while the ban is still on the bus. When profile cannot
  answer, the read model decides, and a missing row there means no (fail closed).
* Read-model rows store the source ``occurred_at`` and apply only newer events;
  a deleted group and a membership that ended stay as tombstones.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

import requests
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from tara_common.auth import mint_internal_token
from tara_resilience import CircuitBreaker

from .models import BlockedPair, GroupMembership, GroupRef

logger = logging.getLogger("tara.post.groups")
_breaker = CircuitBreaker(name="profile-groups", failure_threshold=5, recovery_timeout=20.0)

RANK = {"member": 1, "moderator": 2, "admin": 3, "owner": 4}
NEGATIVE_TTL = 10  # seconds a "no relation" answer from profile is trusted
# A request or an invite is about to change (an approval, an accepted invite):
# reads ask profile again, at most once per this many seconds per account.
PENDING_STATES = frozenset({"requested", "invited"})
RECHECK_TTL = 5
_MISSING = object()


@dataclass(frozen=True)
class GroupAccess:
    """A group's settings and one account's place in it."""

    group_id: str
    privacy: str
    post_approval: bool
    status: str
    role: str | None = None
    state: str = "none"
    owner_ids: frozenset[str] = field(default_factory=frozenset)

    @property
    def live(self) -> bool:
        return self.status == "active"

    @property
    def is_member(self) -> bool:
        return self.state == "active"

    @property
    def is_staff(self) -> bool:
        """Moderators, admins and owners: approve posts, delete content, pin."""
        return self.is_member and RANK.get(self.role or "", 0) >= RANK["moderator"]


# ---- the bus -----------------------------------------------------------------------


def _when(value) -> datetime:
    when = parse_datetime(value or "") if isinstance(value, str) else value
    if when is None:
        return timezone.now()
    return when if timezone.is_aware(when) else timezone.make_aware(when)


def apply_group_event(payload: dict, occurred_at) -> bool:
    """``group.created`` / ``group.updated`` / ``group.deleted``. False when older
    than what is stored, or the group is already deleted (tombstone)."""
    when = _when(occurred_at)
    group_id = payload["group_id"]
    with transaction.atomic():
        ref = GroupRef.objects.select_for_update().filter(group_id=group_id).first()
        if ref is not None and (ref.status == "deleted" or ref.last_event_at >= when):
            return False
        values = {
            "handle": payload.get("handle") or "",
            "privacy": payload.get("privacy") or "hidden",
            "post_approval": bool(payload.get("post_approval")),
            "status": payload.get("status") or "active",
            "last_event_at": when,
        }
        GroupRef.objects.update_or_create(group_id=group_id, defaults=values)
    return True


def _negative_key(group_id, account_id) -> str:
    return f"post:groups:neg:{group_id}:{account_id}"


def _recheck_key(group_id, account_id) -> str:
    return f"post:groups:recheck:{group_id}:{account_id}"


def _store_member(group_id, account_id, *, role, state, notify_posts, when) -> bool:
    with transaction.atomic():
        row = (
            GroupMembership.objects.select_for_update()
            .filter(group_id=group_id, account_id=account_id)
            .first()
        )
        if row is not None and row.last_event_at >= when:
            return False
        GroupMembership.objects.update_or_create(
            group_id=group_id,
            account_id=account_id,
            defaults={
                "role": role or "",
                "state": state or "none",
                "notify_posts": bool(notify_posts),
                "last_event_at": when,
            },
        )
    cache.delete(_negative_key(group_id, account_id))
    return True


def apply_member_event(payload: dict, occurred_at) -> bool:
    """``group.member.changed``: the account's role and state after the change."""
    return _store_member(
        payload["group_id"],
        payload["account_id"],
        role=payload.get("role"),
        state=payload.get("state") or "none",
        notify_posts=payload.get("notify_posts"),
        when=_when(occurred_at),
    )


# ---- the synchronous check ---------------------------------------------------------


def _fetch(group_id: str, account_id: str):
    """Profile's answer as a dict, ``_MISSING`` for no such group, ``None`` when
    profile could not answer."""

    def _call():
        token = mint_internal_token(issuer="post", audience="profile-internal")
        resp = requests.get(
            f"{settings.PROFILE_INTERNAL_URL}/internal/v1/groups/{group_id}/access/",
            params={"account_id": str(account_id)},
            headers={"Authorization": f"Bearer {token}"},
            timeout=settings.GRAPH_CALL_TIMEOUT,
        )
        if resp.status_code == 404:
            return _MISSING
        resp.raise_for_status()
        return resp.json()["data"]

    try:
        return _breaker.call(_call)
    except Exception:  # noqa: BLE001 - circuit open, timeout, error: the read model decides
        logger.warning("group access check failed", exc_info=True)
        return None


def _from_source(group_id: str, account_id: str):
    """Ask profile, and keep what it said: newer than any event already applied,
    so an older event still on the bus cannot overwrite it. A "no relation"
    answer only goes to the short negative cache, never into the table, so the
    join that is on its way is not lost."""
    data = _fetch(group_id, account_id)
    if data is None or data is _MISSING:
        return data
    now = timezone.now()
    group = data["group"]
    member = data.get("member") or {}
    with transaction.atomic():
        ref = GroupRef.objects.select_for_update().filter(group_id=group_id).first()
        if ref is None or (ref.status != "deleted" and ref.last_event_at < now):
            GroupRef.objects.update_or_create(
                group_id=group_id,
                defaults={
                    "handle": group.get("handle") or "",
                    "privacy": group.get("privacy") or "hidden",
                    "post_approval": bool(group.get("post_approval")),
                    "status": group.get("status") or "active",
                    "last_event_at": now,
                },
            )
    state = member.get("state") or "none"
    if state == "none":
        cache.set(_negative_key(group_id, account_id), True, NEGATIVE_TTL)
    else:
        _store_member(
            group_id,
            account_id,
            role=member.get("role"),
            state=state,
            notify_posts=member.get("notify_posts"),
            when=now,
        )
    return GroupAccess(
        group_id=str(group_id),
        privacy=group.get("privacy") or "hidden",
        post_approval=bool(group.get("post_approval")),
        status=group.get("status") or "active",
        role=member.get("role"),
        state=state,
        owner_ids=frozenset(str(o) for o in data.get("owner_ids", [])),
    )


def _owner_ids(group_id) -> frozenset[str]:
    return frozenset(
        str(a)
        for a in GroupMembership.objects.filter(
            group_id=group_id, state="active", role="owner"
        ).values_list("account_id", flat=True)
    )


def access(group_id, account_id, *, fresh: bool = False) -> GroupAccess | None:
    """The group and the account's place in it, or ``None`` when there is no such
    group or nobody can tell (both mean no access).

    ``fresh`` (writes) asks profile first and uses the read model only when
    profile cannot answer."""
    group_id, account_id = str(group_id), str(account_id)
    if fresh:
        found = _from_source(group_id, account_id)
        if found is _MISSING:
            return None
        if found is not None:
            return found
    ref = GroupRef.objects.filter(group_id=group_id).first()
    if ref is None:
        if fresh:
            return None  # profile is down and nothing is known: fail closed
        found = _from_source(group_id, account_id)
        return None if found is None or found is _MISSING else found
    row = GroupMembership.objects.filter(group_id=group_id, account_id=account_id).first()
    unknown = row is None and not cache.get(_negative_key(group_id, account_id))
    # A pending row may already be an approval still on the bus: ask again, throttled.
    pending = (
        row is not None
        and row.state in PENDING_STATES
        and not cache.get(_recheck_key(group_id, account_id))
    )
    if not fresh and (unknown or pending):
        if pending:
            cache.set(_recheck_key(group_id, account_id), True, RECHECK_TTL)
        found = _from_source(group_id, account_id)
        if found is not None and found is not _MISSING:
            return found
    return GroupAccess(
        group_id=group_id,
        privacy=ref.privacy,
        post_approval=ref.post_approval,
        status=ref.status,
        role=(row.role or None) if row is not None else None,
        state=row.state if row is not None else "none",
        owner_ids=_owner_ids(group_id),
    )


# ---- the rules ---------------------------------------------------------------------


def _blocked_with_any(viewer_id: str, others) -> bool:
    others = [str(o) for o in others if str(o) != str(viewer_id)]
    if not others:
        return False
    return (
        BlockedPair.objects.filter(blocker_id=viewer_id, blocked_id__in=others).exists()
        or BlockedPair.objects.filter(blocked_id=viewer_id, blocker_id__in=others).exists()
    )


def can_see_group(viewer_id: str, acc: GroupAccess | None) -> bool:
    """The group itself (its cover), as profile decides for the header."""
    if acc is None or not acc.live or acc.state == "banned":
        return False
    if acc.state in ("active", "invited", "requested"):
        return True
    if acc.privacy == "hidden":
        return False
    return not _blocked_with_any(viewer_id, acc.owner_ids)


def content_visible(viewer_id: str, acc: GroupAccess | None) -> bool:
    """Posts, comments, events and media of the group."""
    if acc is None or not acc.live or acc.state == "banned":
        return False
    if acc.is_member:
        return True
    if acc.privacy != "public":
        return False
    return not _blocked_with_any(viewer_id, acc.owner_ids)


# ---- recipients for notifications --------------------------------------------------


def handle_of(group_id) -> str:
    """For notification links; blank for a hidden group (links then use the id)."""
    ref = GroupRef.objects.filter(group_id=group_id).only("handle").first()
    return ref.handle if ref is not None else ""


def member_ids(group_id, *, opted_in_only: bool = False) -> list[str]:
    qs = GroupMembership.objects.filter(group_id=group_id, state="active")
    if opted_in_only:
        qs = qs.filter(notify_posts=True)
    return [str(a) for a in qs.order_by("id").values_list("account_id", flat=True)]
