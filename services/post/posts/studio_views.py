"""Creator studio HTTP reads (track T8): summary, content library, planner.

All of them answer for the signed-in account only. Writes stay where they are:
drafts and scheduling under ``/posts/drafts/``, published posts under
``/posts/<id>/``.
"""

from __future__ import annotations

from django.db import transaction
from django.utils.decorators import method_decorator
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tara_common.pagination import CursorPagination

from . import studio
from .serializers import CommentSerializer, PostSerializer
from .views import _comments, _me, _serialize


# Serializing calls graph for the viewer's blocks: keep reads out of ATOMIC_REQUESTS.
@method_decorator(transaction.non_atomic_requests, name="dispatch")
class StudioSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["studio"])
    def get(self, request: Request) -> Response:
        """Lifetime totals over my published posts (posts, reactions, comments,
        shares, saves), my drafts and scheduled counts, and my top posts."""
        me = _me(request)
        data = studio.summary(me)
        data["top_posts"] = _serialize(me, studio.top_posts(me))
        return Response({"data": data})


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class StudioInsightsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["studio"])
    def get(self, request: Request) -> Response:
        """My published posts per type with their reactions, comments and
        shares, and my ten posts with the most interactions."""
        me = _me(request)
        top = studio.top_posts(me, studio.INSIGHTS_TOP_POSTS)
        return Response({"data": {"by_type": studio.by_type(me), "top_posts": _serialize(me, top)}})


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class StudioPublishedView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter("type", str, description="text, image, video, link, share or poll")
        ],
        responses={200: PostSerializer(many=True)},
        tags=["studio"],
    )
    def get(self, request: Request) -> Response:
        """My published posts (group posts included), newest first."""
        me = _me(request)
        queryset = studio.published_queryset(me, request.query_params.get("type") or None)
        paginator = CursorPagination()
        page = paginator.paginate_queryset(queryset, request)
        return paginator.get_paginated_response(_serialize(me, list(page)))


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class CalendarView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter("from", str, required=True, description="ISO date-time with offset"),
            OpenApiParameter("to", str, required=True, description="ISO date-time with offset"),
        ],
        responses={200: PostSerializer(many=True)},
        tags=["studio"],
    )
    def get(self, request: Request) -> Response:
        """My scheduled and published posts in ``[from, to)`` (at most 43 days),
        earliest first. ``meta.truncated`` is true past 300 posts."""
        me = _me(request)
        posts, truncated = studio.calendar(
            me, request.query_params.get("from"), request.query_params.get("to")
        )
        return Response({"data": _serialize(me, posts), "meta": {"truncated": truncated}})


# How much of the commented post the Engagement list shows next to each comment.
POST_EXCERPT = 140


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class StudioCommentsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: CommentSerializer(many=True)}, tags=["studio"])
    def get(self, request: Request) -> Response:
        """Other people's comments on my published posts, newest first, each
        with ``post_excerpt`` (the start of the post it is on)."""
        me = _me(request)
        paginator = CursorPagination()
        page = list(paginator.paginate_queryset(studio.recent_comments(me), request))
        data = _comments(me, page)
        for row, comment in zip(data, page, strict=True):
            row["post_excerpt"] = (comment.post.body or "")[:POST_EXCERPT]
            row["post_type"] = comment.post.type
        return paginator.get_paginated_response(data)
