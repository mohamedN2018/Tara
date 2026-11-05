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

from . import activity, studio
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
            OpenApiParameter("type", str, description="text, image, video, link, share or poll"),
            OpenApiParameter("q", str, description="Only posts whose text contains this"),
            OpenApiParameter("from", str, description="ISO date-time with offset (inclusive)"),
            OpenApiParameter("to", str, description="ISO date-time with offset (exclusive)"),
        ],
        responses={200: PostSerializer(many=True)},
        tags=["studio"],
    )
    def get(self, request: Request) -> Response:
        """My published posts (group posts included), newest first, optionally
        filtered by type, text and publication time."""
        me = _me(request)
        params = request.query_params
        queryset = studio.published_queryset(
            me,
            params.get("type") or None,
            query=params.get("q"),
            start=params.get("from") or None,
            end=params.get("to") or None,
        )
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


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class StudioDailyView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter("from", str, required=True, description="First day, YYYY-MM-DD"),
            OpenApiParameter("to", str, required=True, description="Last day, YYYY-MM-DD"),
            OpenApiParameter("tz", str, description="IANA time zone of the days (default UTC)"),
        ],
        tags=["studio"],
    )
    def get(self, request: Request) -> Response:
        """Per day (at most 366): reel views, reactions, comments, shares and
        saves my published posts received from other people, and my posts."""
        params = request.query_params
        data = studio.daily(_me(request), params.get("from"), params.get("to"), params.get("tz"))
        return Response({"data": data})


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class ActivityLogView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "kind", str, description="post, comment, reaction, comment_reaction, save or vote"
            ),
            OpenApiParameter("cursor", str),
            OpenApiParameter("limit", int),
        ],
        tags=["activity"],
    )
    def get(self, request: Request) -> Response:
        """My own activity, newest first. A row's ``target`` (the post acted
        on) is null once I can no longer see that post."""
        params = request.query_params
        try:
            limit = int(params.get("limit") or activity.PAGE_SIZE)
        except ValueError:
            limit = activity.PAGE_SIZE
        return Response(
            activity.activity(
                _me(request),
                kind=params.get("kind") or None,
                cursor=params.get("cursor"),
                limit=limit,
            )
        )
