"""RBAC permission classes keyed off the access token's ``roles`` and ``caps`` claims.

Identity owns roles (the Admin service changes them through Identity's internal
API) and embeds them in the access token at issuance. Services enforce them
locally: no per-request call to Admin or Identity.
"""

from __future__ import annotations

from rest_framework.permissions import BasePermission


class HasAnyRole(BasePermission):
    """Grant access if the user holds at least one of ``required_roles``."""

    required_roles: set[str] = set()
    message = "You do not have the required role for this action."

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)
        if not (user and user.is_authenticated):
            return False
        return bool(self.required_roles & getattr(user, "roles", set()))


class IsModerator(HasAnyRole):
    required_roles = {"moderator", "admin"}


class IsAdmin(HasAnyRole):
    required_roles = {"admin"}


class HasCapability(BasePermission):
    """Grant access if the token carries every one of the given capability keys.

    Use an instance: ``permission_classes = [HasCapability("moderation.case.act")]``.
    DRF instantiates each entry with no arguments, so ``__call__`` returns the
    instance itself. Keys come from the verified token (``TokenUser.capabilities``):
    the ``caps`` claim, or the role defaults for a token minted before it existed.
    A principal without capabilities (anonymous, service) is refused.
    """

    message = "You do not have the required capability for this action."

    def __init__(self, *capabilities: str) -> None:
        from .capabilities import is_capability

        unknown = [c for c in capabilities if not is_capability(c)]
        if not capabilities or unknown:
            # A typo would silently deny (or, in a list, silently narrow) access.
            raise ValueError(f"Unknown capability: {unknown or capabilities!r}")
        self.capabilities = frozenset(capabilities)

    def __call__(self) -> HasCapability:
        return self

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"HasCapability({', '.join(sorted(self.capabilities))})"

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)
        if not (user and user.is_authenticated):
            return False
        held = getattr(user, "capabilities", None) or frozenset()
        return self.capabilities <= held
