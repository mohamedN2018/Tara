"""Feed API: the viewer's home feed in four modes, plus hide and snooze (2A, 1.7)."""

from __future__ import annotations

from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from tara_common.pagination import CursorPagination
from tara_common.responses import data_response

from . import feedback, ranking, services
from .serializers import (
    AuthorSnoozeSerializer,
    FeedItemSerializer,
    HideRequestSerializer,
    PostHideSerializer,
    SnoozeRequestSerializer,
)


class FeedCursorPagination(CursorPagination):
    ordering = "-post_created_at"


class SnoozeCursorPagination(CursorPagination):
    ordering = "-snoozed_at"


def _mode(request) -> str:
    mode = request.query_params.get("mode") or services.DEFAULT_MODE
    if mode not in services.MODES:
        raise ValidationError({"mode": [f"Must be one of: {', '.join(services.MODES)}."]})
    return mode


def _page_size(request) -> int:
    try:
        size = int(request.query_params.get("limit") or CursorPagination.page_size)
    except ValueError:
        size = CursorPagination.page_size
    return max(1, min(size, CursorPagination.max_page_size))


class HomeFeedView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = FeedItemSerializer
    pagination_class = FeedCursorPagination

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "mode", OpenApiTypes.STR, enum=list(services.MODES), default=services.DEFAULT_MODE
            )
        ],
        responses={200: FeedItemSerializer(many=True)},
        tags=["feed"],
    )
    def get(self, request, *args, **kwargs):
        mode = _mode(request)
        if mode == "for_you":
            response = self._ranked(request)
        else:
            response = super().get(request, *args, **kwargs)
        if response.status_code == 200:
            response.data["mode"] = mode
            # Blend one sponsored slot into the first page; never block organic content.
            if request.query_params.get("cursor") is None:
                from .ads_client import feed_sponsored

                response.data["sponsored"] = feed_sponsored(request.user.account_id)
        return response

    def _ranked(self, request) -> Response:
        viewer, size = request.user.account_id, _page_size(request)
        token = request.query_params.get("cursor")
        try:
            if token is None:
                page = ranking.first_page(viewer, size, timezone.now())
            else:
                page = ranking.next_page(viewer, token, size)
        except ranking.InvalidCursor as exc:
            raise NotFound("Invalid cursor.") from exc
        return Response(
            {
                "data": FeedItemSerializer(page.items, many=True).data,
                "page": {
                    "next_cursor": page.next_cursor,
                    "prev_cursor": None,
                    "has_more": page.has_more,
                    "fallback": page.fallback,
                },
            }
        )

    def get_queryset(self):
        return services.home_feed(self.request.user.account_id, _mode(self.request))


class HideView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=HideRequestSerializer, responses={201: PostHideSerializer}, tags=["feed"]
    )
    def post(self, request):
        body = HideRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        hide = feedback.hide_post(
            request.user.account_id, body.validated_data["post_id"], body.validated_data["reason"]
        )
        return data_response(PostHideSerializer(hide).data, status=status.HTTP_201_CREATED)


class UnhideView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={204: None}, tags=["feed"])
    def delete(self, request, post_id):
        feedback.unhide_post(request.user.account_id, post_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class SnoozeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=SnoozeRequestSerializer, responses={201: AuthorSnoozeSerializer}, tags=["feed"]
    )
    def post(self, request):
        body = SnoozeRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        snooze = feedback.snooze_author(request.user.account_id, body.validated_data["author_id"])
        return data_response(AuthorSnoozeSerializer(snooze).data, status=status.HTTP_201_CREATED)


class UnsnoozeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={204: None}, tags=["feed"])
    def delete(self, request, author_id):
        feedback.unsnooze_author(request.user.account_id, author_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class SnoozeListView(generics.ListAPIView):
    """Active snoozes, newest first (for the settings screen)."""

    permission_classes = [IsAuthenticated]
    serializer_class = AuthorSnoozeSerializer
    pagination_class = SnoozeCursorPagination

    @extend_schema(tags=["feed"])
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        return feedback.active_snoozes(self.request.user.account_id).order_by("-snoozed_at")
