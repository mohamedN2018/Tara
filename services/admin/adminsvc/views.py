"""Admin HTTP API. Every staff endpoint requires a capability (roadmap 8.12).

A public flag-read endpoint (any authenticated service/user) lets clients gate
features. With the default role map each capability below is held by exactly
the roles the old ``IsAdmin`` check allowed, so behaviour is unchanged until an
admin edits the matrix.
"""

from __future__ import annotations

from django.http import StreamingHttpResponse
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from tara_common.exceptions import TaraAPIError
from tara_common.pagination import CursorPagination
from tara_common.permissions import HasCapability
from tara_common.responses import data_response
from tara_common.throttling import ReadThrottle

from . import audit, identity_client, services
from .models import FeatureFlag
from .serializers import (
    AuditEntrySerializer,
    AuditFilterSerializer,
    CapabilityMatrixUpdateSerializer,
    FeatureFlagSerializer,
    FeatureFlagWriteSerializer,
    RoleSerializer,
)

FLAG_KEY_MAX_LENGTH = FeatureFlag._meta.get_field("key").max_length


def _me(request: Request) -> str:
    return request.user.account_id


class FeatureFlagsView(APIView):
    """GET is readable by any authenticated caller; PATCH requires admin.flags.manage."""

    def get_permissions(self):
        if self.request.method == "PATCH":
            return [HasCapability("admin.flags.manage")]
        return [IsAuthenticated()]

    @extend_schema(responses={200: FeatureFlagSerializer(many=True)}, tags=["admin"])
    def get(self, request: Request) -> Response:
        return data_response(FeatureFlagSerializer(FeatureFlag.objects.all(), many=True).data)


class FeatureFlagDetailView(APIView):
    def get_permissions(self):
        if self.request.method == "PATCH":
            return [HasCapability("admin.flags.manage")]
        return [IsAuthenticated()]

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
        if len(key) > FLAG_KEY_MAX_LENGTH:
            raise TaraAPIError(
                f"A flag key is at most {FLAG_KEY_MAX_LENGTH} characters.",
                code="validation_error",
                http_status_code=400,
            )
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
    """Accounts holding roles, and grants. Identity stores and audits them."""

    permission_classes = [HasCapability("admin.roles.manage")]

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
    permission_classes = [HasCapability("admin.roles.manage")]

    @extend_schema(responses={200: None}, tags=["admin"])
    def get(self, request: Request) -> Response:
        email = request.query_params.get("email", "").strip()
        if not email:
            raise TaraAPIError("email is required.", code="validation_error", http_status_code=400)
        return data_response(identity_client.lookup(email))


class AccountRolesView(APIView):
    permission_classes = [HasCapability("admin.roles.manage")]

    @extend_schema(responses={200: None}, tags=["admin"])
    def get(self, request: Request, account_id: str) -> Response:
        return data_response(identity_client.account_roles(str(account_id)))


class CapabilityMatrixView(APIView):
    """The role x capability matrix. Identity stores it and emits the audit events."""

    permission_classes = [HasCapability("admin.capabilities.manage")]

    @extend_schema(responses={200: None}, tags=["admin"])
    def get(self, request: Request) -> Response:
        return data_response(identity_client.capability_matrix())

    @extend_schema(request=CapabilityMatrixUpdateSerializer, responses={200: None}, tags=["admin"])
    def put(self, request: Request) -> Response:
        serializer = CapabilityMatrixUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        changes = [dict(c) for c in serializer.validated_data["changes"]]
        return data_response(identity_client.update_capabilities(changes, _me(request)))


class ServiceHealthView(APIView):
    """The latest beat-polled readiness of every service (never polls per request)."""

    permission_classes = [HasCapability("admin.monitor.view")]

    @extend_schema(responses={200: None}, tags=["admin"])
    def get(self, request: Request) -> Response:
        return data_response(services.latest_health())


class MonitorView(APIView):
    """Service health tiles and platform counters, both from beat tasks (8.11)."""

    permission_classes = [HasCapability("admin.monitor.view")]

    @extend_schema(responses={200: None}, tags=["admin"])
    def get(self, request: Request) -> Response:
        return data_response(services.monitor())


_AUDIT_FILTERS = [
    OpenApiParameter("actor", str, description="An account id, or 'system'"),
    OpenApiParameter("action", str),
    OpenApiParameter("target_type", str),
    OpenApiParameter("target_id", str),
    OpenApiParameter("since", str, description="ISO 8601, inclusive"),
    OpenApiParameter("until", str, description="ISO 8601, exclusive"),
]


def _audit_filters(request: Request) -> dict:
    serializer = AuditFilterSerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


class AuditPagination(CursorPagination):
    page_size = 50


class AuditListView(APIView):
    permission_classes = [HasCapability("admin.audit.view")]

    @extend_schema(
        parameters=_AUDIT_FILTERS, responses={200: AuditEntrySerializer(many=True)}, tags=["admin"]
    )
    def get(self, request: Request) -> Response:
        paginator = AuditPagination()
        page = paginator.paginate_queryset(audit.filtered(_audit_filters(request)), request)
        return paginator.get_paginated_response(AuditEntrySerializer(page, many=True).data)


class AuditExportView(APIView):
    """CSV of the filtered audit log, streamed, capped, and itself audited."""

    permission_classes = [HasCapability("admin.audit.export")]
    throttle_classes = [ReadThrottle, ScopedRateThrottle]
    throttle_scope = "audit_export"

    @extend_schema(parameters=_AUDIT_FILTERS, responses={(200, "text/csv"): str}, tags=["admin"])
    def get(self, request: Request) -> StreamingHttpResponse:
        filters = _audit_filters(request)
        queryset = audit.filtered(filters)
        cap = audit.export_cap()
        truncated = queryset[cap : cap + 1].exists()
        # Commits with the request (ATOMIC_REQUESTS) before the first byte goes
        # out: an export that starts is always on the record.
        audit.record(
            "audit.exported",
            actor_id=_me(request),
            target_type="audit_log",
            request_id=getattr(request, "request_id", ""),
            detail={
                **{
                    k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in filters.items()
                },
                "row_cap": cap,
                "truncated": truncated,
            },
        )
        response = StreamingHttpResponse(
            audit.stream_csv(queryset, cap), content_type="text/csv; charset=utf-8"
        )
        stamp = timezone.now().strftime("%Y%m%d-%H%M%S")
        response["Content-Disposition"] = f'attachment; filename="tara-audit-{stamp}.csv"'
        response["Cache-Control"] = "no-store"
        response["X-Export-Truncated"] = "true" if truncated else "false"
        response["X-Export-Row-Cap"] = str(cap)
        return response
