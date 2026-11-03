"""Post HTTP API: posts, reactions, comments, shares, saves, reports."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tara_common.pagination import CursorPagination
from tara_common.responses import data_response
from tara_resilience.idempotency import idempotent

from . import services
from .models import IdempotencyRecord
from .serializers import (
    CommentCreateSerializer,
    CommentSerializer,
    PostBatchSerializer,
    PostCreateSerializer,
    PostEditSerializer,
    PostSerializer,
    ReactionSerializer,
    ReportSerializer,
    SavedItemSerializer,
    SaveSerializer,
)


def _me(request: Request) -> str:
    return request.user.account_id


def _serialize(viewer_id: str, posts: list) -> list:
    context = {"viewer_state": services.viewer_state(viewer_id, posts)}
    return PostSerializer(posts, many=True, context=context).data


class PostCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: PostSerializer(many=True)}, tags=["posts"])
    def get(self, request: Request) -> Response:
        """Posts by ``author_id`` (a profile's timeline), newest first.

        Audience filtering runs after paging, so a page can be short. Keep
        following ``page.next_cursor`` until ``has_more`` is false.
        """
        queryset = services.author_posts_queryset(request.query_params.get("author_id"))
        paginator = CursorPagination()
        page = paginator.paginate_queryset(queryset, request)
        posts = services.only_visible(_me(request), page)
        return paginator.get_paginated_response(_serialize(_me(request), posts))

    @extend_schema(request=PostCreateSerializer, responses={201: PostSerializer}, tags=["posts"])
    def post(self, request: Request) -> Response:
        serializer = PostCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        v = serializer.validated_data

        def handler() -> Response:
            post = services.create_post(
                _me(request),
                body=v["body"],
                post_type=v["type"],
                audience=v["audience"],
                media_ids=[str(m) for m in v["media_ids"]],
                shared_post_id=str(v["shared_post_id"]) if v.get("shared_post_id") else None,
                link_preview=v.get("link_preview"),
            )
            return data_response(PostSerializer(post).data, status=status.HTTP_201_CREATED)

        return idempotent(IdempotencyRecord, request, handler)


class PostBatchView(APIView):
    """Current content, counts and viewer state for a batch of posts.

    The feed stores snapshots; clients use this to show live data, and any id
    missing from the response was deleted or is no longer visible.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=PostBatchSerializer, responses={200: PostSerializer(many=True)}, tags=["posts"]
    )
    def post(self, request: Request) -> Response:
        serializer = PostBatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        posts = services.posts_by_ids(_me(request), serializer.validated_data["ids"])
        return data_response(_serialize(_me(request), posts))


class PostDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: PostSerializer}, tags=["posts"])
    def get(self, request: Request, post_id: str) -> Response:
        post = services.get_post(_me(request), post_id)
        return data_response(_serialize(_me(request), [post])[0])

    @extend_schema(request=PostEditSerializer, responses={200: PostSerializer}, tags=["posts"])
    def patch(self, request: Request, post_id: str) -> Response:
        serializer = PostEditSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        post = services.edit_post(_me(request), post_id, serializer.validated_data["body"])
        return data_response(PostSerializer(post).data)

    @extend_schema(responses={204: None}, tags=["posts"])
    def delete(self, request: Request, post_id: str) -> Response:
        services.delete_post(_me(request), post_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ReactionView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=ReactionSerializer, responses={200: None}, tags=["posts"])
    def post(self, request: Request, post_id: str) -> Response:
        serializer = ReactionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.react(_me(request), post_id, serializer.validated_data["type"])
        return data_response({"detail": "reacted"})

    @extend_schema(responses={204: None}, tags=["posts"])
    def delete(self, request: Request, post_id: str) -> Response:
        services.unreact(_me(request), post_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CommentsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: CommentSerializer(many=True)}, tags=["posts"])
    def get(self, request: Request, post_id: str) -> Response:
        paginator = CursorPagination()
        page = paginator.paginate_queryset(services.list_comments(_me(request), post_id), request)
        return paginator.get_paginated_response(CommentSerializer(page, many=True).data)

    @extend_schema(
        request=CommentCreateSerializer, responses={201: CommentSerializer}, tags=["posts"]
    )
    def post(self, request: Request, post_id: str) -> Response:
        serializer = CommentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        comment = services.add_comment(
            _me(request),
            post_id,
            serializer.validated_data["body"],
            str(serializer.validated_data["parent_id"])
            if serializer.validated_data.get("parent_id")
            else None,
        )
        return data_response(CommentSerializer(comment).data, status=status.HTTP_201_CREATED)


class RepliesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=CommentCreateSerializer, responses={201: CommentSerializer}, tags=["posts"]
    )
    def post(self, request: Request, comment_id: str) -> Response:
        from .models import Comment

        parent = Comment.objects.filter(id=comment_id, deleted_at__isnull=True).first()
        if parent is None:
            from tara_common.exceptions import TaraAPIError

            raise TaraAPIError("Comment not found.", code="not_found", http_status_code=404)
        serializer = CommentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        comment = services.add_comment(
            _me(request), str(parent.post_id), serializer.validated_data["body"], str(parent.id)
        )
        return data_response(CommentSerializer(comment).data, status=status.HTTP_201_CREATED)


class ShareView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={201: None}, tags=["posts"])
    def post(self, request: Request, post_id: str) -> Response:
        services.share(_me(request), post_id)
        return data_response({"detail": "shared"}, status=status.HTTP_201_CREATED)


class SaveView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: None}, tags=["saved"])
    def post(self, request: Request, post_id: str) -> Response:
        services.save_item(_me(request), "post", post_id)
        return data_response({"detail": "saved"})

    @extend_schema(responses={204: None}, tags=["saved"])
    def delete(self, request: Request, post_id: str) -> Response:
        services.unsave_item(_me(request), "post", post_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class SavedListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=SaveSerializer, responses={200: SavedItemSerializer(many=True)}, tags=["saved"]
    )
    def get(self, request: Request) -> Response:
        item_type = request.query_params.get("item_type")
        paginator = CursorPagination()
        page = paginator.paginate_queryset(services.list_saved(_me(request), item_type), request)
        return paginator.get_paginated_response(SavedItemSerializer(page, many=True).data)

    def post(self, request: Request) -> Response:
        serializer = SaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.save_item(
            _me(request),
            serializer.validated_data["item_type"],
            str(serializer.validated_data["item_id"]),
        )
        return data_response({"detail": "saved"}, status=status.HTTP_201_CREATED)


class ReportView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=ReportSerializer, responses={202: None}, tags=["posts"])
    def post(self, request: Request, post_id: str) -> Response:
        serializer = ReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.report_post(_me(request), post_id, serializer.validated_data["reason"])
        return data_response({"detail": "reported"}, status=status.HTTP_202_ACCEPTED)
