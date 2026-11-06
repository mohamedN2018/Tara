"""Groups business logic: visibility, create/edit/delete, membership, roles,
rules, reports, suggestions and moderation.

Rules (roadmap 1.11 and section 3.3):

* **One visibility rule** (``can_see`` for the group itself, ``content_visible``
  for its posts, members, events and media). A group the viewer may not see is
  404, never 403. Deleted and moderator-removed groups are hidden from everyone.
  - Public: anyone sees the group and its content.
  - Private: anyone sees the name, description and rules; content is for
    active members only.
  - Hidden: only members, invitees and people who asked to join see it at all.
  - Banned accounts never see the group. Someone blocked either way with an
    owner does not see it either, unless they are themselves a member.
* **Roles** (``roles.py``) are checked here, never only in the UI. The last
  owner cannot leave, be demoted, removed or banned.
* **Every membership write locks the group row first**, so ``member_count`` and
  the last-owner checks never race.
* **Remote calls before the write transaction** (graph for invites, media for
  the cover); views run outside ``ATOMIC_REQUESTS``.
* **Events on the bus carry ids and enums only.** Name and handle travel only
  for public and private groups; a hidden group's are blank.
"""

from __future__ import annotations

import logging
import re
import uuid

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count, IntegerField, Q, Value
from django.utils import timezone
from profiles import events
from profiles.models import BlockedPair, UserProfile

from tara_common.exceptions import TaraAPIError
from tara_events.envelope import uuid7

from . import graph, media, roles
from .models import (
    MAX_RULES,
    Category,
    Group,
    GroupMember,
    GroupReport,
    GroupRule,
    GroupSuggestionDismissal,
    Privacy,
    ReportReason,
    Role,
    State,
)

logger = logging.getLogger("tara.profile.groups")

HANDLE_RE = re.compile(r"^[a-z0-9_]{3,30}$")
# Path segments of the API and the SPA, and names people would take for staff.
RESERVED_HANDLES = frozenset(
    {
        "new",
        "discover",
        "mine",
        "id",
        "manage",
        "admin",
        "tara",
        "feed",
        "invites",
        "suggestions",
        "lookup",
    }
)
MAX_INVITES_PER_CALL = 50
MAX_SUGGESTIONS = 20
MAX_STAFF_RECIPIENTS = 100
MAX_SEARCH = 100
STAFF_ROLES = (Role.OWNER, Role.ADMIN, Role.MODERATOR)
NO_STATE = "none"  # on the bus: the account has no relation with the group any more
EDITABLE_FIELDS = (
    "name",
    "description",
    "category",
    "privacy",
    "membership_approval",
    "post_approval",
    "cover_media_id",
)
# ``managed``: my active groups where I am staff (moderator and up), for the
# "Groups you manage" hub.
LIST_SCOPES = ("mine", "discover", "invited", "requested", "managed")


# ---- errors ------------------------------------------------------------------------


def _not_found(what: str = "Group") -> TaraAPIError:
    return TaraAPIError(f"{what} not found.", code="not_found", http_status_code=404)


def _bad_request(message: str, code: str = "validation_error") -> TaraAPIError:
    return TaraAPIError(message, code=code, http_status_code=400)


def _forbidden(message: str, code: str = "permission_denied") -> TaraAPIError:
    return TaraAPIError(message, code=code, http_status_code=403)


def _conflict(message: str, code: str) -> TaraAPIError:
    return TaraAPIError(message, code=code, http_status_code=409)


def _last_owner() -> TaraAPIError:
    return _conflict("A group needs at least one owner.", "last_owner")


# ---- lookups -----------------------------------------------------------------------


def blocked_ids(account_id: str) -> set[str]:
    """Accounts blocked by, or blocking, the account."""
    pairs = BlockedPair.objects.filter(
        Q(blocker_id=account_id) | Q(blocked_id=account_id)
    ).values_list("blocker_id", "blocked_id")
    return {str(a) for pair in pairs for a in pair} - {str(account_id)}


def _blocked_either_way(a: str, b: str) -> bool:
    return BlockedPair.objects.filter(
        Q(blocker_id=a, blocked_id=b) | Q(blocker_id=b, blocked_id=a)
    ).exists()


def owner_ids(group: Group) -> list[str]:
    return [
        str(a)
        for a in GroupMember.objects.filter(group=group, state=State.ACTIVE, role=Role.OWNER)
        .order_by("joined_at", "id")
        .values_list("account_id", flat=True)
    ]


