"""Moderation HTTP API. Queue/action endpoints require the moderator role (RBAC)."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tara_common.pagination import CursorPagination
from tara_common.permissions import IsModerator
from tara_common.responses import data_response

from . import services
from .serializers import (
    ActionSerializer,
    AppealCreateSerializer,
    AppealResolveSerializer,
    CaseSerializer,
    ManualReportSerializer,
    ReportSerializer,
)


def _me(request: Request) -> str:
    return request.user.account_id


def _paginate(request, queryset, serializer_cls):
    paginator = CursorPagination()
    page = paginator.paginate_queryset(queryset, request)
    return paginator.get_paginated_response(serializer_cls(page, many=True).data)


class ReportsView(APIView):
    permission_classes = [IsModerator]

    @extend_schema(responses={200: ReportSerializer(many=True)}, tags=["moderation"])
    def get(self, request: Request) -> Response:
        from .models import Report

        return _paginate(request, Report.objects.order_by("-created_at"), ReportSerializer)


class ManualReportView(APIView):
    """Any authenticated user can file a report (e.g. reporting a user/page)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=ManualReportSerializer, responses={202: None}, tags=["moderation"])
    def post(self, request: Request) -> Response:
        serializer = ManualReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        v = serializer.validated_data
        services.ingest_report(
            reporter_id=_me(request),
            target_type=v["target_type"],
            target_id=v["target_id"],
            reason=v["reason"],
        )
        return data_response({"detail": "reported"}, status=status.HTTP_202_ACCEPTED)


class CasesView(APIView):
    permission_classes = [IsModerator]

    @extend_schema(responses={200: CaseSerializer(many=True)}, tags=["moderation"])
    def get(self, request: Request) -> Response:
        return _paginate(request, services.queue(request.query_params.get("state")), CaseSerializer)


class CaseAssignView(APIView):
    permission_classes = [IsModerator]

    @extend_schema(responses={200: CaseSerializer}, tags=["moderation"])
    def post(self, request: Request, case_id: str) -> Response:
        return data_response(CaseSerializer(services.assign(case_id, _me(request))).data)


class CaseActionView(APIView):
    permission_classes = [IsModerator]

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


class AppealResolveView(APIView):
    permission_classes = [IsModerator]

    @extend_schema(request=AppealResolveSerializer, responses={200: None}, tags=["moderation"])
    def post(self, request: Request, appeal_id: str) -> Response:
        serializer = AppealResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.resolve_appeal(appeal_id, _me(request), serializer.validated_data["status"])
        return data_response({"detail": "appeal resolved"})
