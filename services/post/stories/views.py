"""Stories HTTP API (``/api/v1/stories/``).

Views may call graph or media before writing, so they run outside
ATOMIC_REQUESTS and each write path opens its own transaction (roadmap 3.3).
A hidden story is 404 everywhere.
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
    CloseFriendAddSerializer,
    CloseFriendSerializer,
    ReactSerializer,
    StoryCreateSerializer,
    StoryReportSerializer,
    StorySerializer,
    StoryViewerSerializer,
)


def _me(request: Request) -> str:
    return request.user.account_id


def _serialize(viewer_id: str, stories: list, state: dict | None = None) -> list:
    state = state if state is not None else services.viewer_state(viewer_id, stories)
    return StorySerializer(
        stories, many=True, context={"viewer_id": viewer_id, "state": state}
    ).data


def _one(viewer_id: str, story) -> dict:
    return _serialize(viewer_id, [story])[0]


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class StoryListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[OpenApiParameter("author_id", str, required=True)],
        responses={200: StorySerializer(many=True)},
        tags=["stories"],
    )
    def get(self, request: Request) -> Response:
        """One author's active stories the viewer may see, oldest first."""
        stories = services.author_stories(_me(request), request.query_params.get("author_id", ""))
        return data_response(_serialize(_me(request), stories))

    @extend_schema(
        request=StoryCreateSerializer, responses={201: StorySerializer}, tags=["stories"]
    )
    def post(self, request: Request) -> Response:
        """A photo story (an uploaded image, private to the story's audience) or a
        text story. It is shown for 24 hours, then kept in the author's archive."""
        serializer = StoryCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = dict(serializer.validated_data)

        def handler() -> Response:
            story = services.create_story(_me(request), **values)
            return data_response(_one(_me(request), story), status=status.HTTP_201_CREATED)

        return idempotent(IdempotencyRecord, request, handler)


@method_decorator(transaction.non_atomic_requests, name="dispatch")  # calls graph
class StoryTrayView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: None}, tags=["stories"])
    def get(self, request: Request) -> Response:
        """Active stories of the viewer and their friends, grouped by author."""
        groups, state = services.tray(_me(request))
        return data_response(
            [
                {
                    "author_id": g["author_id"],
                    "has_unseen": g["has_unseen"],
                    "latest_at": g["latest_at"].isoformat(),
                    "stories": _serialize(_me(request), g["stories"], state),
                }
                for g in groups
            ]
        )


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class StoryArchiveView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: StorySerializer(many=True)}, tags=["stories"])
    def get(self, request: Request) -> Response:
        """The signed-in account's own stories, active and expired, newest first."""
        paginator = CursorPagination()
        page = paginator.paginate_queryset(services.archive_queryset(_me(request)), request)
        return paginator.get_paginated_response(_serialize(_me(request), page))


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class StoryDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: StorySerializer}, tags=["stories"])
    def get(self, request: Request, story_id) -> Response:
        """404 when hidden: expired (except for the author), outside the audience,
        blocked either way, deleted or removed."""
        return data_response(_one(_me(request), services.require_visible(_me(request), story_id)))

    @extend_schema(responses={204: None}, tags=["stories"])
    def delete(self, request: Request, story_id) -> Response:
        services.delete_story(_me(request), story_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class StorySeenView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: StorySerializer}, tags=["stories"])
    def post(self, request: Request, story_id) -> Response:
        """Mark the story seen (once per viewer; the author's own views don't count)."""
        return data_response(_one(_me(request), services.mark_viewed(_me(request), story_id)))


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class StoryViewersView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: StoryViewerSerializer(many=True)}, tags=["stories"])
    def get(self, request: Request, story_id) -> Response:
        """The author only (404 for anyone else): who saw it, newest first, with
        each viewer's reaction."""
        queryset, story = services.viewers_queryset(_me(request), story_id)
        paginator = CursorPagination()
        page = paginator.paginate_queryset(queryset, request)
        reactions = services.reactions_of(story, [v.viewer_id for v in page])
        data = StoryViewerSerializer(page, many=True, context={"reactions": reactions}).data
        return paginator.get_paginated_response(data)


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class StoryReactView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=ReactSerializer, responses={200: StorySerializer}, tags=["stories"])
    def post(self, request: Request, story_id) -> Response:
        serializer = ReactSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        story = services.react(_me(request), story_id, serializer.validated_data["reaction"])
        return data_response(_one(_me(request), story))

    @extend_schema(responses={200: StorySerializer}, tags=["stories"])
    def delete(self, request: Request, story_id) -> Response:
        return data_response(_one(_me(request), services.unreact(_me(request), story_id)))


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class StoryReportView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [*APIView.throttle_classes, ReportThrottle]

    @extend_schema(request=StoryReportSerializer, responses={202: None}, tags=["stories"])
    def post(self, request: Request, story_id) -> Response:
        """404 if the reporter cannot see the story; a repeat report is accepted once."""
        serializer = StoryReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.report(_me(request), story_id, serializer.validated_data["reason"])
        return data_response({"detail": "reported"}, status=status.HTTP_202_ACCEPTED)


@method_decorator(transaction.non_atomic_requests, name="dispatch")  # calls graph
class CloseFriendsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: CloseFriendSerializer(many=True)}, tags=["stories"])
    def get(self, request: Request) -> Response:
        """The signed-in account's close friends list (nobody else's, ever)."""
        paginator = CursorPagination()
        page = paginator.paginate_queryset(services.close_friends_queryset(_me(request)), request)
        return paginator.get_paginated_response(CloseFriendSerializer(page, many=True).data)

    @extend_schema(request=CloseFriendAddSerializer, responses={200: None}, tags=["stories"])
    def post(self, request: Request) -> Response:
        """Friends only (400 ``not_friend``). Returns who was newly added."""
        serializer = CloseFriendAddSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        added = services.add_close_friends(
            _me(request), [str(a) for a in serializer.validated_data["account_ids"]]
        )
        return data_response({"added": added})


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class CloseFriendDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={204: None}, tags=["stories"])
    def delete(self, request: Request, account_id) -> Response:
        services.remove_close_friend(_me(request), account_id)
        return Response(status=status.HTTP_204_NO_CONTENT)