def staff_ids(group: Group) -> list[str]:
    return [
        str(a)
        for a in GroupMember.objects.filter(group=group, state=State.ACTIVE, role__in=STAFF_ROLES)
        .order_by("joined_at", "id")
        .values_list("account_id", flat=True)[:MAX_STAFF_RECIPIENTS]
    ]


def membership(group: Group, account_id: str) -> GroupMember | None:
    return GroupMember.objects.filter(group=group, account_id=account_id).first()


def active_role(member: GroupMember | None) -> str | None:
    return member.role if member is not None and member.state == State.ACTIVE else None


def _parse_ref(ref: str) -> dict:
    try:
        return {"id": uuid.UUID(str(ref))}
    except ValueError:
        return {"handle": str(ref).lower()}


# ---- visibility --------------------------------------------------------------------


def can_see(viewer_id: str, group: Group, member: GroupMember | None) -> bool:
    """The single rule for the group itself (header, About, rules)."""
    if not group.is_live:
        return False
    if member is not None:
        if member.state == State.BANNED:
            return False
        return True  # active, invited or asked to join
    if group.privacy == Privacy.HIDDEN:
        return False
    blocked = blocked_ids(str(viewer_id))
    return not any(o in blocked for o in owner_ids(group))


def content_visible(viewer_id: str, group: Group, member: GroupMember | None) -> bool:
    """Posts, members, events and media of the group."""
    if not can_see(viewer_id, group, member):
        return False
    if member is not None and member.state == State.ACTIVE:
        return True
    return group.privacy == Privacy.PUBLIC


def resolve(viewer_id: str, ref: str) -> tuple[Group, GroupMember | None]:
    """The group by handle or id and the viewer's membership; 404 when hidden."""
    group = Group.objects.filter(**_parse_ref(ref)).first()
    if group is None:
        raise _not_found()
    member = membership(group, viewer_id)
    if not can_see(viewer_id, group, member):
        raise _not_found()
    return group, member


def _require(member: GroupMember | None, permission: str) -> str:
    role = active_role(member)
    if not roles.has(role, permission):
        raise _forbidden("You do not have permission to do this in the group.")
    return role


def _lock(group: Group) -> Group:
    """Re-read the group under its row lock; gone or removed meanwhile is 404."""
    locked = Group.objects.select_for_update().filter(id=group.id).first()
    if locked is None or not locked.is_live:
        raise _not_found()
    return locked


# ---- events on the bus -------------------------------------------------------------


def _status(group: Group) -> str:
    return "deleted" if group.deleted_at else group.status


def group_payload(group: Group) -> dict:
    """``{group_id, handle, name, privacy, category}`` (what search indexes), plus
    the fields post's read model needs. A hidden group's name and handle never
    travel, and ``privacy: "hidden"`` tells search to drop it."""
    hidden = group.privacy == Privacy.HIDDEN
    return {
        "group_id": str(group.id),
        "handle": "" if hidden else group.handle,
        "name": "" if hidden else group.name,
        "privacy": group.privacy,
        "category": group.category,
        "post_approval": group.post_approval,
        "membership_approval": group.membership_approval,
        "status": _status(group),
    }


def _emit(event_type: str, group: Group, payload: dict, *, actor_id: str | None) -> None:
    if not settings.PROFILE_EMIT_GROUP_EVENTS:
        return
    events.emit(
        event_type,
        subject_id=str(group.id),
        payload=payload,
        actor_id=str(actor_id) if actor_id else None,
        partition_key=f"group:{group.id}",
    )


def _emit_member(
    group: Group,
    account_id: str,
    *,
    action: str,
    actor_id: str | None,
    member: GroupMember | None,
    previous: tuple[str | None, str | None] = (None, None),
    recipients: list[str] | None = None,
) -> None:
    """``group.member.changed``: the account's role and state after the change
    (``state: "none"`` once the row is gone). ``recipients`` is set only for a
    new request, so notification can tell the group's staff."""
    hidden = group.privacy == Privacy.HIDDEN
    _emit(
        "group.member.changed",
        group,
        {
            "group_id": str(group.id),
            "account_id": str(account_id),
            "role": member.role if member is not None else None,
            "state": member.state if member is not None else NO_STATE,
            "previous_role": previous[0],
            "previous_state": previous[1] or NO_STATE,
            "action": action,
            "notify_posts": bool(member.notify_posts) if member is not None else False,
            "privacy": group.privacy,
            "handle": "" if hidden else group.handle,
            "recipients": recipients or [],
        },
        actor_id=actor_id,
    )


def _snapshot(member: GroupMember | None) -> tuple[str | None, str | None]:
    return (member.role, member.state) if member is not None else (None, None)


