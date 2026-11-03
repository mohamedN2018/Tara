"""Capability registry: what staff may do, by namespaced key (roadmap 8.1, 8.12).

Roles stay the unit that admins grant (identity's ``AccountRole``). A capability
is one thing a role allows, such as ``moderation.case.act``. Identity computes
an account's capabilities from its roles plus the per-role overrides it stores,
and mints them into the access token as the sorted ``caps`` claim. Services
check them locally with ``tara_common.permissions.HasCapability``.

Backward compatibility: a token minted before ``caps`` existed carries only
``roles``. Its capabilities are derived from those roles with the defaults
below, so every role check keeps its old meaning.

Precedence (ported from QTech ``access.services``): the locked ``admin`` role
always holds every capability and cannot be edited, so nobody can lock the
platform out of its own matrix editor; for other roles an override (grant or
revoke) wins over the default. ``IMPLIES`` adds what a capability needs to be
usable (acting on a case means seeing it), like QTech's "edit implies view".
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Capability:
    key: str

    @property
    def namespace(self) -> str:
        return self.key.split(".", 1)[0]


_KEYS = (
    # Moderation queue (service: moderation)
    "moderation.case.view",
    "moderation.case.act",
    "moderation.appeal.view",
    "moderation.appeal.resolve",
    # Ads (service: ads)
    "ads.review",
    # Admin console (service: admin)
    "admin.users.view",
    "admin.roles.manage",
    "admin.capabilities.manage",
    "admin.flags.manage",
    "admin.audit.view",
    "admin.audit.export",
    "admin.monitor.view",
)

CAPABILITIES: dict[str, Capability] = {key: Capability(key) for key in _KEYS}

ROLES = ("admin", "moderator", "ad_reviewer", "analyst")
# Holds every capability; the matrix refuses to edit it.
LOCKED_ROLES = frozenset({"admin"})

IMPLIES: dict[str, frozenset[str]] = {
    "moderation.case.act": frozenset({"moderation.case.view"}),
    "moderation.appeal.resolve": frozenset({"moderation.appeal.view"}),
    "admin.audit.export": frozenset({"admin.audit.view"}),
}

# Identical to the role checks these replace: IsModerator (moderator, admin),
# IsAdReviewer (ad_reviewer, admin), IsAdmin (admin). ``analyst`` had no check.
DEFAULT_ROLE_CAPABILITIES: dict[str, frozenset[str]] = {
    "admin": frozenset(CAPABILITIES),
    "moderator": frozenset(
        {
            "moderation.case.view",
            "moderation.case.act",
            "moderation.appeal.view",
            "moderation.appeal.resolve",
        }
    ),
    "ad_reviewer": frozenset({"ads.review"}),
    "analyst": frozenset(),
}


def is_capability(key: object) -> bool:
    return isinstance(key, str) and key in CAPABILITIES


def with_implied(capabilities: Iterable[str]) -> frozenset[str]:
    """Add every capability that the given ones imply (transitively)."""
    result = set(capabilities)
    pending = list(result)
    while pending:
        for implied in IMPLIES.get(pending.pop(), ()):
            if implied not in result:
                result.add(implied)
                pending.append(implied)
    return frozenset(result)


def role_capabilities(
    role: str, overrides: Mapping[tuple[str, str], bool] | None = None
) -> frozenset[str]:
    """Effective capabilities of one role: defaults, then overrides, then implies."""
    if role in LOCKED_ROLES:
        return frozenset(CAPABILITIES)
    caps = set(DEFAULT_ROLE_CAPABILITIES.get(role, frozenset()))
    for (override_role, key), granted in (overrides or {}).items():
        if override_role != role or key not in CAPABILITIES:
            continue
        if granted:
            caps.add(key)
        else:
            caps.discard(key)
    return with_implied(caps)


def capabilities_for_roles(
    roles: Iterable[str], overrides: Mapping[tuple[str, str], bool] | None = None
) -> frozenset[str]:
    """The union of the effective capabilities of every role held."""
    result: set[str] = set()
    for role in set(roles):
        result |= role_capabilities(role, overrides)
    return frozenset(result)


def capabilities_from_claims(claims: Mapping) -> frozenset[str]:
    """Capabilities carried by a verified access token.

    The ``caps`` claim wins when present (identity applied the overrides). A
    token from before ``caps`` existed gets the defaults for its ``roles``.
    """
    caps = claims.get("caps")
    if isinstance(caps, list | tuple):
        return frozenset(c for c in caps if isinstance(c, str))
    roles = claims.get("roles") or []
    if not isinstance(roles, list | tuple):
        return frozenset()
    return capabilities_for_roles(r for r in roles if isinstance(r, str))
