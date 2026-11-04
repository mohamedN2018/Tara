"""Admin HTTP API. Every staff endpoint requires a capability (roadmap 8.12).

A public flag-read endpoint (any authenticated service/user) lets clients gate
features. With the default role map each capability below is held by exactly
the roles the old ``IsAdmin`` check allowed, so behaviour is unchanged until an
admin edits the matrix.
"""

from __future__ import annotations

import uuid

from django.db import transaction
from django.http import StreamingHttpResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
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
from tara_common.throttling import ReadThrottle, WriteThrottle

from . import audit, identity_client, notices, services, users
from .models import FeatureFlag
from .serializers import (
    AuditEntrySerializer,
    AuditFilterSerializer,
    CapabilityMatrixUpdateSerializer,
    FeatureFlagSerializer,
    FeatureFlagWriteSerializer,
    ReasonSerializer,
    RoleSerializer,
    SuspendSerializer,
    SystemNoticeSerializer,
    SystemNoticeWriteSerializer,
    UserSearchSerializer,
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


# ---- user management console (8.6) -------------------------------------------
#
# These views call identity, profile and the counters before they write, so they
# do not run in ATOMIC_REQUESTS' transaction (05 §3.3, sync calls inside
# requests): each audit row opens and commits its own, before the response.

_non_atomic = method_decorator(transaction.non_atomic_requests, name="dispatch")


def _no_store(response: Response) -> Response:
    response["Cache-Control"] = "no-store"
    return response


def _idempotency_key(request: Request) -> str:
    """The client's key for this action (a retried dialog applies once), or a fresh one."""
    key = request.headers.get("Idempotency-Key", "").strip()
    if key and not (8 <= len(key) <= 90 and key.isprintable()):
        raise TaraAPIError(
            "Idempotency-Key must be 8 to 90 characters.",
            code="validation_error",
            http_status_code=400,
        )
    return f"admin:{key}" if key else f"admin:{uuid.uuid4().hex}"


@_non_atomic
class UserSearchView(APIView):
    """Accounts by email (exact or prefix), handle, name or account id."""

    permission_classes = [HasCapability("admin.users.view")]

    @extend_schema(
        parameters=[
            OpenApiParameter("q", str, required=True),
            OpenApiParameter("field", str, enum=list(users.SEARCH_FIELDS)),
            OpenApiParameter("cursor", str),
            OpenApiParameter("limit", int),
        ],
        responses={200: None},
        tags=["admin"],
    )
    def get(self, request: Request) -> Response:
        serializer = UserSearchSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        v = serializer.validated_data
        result = users.search(v["q"], field=v["field"], cursor=v.get("cursor"), limit=v["limit"])
        page = result["page"]
        return _no_store(
            Response(
                {
                    "data": result["data"],
                    "page": {
                        "next_cursor": page.get("next_cursor"),
                        "prev_cursor": page.get("prev_cursor"),
                        "has_more": bool(page.get("has_more")),
                    },
                    "field": result["field"],
                }
            )
        )


@_non_atomic
class UserDetailView(APIView):
    """One account's page. Every view is audited (``user.viewed``)."""

    permission_classes = [HasCapability("admin.users.view")]

    @extend_schema(responses={200: None}, tags=["admin"])
    def get(self, request: Request, account_id) -> Response:
        data = users.detail(str(account_id))
        users.record_view(str(account_id), _me(request))
        return _no_store(data_response(data))


@_non_atomic
class UserRevealView(APIView):
    """Full email, phone and sessions, after a typed reason is on the audit log."""

    permission_classes = [HasCapability("admin.users.reveal")]
    throttle_classes = [WriteThrottle, ScopedRateThrottle]
    throttle_scope = "user_reveal"

    @extend_schema(request=ReasonSerializer, responses={200: None}, tags=["admin"])
    def post(self, request: Request, account_id) -> Response:
        serializer = ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = users.reveal(str(account_id), _me(request), serializer.validated_data["reason"])
        return _no_store(data_response(data))


@_non_atomic
class UserSuspendView(APIView):
    permission_classes = [HasCapability("admin.users.suspend")]

    @extend_schema(request=SuspendSerializer, responses={201: None}, tags=["admin"])
    def post(self, request: Request, account_id) -> Response:
        serializer = SuspendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        v = serializer.validated_data
        result = users.suspend(
            str(account_id),
            _me(request),
            reason=v["reason"],
            until=v["until"],
            idempotency_key=_idempotency_key(request),
        )
        return data_response(result, status=201 if result.get("created") else 200)


@_non_atomic
class UserUnsuspendView(APIView):
    permission_classes = [HasCapability("admin.users.suspend")]

    @extend_schema(request=ReasonSerializer, responses={200: None}, tags=["admin"])
    def post(self, request: Request, account_id) -> Response:
        serializer = ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return data_response(
            users.unsuspend(
                str(account_id), _me(request), reason=serializer.validated_data["reason"]
            )
        )


@_non_atomic
class UserSignOutView(APIView):
    permission_classes = [HasCapability("admin.users.sign_out")]

    @extend_schema(responses={200: None}, tags=["admin"])
    def post(self, request: Request, account_id) -> Response:
        return data_response(users.sign_out_everywhere(str(account_id), _me(request)))


@_non_atomic
class UserResendVerificationView(APIView):
    permission_classes = [HasCapability("admin.users.resend_verification")]

    @extend_schema(responses={202: None}, tags=["admin"])
    def post(self, request: Request, account_id) -> Response:
        return data_response(users.resend_verification(str(account_id), _me(request)), status=202)


# ---- administrative notices (system.notice) -----------------------------------


@_non_atomic
class SystemNoticesView(APIView):
    """Send a notice to some accounts, and list what was sent (``admin.notices.send``)."""

    permission_classes = [HasCapability("admin.notices.send")]

    @extend_schema(responses={200: SystemNoticeSerializer(many=True)}, tags=["admin"])
    def get(self, request: Request) -> Response:
        paginator = CursorPagination()
        page = paginator.paginate_queryset(notices.sent(), request)
        return paginator.get_paginated_response(SystemNoticeSerializer(page, many=True).data)

    @extend_schema(
        request=SystemNoticeWriteSerializer, responses={201: SystemNoticeSerializer}, tags=["admin"]
    )
    def post(self, request: Request) -> Response:
        serializer = SystemNoticeWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        v = serializer.validated_data
        notice = notices.send(
            actor_id=_me(request), recipient_ids=v["recipient_ids"], body=v["body"]
        )
        return data_response(SystemNoticeSerializer(notice).data, status=201)