# ---- create, edit, delete ----------------------------------------------------------


def validate_handle(handle: str) -> str:
    handle = (handle or "").strip().lower()
    if not HANDLE_RE.match(handle):
        raise _bad_request(
            "A group URL has 3 to 30 letters, digits or underscores.", "invalid_handle"
        )
    if handle in RESERVED_HANDLES:
        raise _conflict("This group URL is taken.", "handle_taken")
    return handle


def _clean_rules(rules: list[dict]) -> list[dict]:
    if len(rules) > MAX_RULES:
        raise _bad_request(f"A group can have at most {MAX_RULES} rules.", "too_many_rules")
    out = []
    for rule in rules:
        title = (rule.get("title") or "").strip()
        if not title:
            raise _bad_request("A rule needs a title.")
        out.append({"title": title, "body": (rule.get("body") or "").strip()})
    return out


def create_group(actor_id: str, data: dict) -> Group:
    """Any signed-in account may create a group and becomes its owner. The cover
    is checked and bound through media first (503 when media is down)."""
    handle = validate_handle(data["handle"])
    name = (data.get("name") or "").strip()
    if not name:
        raise _bad_request("A group needs a name.")
    if data.get("privacy", Privacy.PUBLIC) not in Privacy.values:
        raise _bad_request("Invalid privacy.")
    if data.get("category", Category.GENERAL) not in Category.values:
        raise _bad_request("Invalid category.")
    rules = _clean_rules(data.get("rules") or [])
    if Group.objects.filter(handle=handle).exists():
        raise _conflict("This group URL is taken.", "handle_taken")
    group_id = uuid7()
    cover = data.get("cover_media_id")
    if cover:
        media.check_and_bind_cover(str(actor_id), str(group_id), str(cover))
    now = timezone.now()
    try:
        with transaction.atomic():
            group = Group.objects.create(
                id=group_id,
                handle=handle,
                name=name,
                description=(data.get("description") or "").strip(),
                category=data.get("category") or Category.GENERAL,
                cover_media_id=cover or None,
                privacy=data.get("privacy") or Privacy.PUBLIC,
                membership_approval=bool(data.get("membership_approval", False)),
                post_approval=bool(data.get("post_approval", False)),
                member_count=1,
                created_by=actor_id,
            )
            owner = GroupMember.objects.create(
                group=group,
                account_id=actor_id,
                role=Role.OWNER,
                state=State.ACTIVE,
                joined_at=now,
            )
            GroupRule.objects.bulk_create(
                GroupRule(group=group, position=i, **rule) for i, rule in enumerate(rules)
            )
            _emit("group.created", group, group_payload(group), actor_id=actor_id)
            _emit_member(group, actor_id, action="created", actor_id=actor_id, member=owner)
    except IntegrityError as exc:  # a concurrent create took the handle first
        raise _conflict("This group URL is taken.", "handle_taken") from exc
    return group


def update_group(actor_id: str, group: Group, member: GroupMember | None, changes: dict) -> Group:
    """Admins and owners edit the settings; the handle never changes."""
    changes = {k: v for k, v in changes.items() if k in EDITABLE_FIELDS}
    if not changes:
        raise _bad_request("Nothing to change.")
    role = _require(member, "edit")
    if "privacy" in changes:
        if not roles.has(role, "change_privacy"):
            raise _forbidden("You cannot change the group's privacy.")
        if changes["privacy"] not in Privacy.values:
            raise _bad_request("Invalid privacy.")
    if "category" in changes and changes["category"] not in Category.values:
        raise _bad_request("Invalid category.")
    if "name" in changes:
        changes["name"] = (changes["name"] or "").strip()
        if not changes["name"]:
            raise _bad_request("A group needs a name.")
    if "description" in changes:
        changes["description"] = (changes["description"] or "").strip()
    cover = changes.get("cover_media_id")
    if cover and str(cover) != str(group.cover_media_id or ""):
        media.check_and_bind_cover(str(actor_id), str(group.id), str(cover))
    with transaction.atomic():
        group = _lock(group)
        _require(membership(group, actor_id), "edit")  # demoted meanwhile: 403
        changed = sorted(f for f, v in changes.items() if getattr(group, f) != v)
        if not changed:
            return group
        for field in changed:
            setattr(group, field, changes[field])
        group.save(update_fields=[*changed, "updated_at"])
        _emit(
            "group.updated",
            group,
            {**group_payload(group), "changed": changed},
            actor_id=actor_id,
        )
    return group


