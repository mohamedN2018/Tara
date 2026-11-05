"""Reels HTTP API (roadmap 5.5 / 5.8), under ``/api/v1/reels/``.

Reactions, comments, shares, saves, reports, edits and deletion are the post's
own endpoints (``/api/v1/posts/<id>/...``): a reel's id is its post's id.
"""

from __future__ import annotations

from django.db import transaction
from django.utils.decorators import method_decorator
from drf_spectacular.utils import OpenApiParameter, extend_schema
from posts.models import IdempotencyRecord
from posts.serializers import PostSerializer
from posts.services import viewer_state
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tara_common.exceptions import TaraAPIError
from tara_common.pagination import CursorPagination
from tara_common.responses import data_response
from tara_resilience.idempotency import idempotent

from . import services
from .serializers import ReelCreateSerializer, ReelEligibilitySerializer


def _me(request: Request) -> str:
    return request.user.account_id


def serialize(viewer_id: str, reels: list) -> list[dict]:
    """Each reel as its post (counts, the viewer's reaction, saved...) plus ``reel``."""
    posts = [r.post for r in reels]
    data = PostSerializer(
        posts, many=True, context={"viewer_state": viewer_state(viewer_id, posts)}
    ).data
    today = services.views_today(viewer_id, reels) if reels else set()
    out = []
    for item, reel in zip(data, reels, strict=True):
        item = dict(item)
        item["reel"] = {
            "media_id": str(reel.media_id),
            "cover_media_id": str(reel.cover_media_id) if reel.cover_media_id else None,
            "duration_ms": reel.duration_ms,
            "width": reel.width,
            "height": reel.height,
            "view_count": reel.view_count,
            "viewed_today": reel.pk in today,
        }
        out.append(item)
    return out


class ReelPagination(CursorPagination):
    page_size = 10
    max_page_size = 30


# Feeds ask graph and profile; creating calls media first: no request-wide transaction.
@method_decorator(transaction.non_atomic_requests, name="dispatch")
class ReelListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["reels"],
        parameters=[
            OpenApiParameter("tab", str, enum=list(services.TABS)),
            OpenApiParameter("author_id", str, description="A profile's or page's reels"),
        ],
    )
    def get(self, request: Request) -> Response:
        """``?tab=for_you`` (default) or ``following``; ``?author_id=`` lists one
        profile's or page's reels instead (their Reels tab). Newest first.

        Every item is checked with the post's visibility rule after paging, so a
        page can be short; keep following ``page.next_cursor`` while ``has_more``.
        """
        me = _me(request)
        paginator = ReelPagination()
        author_id = request.query_params.get("author_id")
        if author_id:
            page = paginator.paginate_queryset(services.author_queryset(author_id), request)
            reels = services.visible_reels(me, list(page))
        else:
            tab = request.query_params.get("tab") or services.TAB_FOR_YOU
            if tab not in services.TABS:
                raise TaraAPIError("Unknown tab.", code="validation_error", http_status_code=400)
            ctx = services.FeedContext(me, tab=tab)
            page = paginator.paginate_queryset(services.feed_queryset(ctx, tab), request)
            reels = ctx.visible(list(page))
        return paginator.get_paginated_response(serialize(me, reels))

    @extend_schema(request=ReelCreateSerializer, tags=["reels"])
    def post(self, request: Request) -> Response:
        """Publish a vertical video (portrait around 9:16, at most 90 s, as media
        measured it) as a reel. A landscape or longer clip is refused with
        ``reel_not_vertical`` / ``reel_too_long``: post it as a video instead."""
        serializer = ReelCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        v = serializer.validated_data

        def handler() -> Response:
            post = services.create_reel(
                _me(request),
                media_id=v["media_id"],
                cover_media_id=v.get("cover_media_id"),
                caption=v["caption"],
                audience=v["audience"],
                comment_policy=v["comment_policy"],
                page_id=v.get("page_id"),
            )
            reel = services.get_reel(_me(request), post.id)
            return data_response(serialize(_me(request), [reel])[0], status=status.HTTP_201_CREATED)

        return idempotent(IdempotencyRecord, request, handler)


@method_decorator(transaction.non_atomic_requests, name="dispatch")  # calls media
class ReelEligibilityView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=ReelEligibilitySerializer, tags=["reels"])
    def post(self, request: Request) -> Response:
        """Whether my ready video can be a reel (``eligible``, else ``code``)."""
        serializer = ReelEligibilitySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return data_response(
            services.eligibility(_me(request), serializer.validated_data["media_id"])
        )


@method_decorator(transaction.non_atomic_requests, name="dispatch")  # calls graph
class ReelDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["reels"])
    def get(self, request: Request, reel_id) -> Response:
        """One reel; 404 for one the viewer may not see, or a post that is not a reel."""
        reel = services.get_reel(_me(request), reel_id)
        return data_response(serialize(_me(request), [reel])[0])


@method_decorator(transaction.non_atomic_requests, name="dispatch")  # calls graph
class ReelViewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["reels"])
    def post(self, request: Request, reel_id) -> Response:
        """The viewer watched it for ``watch_ms`` (at least 1 s counts): counted
        once per viewer per day, never the author."""
        body = request.data if isinstance(request.data, dict) else {}
        reel, counted = services.record_view(_me(request), reel_id, body.get("watch_ms"))
        return data_response({"view_count": reel.view_count, "counted": counted})


@method_decorator(transaction.non_atomic_requests, name="dispatch")  # calls graph
class ReelHideView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["reels"])
    def post(self, request: Request, reel_id) -> Response:
        """Mark it "not interested": the reel leaves my reels feeds."""
        services.hide(_me(request), reel_id)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(tags=["reels"])
    def delete(self, request: Request, reel_id) -> Response:
        services.unhide(_me(request), reel_id)
        return Response(status=status.HTTP_204_NO_CONTENT)
