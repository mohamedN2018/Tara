"""Admin HTTP API (RBAC: admin). Feature flags, roles, service-health overview.

A public flag-read endpoint (any authenticated service/user) lets clients gate
features; everything else requires the admin role.
"""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tara_common.exceptions import TaraAPIError
from tara_common.permissions import IsAdmin
from tara_common.responses import data_response

from . import identity_client, services
from .models import FeatureFlag
from .serializers import FeatureFlagSerializer, FeatureFlagWriteSerializer, RoleSerializer


def _me(request: Request) -> str:
    return request.user.account_id


class FeatureFlagsView(APIView):
    """GET is readable by any authenticated caller; PATCH requires admin."""

    def get_permissions(self):
        return [IsAdmin()] if self.request.method == "PATCH" else [IsAuthenticated()]

    @extend_schema(responses={200: FeatureFlagSerializer(many=True)}, tags=["admin"])
    def get(self, request: Request) -> Response:
        return data_response(FeatureFlagSerializer(FeatureFlag.objects.all(), many=True).data)


class FeatureFlagDetailView(APIView):
    def get_permissions(self):
        return [IsAdmin()] if self.request.method == "PATCH" else [IsAuthenticated()]

    @extend_schema(responses={200: FeatureFlagSerializer}, tags=["admin"])
    def get(self, request: Request, key: str) -> Response:
        flag = FeatureFlag.objects.filter(key=key).first()
        if flag is None:
            return data_response({"key": key, "enabled": False, "rollout_pct": 0})
        return data_response(FeatureFlagSerializer(flag).data)

    @extend_schema(
        request=FeatureFlagWriteSerializer, responses={200: FeatureFlagSerializer}, tags=["admin"]
    )
    def patch(self, request: Request, key: str) -> Response:
        serializer = FeatureFlagWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        v = serializer.validated_data
        flag = services.set_flag(
            key,
            enabled=v["enabled"],
            rollout_pct=v["rollout_pct"],
            description=v["description"],
            actor_id=_me(request),
        )
        return data_response(FeatureFlagSerializer(flag).data)


class RolesView(APIView):
    """Accounts holding roles, and grants. Identity stores them; this API audits them."""

    permission_classes = [IsAdmin]

    @extend_schema(responses={200: None}, tags=["admin"])
    def get(self, request: Request) -> Response:
        return data_response(identity_client.role_holders())

    @extend_schema(request=RoleSerializer, responses={201: None}, tags=["admin"])
    def post(self, request: Request) -> Response:
        serializer = RoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        account = services.grant_role(
            str(serializer.validated_data["account_id"]),
            serializer.validated_data["role"],
            _me(request),
        )
        return data_response(account, status=201)

    @extend_schema(request=RoleSerializer, responses={200: None}, tags=["admin"])
    def delete(self, request: Request) -> Response:
        serializer = RoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        account = services.revoke_role(
            str(serializer.validated_data["account_id"]),
            serializer.validated_data["role"],
            _me(request),
        )
        return data_response(account)


class RoleLookupView(APIView):
    permission_classes = [IsAdmin]

    @extend_schema(responses={200: None}, tags=["admin"])
    def get(self, request: Request) -> Response:
        email = request.query_params.get("email", "").strip()
        if not email:
            raise TaraAPIError("email is required.", code="validation_error", http_status_code=400)
        return data_response(identity_client.lookup(email))


class AccountRolesView(APIView):
    permission_classes = [IsAdmin]

    @extend_schema(responses={200: None}, tags=["admin"])
    def get(self, request: Request, account_id: str) -> Response:
        return data_response(identity_client.account_roles(str(account_id)))


class ServiceHealthView(APIView):
    permission_classes = [IsAdmin]

    @extend_schema(responses={200: None}, tags=["admin"])
    def get(self, request: Request) -> Response:
        results = services.service_health()
        overall = "ok" if all(r["status"] == "ready" for r in results) else "degraded"
        return data_response({"overall": overall, "services": results})