def delete_group(actor_id: str, group: Group) -> None:
    with transaction.atomic():
        group = _lock(group)
        _require(membership(group, actor_id), "delete")
        group.deleted_at = timezone.now()
        group.save(update_fields=["deleted_at", "updated_at"])
        _emit("group.deleted", group, group_payload(group), actor_id=actor_id)


# ---- joining and leaving -----------------------------------------------------------


def _activate(group: Group, member: GroupMember) -> None:
    member.state = State.ACTIVE
    member.joined_at = timezone.now()
    member.save(update_fields=["state", "joined_at", "updated_at"])
    group.member_count += 1
    group.save(update_fields=["member_count", "updated_at"])


def _deactivate_count(group: Group) -> None:
    group.member_count = max(0, group.member_count - 1)
    group.save(update_fields=["member_count", "updated_at"])


def join(viewer_id: str, group: Group) -> GroupMember:
    """Join at once, or ask to join when the group needs approval. Accepting an
    invite from staff skips the approval. Asking again changes nothing."""
    with transaction.atomic():
        group = _lock(group)
        member = membership(group, viewer_id)
        if not can_see(viewer_id, group, member):
            raise _not_found()
        if member is not None and member.state in (State.ACTIVE, State.REQUESTED):
            return member
        previous = _snapshot(member)
        if member is not None:  # invited
            inviter = membership(group, str(member.invited_by)) if member.invited_by else None
            if not group.membership_approval or roles.has(active_role(inviter), "approve_requests"):
                _activate(group, member)
                action = "joined"
            else:
                member.state = State.REQUESTED
                member.save(update_fields=["state", "updated_at"])
                action = "requested"
        else:
            needs_approval = group.membership_approval
            member = GroupMember.objects.create(
                group=group,
                account_id=viewer_id,
                role=Role.MEMBER,
                state=State.REQUESTED if needs_approval else State.ACTIVE,
                joined_at=None if needs_approval else timezone.now(),
            )
            if not needs_approval:
                group.member_count += 1
                group.save(update_fields=["member_count", "updated_at"])
            action = "requested" if needs_approval else "joined"
        _emit_member(
            group,
            viewer_id,
            action=action,
            actor_id=viewer_id,
            member=member,
            previous=previous,
            recipients=staff_ids(group) if action == "requested" else None,
        )
    return member


def cancel_join(viewer_id: str, group: Group) -> None:
    """Take back my request, or decline my invite."""
    with transaction.atomic():
        group = _lock(group)
        member = membership(group, viewer_id)
        if member is None or member.state not in (State.REQUESTED, State.INVITED):
            raise _not_found("Request")
        previous = _snapshot(member)
        action = "cancelled" if member.state == State.REQUESTED else "invite_declined"
        member.delete()
        _emit_member(
            group, viewer_id, action=action, actor_id=viewer_id, member=None, previous=previous
        )


def _owner_count(group: Group) -> int:
    return GroupMember.objects.filter(group=group, state=State.ACTIVE, role=Role.OWNER).count()


def leave(viewer_id: str, group: Group) -> None:
    with transaction.atomic():
        group = _lock(group)
        member = membership(group, viewer_id)
        if member is None or member.state != State.ACTIVE:
            raise _not_found("Membership")
        if member.role == Role.OWNER and _owner_count(group) <= 1:
            raise _last_owner()
        previous = _snapshot(member)
        member.delete()
        _deactivate_count(group)
        _emit_member(
            group, viewer_id, action="left", actor_id=viewer_id, member=None, previous=previous
        )


def set_notify_posts(viewer_id: str, group: Group, notify: bool) -> GroupMember:
    with transaction.atomic():
        group = _lock(group)
        member = membership(group, viewer_id)
        if member is None or member.state != State.ACTIVE:
            raise _not_found("Membership")
        if member.notify_posts != notify:
            member.notify_posts = notify
            member.save(update_fields=["notify_posts", "updated_at"])
            _emit_member(
                group,
                viewer_id,
                action="settings_changed",
                actor_id=viewer_id,
                member=member,
                previous=_snapshot(member),
            )
    return member


# ---- invites -----------------------------------------------------------------------


