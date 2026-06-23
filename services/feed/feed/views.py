"""Feed read API: the viewer's home feed (cursor-paginated, newest first)."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated

from tara_common.pagination import CursorPagination

from . import services
from .serializers import FeedItemSerializer


class FeedCursorPagination(CursorPagination):
    ordering = "-post_created_at"


class HomeFeedView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = FeedItemSerializer
    pagination_class = FeedCursorPagination

    @extend_schema(responses={200: FeedItemSerializer(many=True)}, tags=["feed"])
    def get(self, request, *args, **kwargs):
        response = super().get(request, *args, **kwargs)
        # Blend one sponsored slot into the first page; never block organic content.
        if request.query_params.get("cursor") is None and response.status_code == 200:
            from .ads_client import feed_sponsored

            response.data["sponsored"] = feed_sponsored(request.user.account_id)
        return response

    def get_queryset(self):
        return services.home_feed(self.request.user.account_id)
