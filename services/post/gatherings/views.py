"""Events HTTP API (``/api/v1/events/``).

Every view may call graph or media before writing, so they run outside
ATOMIC_REQUESTS and each write path opens its own transaction (roadmap 3.3).
A hidden event is 404 everywhere.
"""

from __future__ import annotations

from django.db import transaction
from django.utils.decorators import method_decorator
from drf_spectacular.utils import OpenApiParameter, extend_schema
from posts.models import IdempotencyRecord
from posts.throttling import ReportThrottle
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tara_common.pagination import CursorPagination
from tara_common.responses import data_response
from tara_resilience.idempotency import idempotent

from . import services
from .serializers import (
    AttendeeSerializer,
    GatheringCreateSerializer,
    GatheringReportSerializer,
    GatheringSerializer,
    InviteeSerializer,
    InviteSerializer,
    RSVPSerializer,
)


def _me(request: Request) -> str:
    return request.user.account_id


def _serialize(viewer_id: str, gatherings: list) -> list:
    context = {"viewer_id": viewer_id, "viewer_state": services.viewer_state(viewer_id, gatherings)}
    return GatheringSerializer(gatherings, many=True, context=context).data


def _one(viewer_id: str, gathering) -> dict:
    return _serialize(viewer_id, [gathering])[0]


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class GatheringListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter("scope", str, enum=list(services.SCOPES)),
            OpenApiParameter("q", str, description="Title search (visible events only)"),
        ],
        responses={200: GatheringSerializer(many=True)},
        tags=["events"],
    )
    def get(self, request: Request) -> Response:
        """``upcoming`` (default), ``hosting``, ``going`` (going or interested),
        ``invited``: soonest first. ``past``: newest first. Keyset-paginated, and
        filtered by visibility before paging, so pages are full."""
        queryset = services.list_queryset(
            _me(request),
            request.query_params.get("scope") or "upcoming",
            q=request.query_params.get("q") or "",
        )
        paginator = CursorPagination()
        page = paginator.paginate_queryset(queryset, request)
        return paginator.get_paginated_response(_serialize(_me(request), page))

    @extend_schema(
        request=GatheringCreateSerializer, responses={201: GatheringSerializer}, tags=["events"]
    )
    def post(self, request: Request) -> Response:
        serializer = GatheringCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = dict(serializer.validated_data)

        def handler() -> Response:
            g = services.create_gathering(_me(request), **values)
            return data_response(_one(_me(request), g), status=status.HTTP_201_CREATED)

        return idempotent(IdempotencyRecord, request, handler)


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class GatheringDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: GatheringSerializer}, tags=["events"])
    def get(self, request: Request, gathering_id) -> Response:
        g = services.get_gathering(_me(request), gathering_id)
        return data_response(_one(_me(request), g))

    @extend_schema(
        request=GatheringCreateSerializer, responses={200: GatheringSerializer}, tags=["events"]
    )
    def patch(self, request: Request, gathering_id) -> Response:
        """Host only (404 for anyone else). Changing the time or place notifies
        everyone going or interested."""
        serializer = GatheringCreateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        g = services.edit_gathering(_me(request), gathering_id, dict(serializer.validated_data))
        return data_response(_one(_me(request), g))

    @extend_schema(responses={204: None}, tags=["events"])
    def delete(self, request: Request, gathering_id) -> Response:
        services.delete_gathering(_me(request), gathering_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class GatheringCancelView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: GatheringSerializer}, tags=["events"])
    def post(self, request: Request, gathering_id) -> Response:
        """Host only. Everyone going or interested is notified."""
        g = services.cancel_gathering(_me(request), gathering_id)
        return data_response(_one(_me(request), g))


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class GatheringRSVPView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=RSVPSerializer, responses={200: GatheringSerializer}, tags=["events"])
    def post(self, request: Request, gathering_id) -> Response:
        """Going, interested or not going. 409 ``event_full`` when the last seat is
        taken, ``event_cancelled`` / ``event_ended``; 400 ``host_cannot_rsvp``."""
        serializer = RSVPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        g = services.rsvp(_me(request), gathering_id, serializer.validated_data["status"])
        return data_response(_one(_me(request), g))

    @extend_schema(responses={200: GatheringSerializer}, tags=["events"])
    def delete(self, request: Request, gathering_id) -> Response:
        """Take the answer back."""
        g = services.withdraw_rsvp(_me(request), gathering_id)
        return data_response(_one(_me(request), g))


@method_decorator(transaction.non_atomic_requests, name="dispatch")  # reads; calls graph
class GatheringAttendeesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[OpenApiParameter("status", str, enum=list(services.ATTENDEE_STATES))],
        responses={200: AttendeeSerializer(many=True)},
        tags=["events"],
    )
    def get(self, request: Request, gathering_id) -> Response:
        """People by answer, newest first. ``not_going`` and ``invited`` are for the
        host only (403). Accounts blocked either way are left out."""
        state = request.query_params.get("status") or "going"
        queryset = services.attendees_queryset(_me(request), gathering_id, state)
        paginator = CursorPagination()
        page = paginator.paginate_queryset(queryset, request)
        serializer = InviteeSerializer if state == "invited" else AttendeeSerializer
        return paginator.get_paginated_response(serializer(page, many=True).data)


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class GatheringInviteView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=InviteSerializer, responses={200: None}, tags=["events"])
    def post(self, request: Request, gathering_id) -> Response:
        """Host only; friends only (400 ``invite_not_friend``). Returns who was newly
        invited."""
        serializer = InviteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new = services.invite(
            _me(request), gathering_id, [str(a) for a in serializer.validated_data["account_ids"]]
        )
        return data_response({"invited": new})


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class GatheringReportView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [*APIView.throttle_classes, ReportThrottle]

    @extend_schema(request=GatheringReportSerializer, responses={202: None}, tags=["events"])
    def post(self, request: Request, gathering_id) -> Response:
        """404 if the reporter cannot see the event; a repeat report is accepted once."""
        serializer = GatheringReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.report(_me(request), gathering_id, serializer.validated_data["reason"])
        return data_response({"detail": "reported"}, status=status.HTTP_202_ACCEPTED)