def invite(actor_id: str, group: Group, account_ids: list) -> list[str]:
    """Active members invite their friends (graph is asked; 503 when it cannot
    answer). Members, invitees and banned accounts are skipped quietly, so a ban
    is never revealed; staff inviting someone who asked to join approves them."""
    actor = str(actor_id)
    ids = list(dict.fromkeys(str(a) for a in account_ids if str(a) != actor))
    if not ids:
        raise _bad_request("Choose at least one friend to invite.")
    if len(ids) > MAX_INVITES_PER_CALL:
        raise _bad_request(f"At most {MAX_INVITES_PER_CALL} invites at a time.")
    _require(membership(group, actor), "invite")
    friends = graph.friend_ids(actor)
    if friends is None:
        raise TaraAPIError(
            "Friends cannot be checked right now; try again.",
            code="dependency_unavailable",
            http_status_code=503,
        )
    blocked = blocked_ids(actor)
    if any(i not in friends or i in blocked for i in ids):
        raise _bad_request("You can only invite your friends.", "invite_not_friend")
    invited: list[str] = []
    with transaction.atomic():
        group = _lock(group)
        actor_role = _require(membership(group, actor), "invite")
        existing = {
            str(m.account_id): m
            for m in GroupMember.objects.filter(group=group, account_id__in=ids)
        }
        for account in ids:
            row = existing.get(account)
            if row is None:
                row = GroupMember.objects.create(
                    group=group, account_id=account, state=State.INVITED, invited_by=actor
                )
                invited.append(account)
                _emit_member(group, account, action="invited", actor_id=actor, member=row)
            elif row.state == State.REQUESTED and roles.has(actor_role, "approve_requests"):
                previous = _snapshot(row)
                _activate(group, row)
                _emit_member(
                    group, account, action="approved", actor_id=actor, member=row, previous=previous
                )
    return invited


# ---- member lists ------------------------------------------------------------------


def members_queryset(
    viewer_id: str,
    group: Group,
    member: GroupMember | None,
    *,
    state: str = State.ACTIVE,
    role: str = "",
    q: str = "",
):
    """Active members to anyone who may read the group's content; requests,
    invites and bans to moderators and up. Accounts blocked either way with the
    viewer are left out."""
    if state not in State.values:
        raise _bad_request(f"state must be one of {', '.join(State.values)}.")
    if role and role not in Role.values:
        raise _bad_request("Invalid role.")
    if not content_visible(viewer_id, group, member):
        raise _not_found()
    if state != State.ACTIVE and not roles.has(active_role(member), "approve_requests"):
        raise _forbidden("Only the group's moderators can see this list.")
    qs = GroupMember.objects.filter(group=group, state=state).exclude(
        account_id__in=list(blocked_ids(str(viewer_id)))
    )
    if role:
        qs = qs.filter(role=role)
    q = (q or "").strip()[:MAX_SEARCH]
    if q:
        matching = UserProfile.objects.filter(
            Q(display_name__icontains=q) | Q(handle__icontains=q.lower()),
            deleted_at__isnull=True,
        ).values("account_id")
        qs = qs.filter(account_id__in=matching)
    if state == State.ACTIVE:
        return qs.order_by("-joined_at", "-id")
    return qs.order_by("-updated_at", "-id")


# ---- staff actions on members ------------------------------------------------------


def _target(group: Group, account_id: str) -> GroupMember:
    row = membership(group, account_id)
    if row is None:
        raise _not_found("Member")
    return row


def approve_request(actor_id: str, group: Group, account_id: str) -> GroupMember:
    with transaction.atomic():
        group = _lock(group)
        _require(membership(group, actor_id), "approve_requests")
        row = _target(group, account_id)
        if row.state != State.REQUESTED:
            raise _not_found("Request")
        previous = _snapshot(row)
        _activate(group, row)
        _emit_member(
            group, account_id, action="approved", actor_id=actor_id, member=row, previous=previous
        )
    return row


def decline_request(actor_id: str, group: Group, account_id: str) -> None:
    with transaction.atomic():
        group = _lock(group)
        _require(membership(group, actor_id), "approve_requests")
        row = _target(group, account_id)
        if row.state != State.REQUESTED:
            raise _not_found("Request")
        previous = _snapshot(row)
        row.delete()
        _emit_member(
            group, account_id, action="declined", actor_id=actor_id, member=None, previous=previous
        )


def revoke_invite(actor_id: str, group: Group, account_id: str) -> None:
    """Staff who see the pending invitations withdraw one. The account keeps no
    relation with the group (``removed``, ``invited`` -> ``none``); nobody is told."""
    with transaction.atomic():
        group = _lock(group)
        _require(membership(group, actor_id), "approve_requests")
        row = _target(group, account_id)
        if row.state != State.INVITED:
            raise _not_found("Invitation")
        previous = _snapshot(row)
        row.delete()
        _emit_member(
            group, account_id, action="removed", actor_id=actor_id, member=None, previous=previous
        )


