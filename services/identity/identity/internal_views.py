"""Service-to-service API. Not routed by the gateway.

Identity owns roles: the Admin service changes them here, and access tokens read
them at issue time, so a change reaches the ``roles`` claim on the next refresh.
"""

from __future__ import annotations

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

MAX_ROLE_HOLDERS = 200


def _require_internal(request: Request) -> None:
    parts = request.META.get("HTTP_AUTHORIZATION", "").split()
    if len(parts) != 2 or parts[0] != "Bearer":
        raise TaraAPIError("Internal auth required.", code="unauthenticated", http_status_code=401)
    try:
        verify_internal_token(parts[1], expected_audience="identity-internal")
    except Exception as exc:  # noqa: BLE001
        raise TaraAPIError(
            "Invalid internal token.", code="unauthenticated", http_status_code=401
        ) from exc


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

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        _require_internal(request)


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
