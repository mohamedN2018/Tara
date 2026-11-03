"""Service-to-service API. Not routed by the gateway.

Identity owns roles: the Admin service changes them here, and access tokens read
them at issue time, so a change reaches the ``roles`` claim on the next refresh.

Caller-specific secrets (roadmap 1.0d). Every service holds the shared
``INTERNAL_JWT_SECRET``, so a token signed with it proves nothing about the
caller, whatever its ``iss`` says. These endpoints grant roles and list staff,
so they accept only a token signed with a secret that identity shares with one
named caller (picked by the token's ``iss``), issued by that caller, for the
``identity.roles`` audience. The shared secret is never tried here.
"""

from __future__ import annotations

import logging

import jwt
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tara_common.auth import verify_internal_token
from tara_common.exceptions import TaraAPIError
from tara_common.responses import data_response

from .events import emit_security_event
from .models import Account, AccountRole
from .tokens import bridged_roles, roles_for

logger = logging.getLogger("tara.identity.internal")

MAX_ROLE_HOLDERS = 200
ROLES_AUDIENCE = "identity.roles"

# Caller (the token's ``iss``) -> the setting with the secret that identity shares
# with that caller alone. A new caller (notification in 2.19, moderation in 8.4)
# gets its own secret here and is allowed only on the views it needs.
CALLER_SECRET_SETTINGS = {"admin": "ADMIN_IDENTITY_SECRET"}


def _invalid_token() -> TaraAPIError:
    return TaraAPIError("Invalid internal token.", code="unauthenticated", http_status_code=401)


def _caller_secret(caller: str) -> str | None:
    setting = CALLER_SECRET_SETTINGS.get(caller)
    secret = (getattr(settings, setting, "") or "") if setting else ""
    if not secret:
        logger.error("no secret configured for internal caller", extra={"caller": caller})
        return None
    if secret == getattr(settings, "TARA_INTERNAL_JWT_SECRET", None):
        # Every service could sign with it, which would undo the whole point.
        logger.error("caller secret equals the shared internal secret", extra={"caller": caller})
        return None
    return secret


def _require_internal(request: Request, *, callers: tuple[str, ...], audience: str) -> str:
    """Return the verified caller, or raise 401. Fails closed on any doubt."""
    parts = request.META.get("HTTP_AUTHORIZATION", "").split()
    if len(parts) != 2 or parts[0] != "Bearer":
        raise TaraAPIError("Internal auth required.", code="unauthenticated", http_status_code=401)
    token = parts[1]
    try:
        # The claimed caller only selects which key to try. The signature made with
        # that caller's own secret, and the issuer check, are what prove it.
        claimed = jwt.decode(token, options={"verify_signature": False}).get("iss")
    except jwt.PyJWTError as exc:
        raise _invalid_token() from exc
    if not isinstance(claimed, str) or claimed not in callers:
        logger.warning(
            "internal token from a caller not allowed here", extra={"path": request.path}
        )
        raise _invalid_token()
    secret = _caller_secret(claimed)
    if secret is None:
        raise _invalid_token()
    try:
        verify_internal_token(
            token, secret=secret, expected_issuer=claimed, expected_audience=audience
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "internal token rejected", extra={"caller": claimed, "reason": type(exc).__name__}
        )
        raise _invalid_token() from exc
    return claimed


def _account_data(account: Account) -> dict:
    return {
        "account_id": str(account.id),
        "email": account.email,
        "roles": roles_for(account),
        # From is_staff / is_superuser: they can't be revoked through the role API.
        "bridged_roles": bridged_roles(account),
    }


def _get_account(account_id) -> Account:
    account = Account.objects.filter(id=account_id).first()
    if account is None:
        raise TaraAPIError("Account not found.", code="not_found", http_status_code=404)
    return account


class _RoleSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=AccountRole.Role.values)
    actor_id = serializers.UUIDField()


class _InternalView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []
    # Role grants, account lookup and staff lists: only admin may call them.
    internal_callers: tuple[str, ...] = ("admin",)
    internal_audience = ROLES_AUDIENCE

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        _require_internal(request, callers=self.internal_callers, audience=self.internal_audience)


class AccountLookupView(_InternalView):
    def get(self, request: Request) -> Response:
        email = request.query_params.get("email", "").strip()
        account = Account.objects.filter(email__iexact=email).first() if email else None
        if account is None:
            raise TaraAPIError("Account not found.", code="not_found", http_status_code=404)
        return data_response(_account_data(account))


class RoleHoldersView(_InternalView):
    def get(self, request: Request) -> Response:
        accounts = (
            Account.objects.filter(
                Q(role_grants__isnull=False) | Q(is_staff=True) | Q(is_superuser=True)
            )
            .distinct()
            .prefetch_related("role_grants")
            .order_by("email")[:MAX_ROLE_HOLDERS]
        )
        return data_response([_account_data(a) for a in accounts])


class AccountRolesView(_InternalView):
    def get(self, request: Request, account_id: str) -> Response:
        return data_response(_account_data(_get_account(account_id)))

    def post(self, request: Request, account_id: str) -> Response:
        serializer = _RoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        role, actor = serializer.validated_data["role"], serializer.validated_data["actor_id"]
        account = _get_account(account_id)
        with transaction.atomic():
            _, created = AccountRole.objects.get_or_create(
                account=account, role=role, defaults={"granted_by": actor}
            )
            if created:
                emit_security_event(
                    account, "role_granted", {"role": role, "granted_by": str(actor)}
                )
        return data_response(_account_data(account), status=201)

    def delete(self, request: Request, account_id: str) -> Response:
        serializer = _RoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        role, actor = serializer.validated_data["role"], serializer.validated_data["actor_id"]
        account = _get_account(account_id)
        with transaction.atomic():
            deleted, _ = AccountRole.objects.filter(account=account, role=role).delete()
            if deleted:
                emit_security_event(
                    account, "role_revoked", {"role": role, "revoked_by": str(actor)}
                )
        return data_response(_account_data(account))