def _check_can_act(actor_role: str, row: GroupMember, group: Group) -> None:
    if row.state == State.ACTIVE:
        if not roles.can_act_on(actor_role, row.role):
            raise _forbidden("You cannot do this to a member with this role.", "role_not_allowed")
        if row.role == Role.OWNER and _owner_count(group) <= 1:
            raise _last_owner()


def remove_member(actor_id: str, group: Group, account_id: str) -> None:
    if str(actor_id) == str(account_id):
        raise _bad_request("Leave the group instead.")
    with transaction.atomic():
        group = _lock(group)
        actor_role = _require(membership(group, actor_id), "moderate")
        row = _target(group, account_id)
        if row.state != State.ACTIVE:
            raise _not_found("Member")
        _check_can_act(actor_role, row, group)
        previous = _snapshot(row)
        row.delete()
        _deactivate_count(group)
        _emit_member(
            group, account_id, action="removed", actor_id=actor_id, member=None, previous=previous
        )


def ban(actor_id: str, group: Group, account_id: str) -> GroupMember:
    """Ban a member, a requester, an invitee, or any account (for example the
    author of reported content). A banned account no longer sees the group."""
    if str(actor_id) == str(account_id):
        raise _bad_request("You cannot ban yourself.")
    with transaction.atomic():
        group = _lock(group)
        actor_role = _require(membership(group, actor_id), "moderate")
        row = membership(group, account_id)
        previous = _snapshot(row)
        if row is not None and row.state == State.BANNED:
            return row
        if row is None:
            row = GroupMember(group=group, account_id=account_id)
        else:
            _check_can_act(actor_role, row, group)
            if row.state == State.ACTIVE:
                _deactivate_count(group)
        row.state = State.BANNED
        row.role = Role.MEMBER
        row.notify_posts = False
        row.joined_at = None
        row.save()
        _emit_member(
            group, account_id, action="banned", actor_id=actor_id, member=row, previous=previous
        )
    return row


def unban(actor_id: str, group: Group, account_id: str) -> None:
    with transaction.atomic():
        group = _lock(group)
        _require(membership(group, actor_id), "moderate")
        row = _target(group, account_id)
        if row.state != State.BANNED:
            raise _not_found("Ban")
        previous = _snapshot(row)
        row.delete()
        _emit_member(
            group, account_id, action="unbanned", actor_id=actor_id, member=None, previous=previous
        )


def change_role(actor_id: str, group: Group, account_id: str, new_role: str) -> GroupMember:
    if new_role not in Role.values:
        raise _bad_request("Invalid role.")
    with transaction.atomic():
        group = _lock(group)
        actor_role = _require(membership(group, actor_id), "change_roles")
        row = _target(group, account_id)
        if row.state != State.ACTIVE:
            raise _not_found("Member")
        if row.role == new_role:
            return row
        if not roles.can_act_on(actor_role, row.role) or not roles.can_assign(actor_role, new_role):
            raise _forbidden("You cannot give this role.", "role_not_allowed")
        if row.role == Role.OWNER and _owner_count(group) <= 1:
            raise _last_owner()
        previous = _snapshot(row)
        row.role = new_role
        row.save(update_fields=["role", "updated_at"])
        _emit_member(
            group,
            account_id,
            action="role_changed",
            actor_id=actor_id,
            member=row,
            previous=previous,
        )
    return row


# ---- rules -------------------------------------------------------------------------


def list_rules(group: Group) -> list[GroupRule]:
    return list(group.rules.order_by("position", "created_at"))


def add_rule(actor_id: str, group: Group, title: str, body: str) -> GroupRule:
    title = (title or "").strip()
    if not title:
        raise _bad_request("A rule needs a title.")
    with transaction.atomic():
        group = _lock(group)
        _require(membership(group, actor_id), "manage_rules")
        count = group.rules.count()
        if count >= MAX_RULES:
            raise _bad_request(f"A group can have at most {MAX_RULES} rules.", "too_many_rules")
        return GroupRule.objects.create(
            group=group, title=title, body=(body or "").strip(), position=count
        )


def _rule(group: Group, rule_id) -> GroupRule:
    rule = GroupRule.objects.filter(group=group, id=rule_id).first()
    if rule is None:
        raise _not_found("Rule")
    return rule


def edit_rule(actor_id: str, group: Group, rule_id, changes: dict) -> GroupRule:
    with transaction.atomic():
        group = _lock(group)
        _require(membership(group, actor_id), "manage_rules")
        rule = _rule(group, rule_id)
        if "title" in changes:
            title = (changes["title"] or "").strip()
            if not title:
                raise _bad_request("A rule needs a title.")
            rule.title = title
        if "body" in changes:
            rule.body = (changes["body"] or "").strip()
        rule.save(update_fields=["title", "body"])
    return rule


