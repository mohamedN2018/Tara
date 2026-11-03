"""The group role hierarchy and its granular permissions, checked on the backend.

``owner > admin > moderator > member``. Each permission names the lowest role
that holds it. Acting on another member (remove, ban, change role) also needs a
higher rank than theirs; owners are peers and may act on each other, as long as
one owner remains (the last owner can never leave, be demoted, removed or banned).
"""

from __future__ import annotations

from .models import Role

RANK = {Role.MEMBER: 1, Role.MODERATOR: 2, Role.ADMIN: 3, Role.OWNER: 4}

# permission -> lowest role that has it
PERMISSIONS: dict[str, str] = {
    "post": Role.MEMBER,
    "invite": Role.MEMBER,
    "approve_requests": Role.MODERATOR,
    "approve_posts": Role.MODERATOR,
    "moderate": Role.MODERATOR,  # delete posts and comments, remove and ban members
    "pin": Role.MODERATOR,
    "view_reports": Role.MODERATOR,
    "edit": Role.ADMIN,
    "change_privacy": Role.ADMIN,
    "manage_rules": Role.ADMIN,
    "change_roles": Role.ADMIN,
    "delete": Role.OWNER,
}


def rank(role: str | None) -> int:
    return RANK.get(role, 0) if role else 0


def has(role: str | None, permission: str) -> bool:
    """Whether an active member with ``role`` holds ``permission``."""
    return rank(role) >= RANK[PERMISSIONS[permission]]


def can_act_on(actor_role: str | None, target_role: str | None) -> bool:
    """Remove, ban or re-role someone: a higher rank, or owner on owner."""
    if actor_role == Role.OWNER:
        return True
    return rank(actor_role) > rank(target_role)


def can_assign(actor_role: str | None, new_role: str) -> bool:
    """Owners give any role (more owners too); others only roles below their own."""
    if actor_role == Role.OWNER:
        return True
    return rank(new_role) < rank(actor_role)


def capabilities(role: str | None) -> dict[str, bool]:
    return {name: has(role, name) for name in PERMISSIONS}
