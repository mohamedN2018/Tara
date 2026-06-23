"""Visibility resolution for profiles.

Combines: self-check, block read-model + authoritative Graph block flag, and
friendship (from Graph) to decide profile-level and per-field visibility.
Blocked either way => the profile is treated as not found (doc 02 / brief §6).
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Q

from .clients import Relationship, get_relationship
from .models import CONTROLLABLE_FIELDS, BlockedPair, UserProfile, Visibility


@dataclass(frozen=True)
class ViewerContext:
    is_self: bool
    are_friends: bool
    blocked: bool
    degraded: bool


def resolve_context(viewer_id: str, profile: UserProfile) -> ViewerContext:
    if str(viewer_id) == str(profile.account_id):
        return ViewerContext(is_self=True, are_friends=True, blocked=False, degraded=False)

    local_block = BlockedPair.objects.filter(
        Q(blocker_id=viewer_id, blocked_id=profile.account_id)
        | Q(blocker_id=profile.account_id, blocked_id=viewer_id)
    ).exists()

    rel: Relationship = get_relationship(str(viewer_id), str(profile.account_id))
    return ViewerContext(
        is_self=False,
        are_friends=rel.are_friends,
        blocked=local_block or rel.blocked_either_way,
        degraded=rel.degraded,
    )


def _level_visible(level: str, ctx: ViewerContext) -> bool:
    if ctx.is_self:
        return True
    if level == Visibility.PUBLIC:
        return True
    if level == Visibility.FRIENDS:
        return ctx.are_friends
    # PRIVATE / CUSTOM (custom audiences not yet evaluated) -> hidden to others
    return False


def profile_visible(profile: UserProfile, ctx: ViewerContext) -> bool:
    """Whether the viewer may see the profile beyond the minimal public card."""
    return _level_visible(profile.visibility, ctx)


def field_visibility_map(profile: UserProfile) -> dict[str, str]:
    overrides = {fp.field_key: fp.visibility for fp in profile.field_privacy.all()}
    return {f: overrides.get(f, Visibility.PUBLIC) for f in CONTROLLABLE_FIELDS}


def visible_fields(profile: UserProfile, ctx: ViewerContext) -> set[str]:
    levels = field_visibility_map(profile)
    return {field for field, level in levels.items() if _level_visible(level, ctx)}