def delete_rule(actor_id: str, group: Group, rule_id) -> None:
    with transaction.atomic():
        group = _lock(group)
        _require(membership(group, actor_id), "manage_rules")
        _rule(group, rule_id).delete()
        for position, rule in enumerate(group.rules.order_by("position", "created_at")):
            if rule.position != position:
                GroupRule.objects.filter(id=rule.id).update(position=position)


def reorder_rules(actor_id: str, group: Group, ids: list) -> list[GroupRule]:
    with transaction.atomic():
        group = _lock(group)
        _require(membership(group, actor_id), "manage_rules")
        current = {str(r.id): r for r in group.rules.all()}
        wanted = [str(i) for i in ids]
        if sorted(wanted) != sorted(current):
            raise _bad_request("Send every rule id exactly once.")
        for position, rule_id in enumerate(wanted):
            GroupRule.objects.filter(id=rule_id).update(position=position)
    return list_rules(group)


# ---- reports -----------------------------------------------------------------------


def report(viewer_id: str, group: Group, member: GroupMember | None, reason: str) -> GroupReport:
    """404 (nothing written) when the reporter cannot see the group; one report
    per account per group, a repeat returns the first and emits nothing."""
    if reason not in ReportReason.values:
        raise _bad_request("Invalid reason.")
    if not can_see(viewer_id, group, member):
        raise _not_found()
    existing = GroupReport.objects.filter(group=group, reporter_id=viewer_id).first()
    if existing is not None:
        return existing
    owners = owner_ids(group)
    try:
        with transaction.atomic():
            row = GroupReport.objects.create(group=group, reporter_id=viewer_id, reason=reason)
            _emit(
                "group.reported",
                group,
                {
                    "group_id": str(group.id),
                    "reporter": str(viewer_id),
                    "reason": reason,
                    "owner_id": owners[0] if owners else str(group.created_by),
                },
                actor_id=viewer_id,
            )
    except IntegrityError:  # a concurrent duplicate won the unique constraint
        return GroupReport.objects.get(group=group, reporter_id=viewer_id)
    return row


# ---- lists, discovery and suggestions ----------------------------------------------


def _live() -> Q:
    return Q(deleted_at__isnull=True, status=Group.Status.ACTIVE)


def _blocked_owner_groups(viewer_id: str):
    blocked = list(blocked_ids(str(viewer_id)))
    return GroupMember.objects.filter(
        state=State.ACTIVE, role=Role.OWNER, account_id__in=blocked
    ).values("group_id")


def list_queryset(viewer_id: str, scope: str = "mine", *, q: str = "", category: str = ""):
    """Groups for one tab, already filtered by visibility in SQL.

    ``discover`` never lists hidden groups, nor groups the viewer already has a
    relation with (member, invited, asked, banned)."""
    if scope not in LIST_SCOPES:
        raise _bad_request(f"scope must be one of {', '.join(LIST_SCOPES)}.")
    if category and category not in Category.values:
        raise _bad_request("Invalid category.")
    viewer = str(viewer_id)
    base = Group.objects.filter(_live())
    q = (q or "").strip()[:MAX_SEARCH]
    if q:
        base = base.filter(Q(name__icontains=q) | Q(handle__icontains=q.lower()))
    if category:
        base = base.filter(category=category)
    mine = GroupMember.objects.filter(account_id=viewer)
    if scope == "discover":
        return (
            base.filter(privacy__in=(Privacy.PUBLIC, Privacy.PRIVATE))
            .exclude(id__in=mine.values("group_id"))
            .exclude(id__in=_blocked_owner_groups(viewer))
            .order_by("-created_at", "-id")
        )
    if scope == "managed":
        staff = mine.filter(state=State.ACTIVE, role__in=(Role.OWNER, Role.ADMIN, Role.MODERATOR))
        return base.filter(id__in=staff.values("group_id")).order_by("-updated_at", "-id")
    state = {"mine": State.ACTIVE, "invited": State.INVITED, "requested": State.REQUESTED}[scope]
    return base.filter(id__in=mine.filter(state=state).values("group_id")).order_by(
        "-updated_at", "-id"
    )


def memberships_of(viewer_id: str, groups) -> dict:
    ids = [g.id for g in groups]
    return {
        m.group_id: m for m in GroupMember.objects.filter(group_id__in=ids, account_id=viewer_id)
    }


