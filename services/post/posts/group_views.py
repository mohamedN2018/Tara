"""Group posts HTTP API (roadmap 1.11): a group's feed, approvals, announcements
and the group's reported-content queue.

The group's staff actions ask profile first (revocation-critical), so these
views run outside ATOMIC_REQUESTS and each write opens its own transaction.
"""

from __future__ import annotations

from django.db import transaction
from django.utils.decorators import method_decorator
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tara_common.pagination import CursorPagination
from tara_common.responses import data_response

from . import group_activity, services
from .serializers import GroupReportDismissSerializer, PostSerializer
from .views import _me, _one, _serialize


@method_decorator(transaction.non_atomic_requests, name="dispatch")  # may ask profile
class GroupFeedView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[OpenApiParameter("view", str, enum=list(services.GROUP_VIEWS))],
        responses={200: PostSerializer(many=True)},
        tags=["groups"],
    )
    def get(self, request: Request, group_id) -> Response:
        """``discussion`` (default), ``featured`` (announcements), ``pending``,
        ``media``. Filtered before paging, so pages are full. 404 when the
        viewer may not read the group's content."""
        queryset = services.group_posts_queryset(
            _me(request), group_id, request.query_params.get("view") or "discussion"
        )
        paginator = CursorPagination()
        page = paginator.paginate_queryset(queryset, request)
        return paginator.get_paginated_response(_serialize(_me(request), list(page)))


@method_decorator(transaction.non_atomic_requests, name="dispatch")  # may ask profile
class GroupActivityView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[OpenApiParameter("ids", str, description="Comma-separated group ids (<= 20).")],
        responses={200: None},
        tags=["groups"],
    )
    def get(self, request: Request) -> Response:
        """When each group last had a post, for the groups rail. Only groups
        whose content the viewer may read are in the answer (others are left
        out, never an error)."""
        ids = group_activity.parse_ids(request.query_params.get("ids", ""))
        times = group_activity.last_post_times(_me(request), ids)
        return data_response(
            [{"group_id": gid, "last_post_at": when} for gid, when in times.items()]
        )


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class GroupPostApprovalView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: PostSerializer}, tags=["groups"])
    def post(self, request: Request, post_id, action: str) -> Response:
        """The group's moderators, admins and owners. ``decline`` deletes the post."""
        if action == "approve":
            post = services.approve_group_post(_me(request), str(post_id))
            return data_response(_one(_me(request), post))
        services.decline_group_post(_me(request), str(post_id))
        return Response(status=status.HTTP_204_NO_CONTENT)


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class GroupPostPinView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: PostSerializer}, tags=["groups"])
    def post(self, request: Request, post_id) -> Response:
        """Pin as an announcement; the group's members are told."""
        post = services.pin_group_post(_me(request), str(post_id), pin=True)
        return data_response(_one(_me(request), post))

    @extend_schema(responses={200: PostSerializer}, tags=["groups"])
    def delete(self, request: Request, post_id) -> Response:
        post = services.pin_group_post(_me(request), str(post_id), pin=False)
        return data_response(_one(_me(request), post))


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class GroupReportsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: None}, tags=["groups"])
    def get(self, request: Request, group_id) -> Response:
        """Reported posts and comments of the group (at most 100, newest report
        first), for its moderators. Not paged: one page is the whole queue."""
        items = services.group_reported_content(_me(request), group_id)
        return Response(
            {
                "data": items,
                "page": {"next_cursor": None, "prev_cursor": None, "has_more": False},
            }
        )


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class GroupReportDismissView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=GroupReportDismissSerializer, responses={204: None}, tags=["groups"])
    def post(self, request: Request, group_id) -> Response:
        serializer = GroupReportDismissSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        v = serializer.validated_data
        services.dismiss_group_report(_me(request), group_id, v["target_type"], str(v["target_id"]))
        return Response(status=status.HTTP_204_NO_CONTENT)
