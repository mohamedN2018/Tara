"""RBAC permission classes keyed off the access token's ``roles`` claim.

Roles are assigned in the Admin service's role registry and embedded into the
access token by Identity at issuance. Services enforce them locally — no
per-request call to Admin/Identity.
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