def suggestions(viewer_id: str, cfg=None) -> list[tuple[Group, int, list[str]]]:
    """Public and private groups (never hidden) that the viewer's friends belong
    to, ranked by how many friends are members, then by the categories of the
    viewer's own groups, then by size. Dismissed groups are left out.

    Returns ``(group, friend_member_count, up to 3 friend ids)``. Graph down: no
    friend signal, so the ranking falls back to categories and size.

    ``cfg`` (``intel_config.Served``, Tara Intelligence WP 5.5) sets how many groups
    and friend ids; none (or no config row) is ``discovery@1``: 20 and 3, as before."""
    from . import intel_config

    params = (cfg or intel_config.Served(intel_config.resolve())).params
    max_suggestions = params["groups.max_suggestions"]
    preview = params["groups.friend_preview"]
    viewer = str(viewer_id)
    friends = sorted((graph.friend_ids(viewer) or set()) - blocked_ids(viewer))
    mine = GroupMember.objects.filter(account_id=viewer)
    my_categories = list(
        Group.objects.filter(_live(), id__in=mine.filter(state=State.ACTIVE).values("group_id"))
        .values_list("category", flat=True)
        .distinct()
    )
    dismissed = GroupSuggestionDismissal.objects.filter(account_id=viewer).values("group_id")
    candidates = (
        Group.objects.filter(_live(), privacy__in=(Privacy.PUBLIC, Privacy.PRIVATE))
        .exclude(id__in=mine.values("group_id"))
        .exclude(id__in=dismissed)
        .exclude(id__in=_blocked_owner_groups(viewer))
        .annotate(
            friend_members=Count(
                "members",
                filter=Q(members__state=State.ACTIVE, members__account_id__in=friends),
            )
            if friends
            else Value(0, output_field=IntegerField())
        )
    )
    rows = list(
        candidates.order_by("-friend_members", "-member_count", "-created_at")[
            : max_suggestions * 3
        ]
    )
    rows.sort(key=lambda g: (-g.friend_members, g.category not in my_categories, -g.member_count))
    rows = rows[:max_suggestions]
    sample: dict = {}
    if friends and rows and preview:
        for group_id, account in (
            GroupMember.objects.filter(
                group_id__in=[g.id for g in rows if g.friend_members],
                state=State.ACTIVE,
                account_id__in=friends,
            )
            .order_by("joined_at")
            .values_list("group_id", "account_id")
        ):
            bucket = sample.setdefault(group_id, [])
            if len(bucket) < preview:
                bucket.append(str(account))
    return [(g, g.friend_members, sample.get(g.id, [])) for g in rows]


def dismiss_suggestion(viewer_id: str, group_id) -> None:
    group = Group.objects.filter(id=group_id).first()
    if group is None:
        raise _not_found()
    GroupSuggestionDismissal.objects.get_or_create(account_id=viewer_id, group=group)


# ---- moderation --------------------------------------------------------------------


def apply_moderation(group_id: str, action: str) -> None:
    """Driven by ``moderation.actioned`` with ``target_type=group``.

    ``remove`` hides the group from everyone (404, its owners too) and emits
    ``group.deleted`` so search drops it and post hides its posts; ``approve``
    (an overturned removal) shows it again and emits ``group.updated``."""
    with transaction.atomic():
        group = Group.objects.select_for_update().filter(id=group_id).first()
        if group is None:
            return
        suspended = group.status == Group.Status.SUSPENDED
        if action == "remove" and not suspended:
            group.status = Group.Status.SUSPENDED
            group.save(update_fields=["status", "updated_at"])
            _emit(
                "group.deleted", group, {**group_payload(group), "by": "moderation"}, actor_id=None
            )
        elif action == "approve" and suspended:
            group.status = Group.Status.ACTIVE
            group.save(update_fields=["status", "updated_at"])
            if group.deleted_at is None:
                _emit(
                    "group.updated",
                    group,
                    {**group_payload(group), "changed": ["status"]},
                    actor_id=None,
                )


# ---- internal access check (post's synchronous fallback) ---------------------------


def access(group_id: str, account_id: str) -> dict | None:
    """The authoritative state post needs before a group post or comment is
    written: the group's privacy, approval flag and status, and the account's
    role and state (``none`` when there is no row). ``None`` when no such group."""
    group = Group.objects.filter(id=group_id).first()
    if group is None:
        return None
    row = membership(group, account_id)
    return {
        "group": group_payload(group),
        "member": {
            "account_id": str(account_id),
            "role": row.role if row is not None else None,
            "state": row.state if row is not None else NO_STATE,
            "notify_posts": bool(row.notify_posts) if row is not None else False,
        },
        "owner_ids": owner_ids(group),
    }
