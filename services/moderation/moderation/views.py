"""Moderation HTTP API. Queue/action endpoints require moderation capabilities (8.12)."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tara_common.exceptions import TaraAPIError
from tara_common.pagination import CursorPagination
from tara_common.permissions import HasCapability
from tara_common.responses import data_response

from . import services
from .models import Appeal
from .serializers import (
    ActionSerializer,
    AppealCreateSerializer,
    AppealResolveSerializer,
    AppealSerializer,
    CaseSerializer,
    ManualReportSerializer,
    ReportSerializer,
)
from .throttling import ReportThrottle


def _me(request: Request) -> str:
    return request.user.account_id


class QueuePagination(CursorPagination):
    """Most cases share a report count, so walking the ties needs a high offset cap."""

    offset_cutoff = 100_000


def _paginate(request, queryset, serializer_cls, paginator_cls=CursorPagination):
    paginator = paginator_cls()
    page = paginator.paginate_queryset(queryset, request)
    return paginator.get_paginated_response(serializer_cls(page, many=True).data)


class ReportsView(APIView):
    permission_classes = [HasCapability("moderation.case.view")]

    @extend_schema(responses={200: ReportSerializer(many=True)}, tags=["moderation"])
    def get(self, request: Request) -> Response:
        from .models import Report

        return _paginate(request, Report.objects.order_by("-created_at"), ReportSerializer)


class ManualReportView(APIView):
    """Any authenticated user can report a user or a page."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [*APIView.throttle_classes, ReportThrottle]

    @extend_schema(request=ManualReportSerializer, responses={202: None}, tags=["moderation"])
    def post(self, request: Request) -> Response:
        serializer = ManualReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        v = serializer.validated_data
        target_id = str(v["target_id"])
        if v["target_type"] == "user" and target_id == str(_me(request)):
            raise TaraAPIError(
                "You cannot report yourself.", code="validation_error", http_status_code=400
            )
        services.ingest_report(
            reporter_id=_me(request),
            target_type=v["target_type"],
            target_id=target_id,
            reason=v["reason"],
            # A reported account owns its own case. A page's owner lives in
            # profile, so page cases stay unappealable until a report names it.
            owner_id=target_id if v["target_type"] == "user" else None,
        )
        return data_response({"detail": "reported"}, status=status.HTTP_202_ACCEPTED)


class CasesView(APIView):
    permission_classes = [HasCapability("moderation.case.view")]

    @extend_schema(responses={200: CaseSerializer(many=True)}, tags=["moderation"])
    def get(self, request: Request) -> Response:
        return _paginate(
            request,
            services.queue(request.query_params.get("state")),
            CaseSerializer,
            QueuePagination,
        )


class CaseAssignView(APIView):
    permission_classes = [HasCapability("moderation.case.act")]

    @extend_schema(responses={200: CaseSerializer}, tags=["moderation"])
    def post(self, request: Request, case_id: str) -> Response:
        return data_response(CaseSerializer(services.assign(case_id, _me(request))).data)


class CaseActionView(APIView):
    permission_classes = [HasCapability("moderation.case.act")]

    @extend_schema(request=ActionSerializer, responses={200: None}, tags=["moderation"])
    def post(self, request: Request, case_id: str) -> Response:
        serializer = ActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.take_action(
            case_id,
            _me(request),
            serializer.validated_data["action"],
            serializer.validated_data["reason"],
        )
        return data_response({"detail": "action recorded"})


class CaseAppealView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=AppealCreateSerializer, responses={201: None}, tags=["moderation"])
    def post(self, request: Request, case_id: str) -> Response:
        serializer = AppealCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.file_appeal(case_id, _me(request), serializer.validated_data["text"])
        return data_response({"detail": "appeal filed"}, status=status.HTTP_201_CREATED)


class AppealsView(APIView):
    """The appeal queue: without it a moderator has no way to find an appeal's id."""

    permission_classes = [HasCapability("moderation.appeal.view")]

    @extend_schema(responses={200: AppealSerializer(many=True)}, tags=["moderation"])
    def get(self, request: Request) -> Response:
        status_filter = request.query_params.get("status")
        if status_filter and status_filter not in Appeal.Status.values:
            raise TaraAPIError("Invalid status.", code="validation_error", http_status_code=400)
        return _paginate(request, services.appeals(status_filter), AppealSerializer)


class AppealResolveView(APIView):
    permission_classes = [HasCapability("moderation.appeal.resolve")]

    @extend_schema(request=AppealResolveSerializer, responses={200: None}, tags=["moderation"])
    def post(self, request: Request, appeal_id: str) -> Response:
        serializer = AppealResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.resolve_appeal(appeal_id, _me(request), serializer.validated_data["status"])
        return data_response({"detail": "appeal resolved"})
