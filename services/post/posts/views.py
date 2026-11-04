"""Post HTTP API: posts, reactions, comments, shares, saves, reports."""

from __future__ import annotations

from django.db import transaction
from django.utils.decorators import method_decorator
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tara_common.pagination import CursorPagination
from tara_common.responses import data_response
from tara_resilience.idempotency import idempotent

from . import composer, saved, services
from .models import IdempotencyRecord, PostState
from .serializers import (
    CommentCreateSerializer,
    CommentEditSerializer,
    CommentSerializer,
    DraftEditSerializer,
    PostBatchSerializer,
    PostCreateSerializer,
    PostEditSerializer,
    PostSerializer,
    PostSettingsSerializer,
    ReactionSerializer,
    ReactorSerializer,
    ReportSerializer,
    SavedFilterSerializer,
    SavedItemSerializer,
    SaveIntoSerializer,
    SaveSerializer,
    ShareCreateSerializer,
    SharerSerializer,
    VoteSerializer,
)
from .throttling import ReportThrottle


def _me(request: Request) -> str:
    return request.user.account_id


def _one(viewer_id: str, post) -> dict:
    return _serialize(viewer_id, [post])[0]


def _serialize(viewer_id: str, posts: list) -> list:
    context = {"viewer_state": services.viewer_state(viewer_id, posts)}
    return PostSerializer(posts, many=True, context=context).data


def _edit_kwargs(v: dict) -> dict:
    kwargs = {
        "body": v.get("body"),
        "audience": v.get("audience"),
        "comment_policy": v.get("comment_policy"),
        "location": v.get("location"),
        "feeling": v.get("feeling"),
    }
    if "tagged_ids" in v:
        kwargs["tagged_ids"] = [str(t) for t in v["tagged_ids"]]
    if "publish_at" in v:
        kwargs["publish_at"] = v["publish_at"]
    return kwargs


def _comments(viewer_id: str, comments: list) -> list:
    context = {"my_reactions": services.comment_reactions_of(viewer_id, comments)}
    return CommentSerializer(comments, many=True, context=context).data


def _comment(viewer_id: str, comment) -> dict:
    return _comments(viewer_id, [comment])[0]


# Creating and editing call media before writing (attachment checks, media
# restriction), so these views run outside ATOMIC_REQUESTS and each write path
# opens its own transaction (roadmap 3.3, "Sync calls inside requests").
@method_decorator(transaction.non_atomic_requests, name="dispatch")
class PostCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: PostSerializer(many=True)}, tags=["posts"])
    def get(self, request: Request) -> Response:
        """Posts by ``author_id`` (a profile's timeline) or ``hashtag``, newest first.

        Audience filtering runs after paging, so a page can be short. Keep
        following ``page.next_cursor`` until ``has_more`` is false.
        """
        hashtag = request.query_params.get("hashtag")
        if request.query_params.get("type") == "video" and not hashtag:
            # The home "Videos" rail and /videos (T4): video posts the viewer may see.
            queryset = services.video_posts_queryset(request.query_params.get("author_id"))
        elif hashtag:
            queryset = services.hashtag_posts_queryset(hashtag)
        else:
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

        if v.get("publish_at"):
            state = PostState.SCHEDULED
        elif v.get("draft"):
            state = PostState.DRAFT
        else:
            state = PostState.PUBLISHED

        def handler() -> Response:
            post = services.create_post(
                _me(request),
                body=v["body"],
                post_type=v["type"],
                audience=v["audience"],
                media_ids=[str(m) for m in v["media_ids"]],
                poll=v.get("poll"),
                comment_policy=v["comment_policy"],
                group_id=v.get("group_id"),
                tagged_ids=[str(t) for t in v["tagged_ids"]],
                location=v["location"],
                feeling=v["feeling"],
                state=state,
                publish_at=v.get("publish_at"),
                page_id=v.get("page_id"),
            )
            return data_response(_one(_me(request), post), status=status.HTTP_201_CREATED)

        return idempotent(IdempotencyRecord, request, handler)


@method_decorator(transaction.non_atomic_requests, name="dispatch")  # reads; calls graph
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


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class PostDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: PostSerializer}, tags=["posts"])
    def get(self, request: Request, post_id: str) -> Response:
        post = services.get_post(_me(request), post_id)
        return data_response(_serialize(_me(request), [post])[0])

    @extend_schema(request=PostEditSerializer, responses={200: PostSerializer}, tags=["posts"])
    def patch(self, request: Request, post_id: str) -> Response:
        """Edit the body, audience, comment policy, tags, location and/or feeling.
        Removed or pending-review posts, drafts and scheduled posts return 404."""
        serializer = PostEditSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        post = services.edit_post(_me(request), post_id, **_edit_kwargs(serializer.validated_data))
        return data_response(_one(_me(request), post))

    @extend_schema(responses={204: None}, tags=["posts"])
    def delete(self, request: Request, post_id: str) -> Response:
        services.delete_post(_me(request), post_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


# The visibility check may call graph, so it runs before the write transaction
# that each write path opens itself (roadmap 3.3).
@method_decorator(transaction.non_atomic_requests, name="dispatch")
class ReactionView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: ReactorSerializer(many=True)}, tags=["posts"])
    def get(self, request: Request, post_id: str) -> Response:
        """Who reacted, newest first; ``?type=love`` keeps one type. 404 when the
        viewer cannot see the post; accounts blocked either way are left out."""
        queryset = services.list_reactions(
            _me(request), post_id, request.query_params.get("type") or None
        )
        paginator = CursorPagination()
        page = paginator.paginate_queryset(queryset, request)
        return paginator.get_paginated_response(ReactorSerializer(page, many=True).data)

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


@method_decorator(transaction.non_atomic_requests, name="dispatch")  # policy may call graph
class CommentsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: CommentSerializer(many=True)}, tags=["comments"])
    def get(self, request: Request, post_id: str) -> Response:
        """Thread roots, oldest first, each with ``reply_count``. Replies come from
        ``GET /comments/<root>/replies/``."""
        paginator = CursorPagination()
        page = paginator.paginate_queryset(services.list_comments(_me(request), post_id), request)
        return paginator.get_paginated_response(_comments(_me(request), page))

    @extend_schema(
        request=CommentCreateSerializer, responses={201: CommentSerializer}, tags=["comments"]
    )
    def post(self, request: Request, post_id: str) -> Response:
        """A root comment, or with ``reply_to_id`` a reply (flattened onto its root).
        403 ``comments_disabled`` / ``comments_friends_only`` under the post's policy."""
        serializer = CommentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        v = serializer.validated_data
        comment = services.add_comment(_me(request), post_id, v["body"], v["target"])
        return data_response(_comment(_me(request), comment), status=status.HTTP_201_CREATED)


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class RepliesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: CommentSerializer(many=True)}, tags=["comments"])
    def get(self, request: Request, comment_id: str) -> Response:
        """The thread's replies, oldest first. 404 when the root is hidden."""
        paginator = CursorPagination()
        page = paginator.paginate_queryset(services.list_replies(_me(request), comment_id), request)
        return paginator.get_paginated_response(_comments(_me(request), page))

    @extend_schema(
        request=CommentCreateSerializer, responses={201: CommentSerializer}, tags=["comments"]
    )
    def post(self, request: Request, comment_id: str) -> Response:
        """Reply to this comment. The post is the comment's own post, never the client's."""
        serializer = CommentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target = services.visible_comment(_me(request), comment_id)
        comment = services.add_comment(
            _me(request), str(target.post_id), serializer.validated_data["body"], str(target.id)
        )
        return data_response(_comment(_me(request), comment), status=status.HTTP_201_CREATED)


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class CommentDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=CommentEditSerializer, responses={200: CommentSerializer}, tags=["comments"]
    )
    def patch(self, request: Request, comment_id: str) -> Response:
        """The author edits the text. 404 for anyone else."""
        serializer = CommentEditSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        comment = services.edit_comment(_me(request), comment_id, serializer.validated_data["body"])
        return data_response(_comment(_me(request), comment))

    @extend_schema(responses={200: None}, tags=["comments"])
    def delete(self, request: Request, comment_id: str) -> Response:
        """The comment's author or the post's author. A root takes its replies with
        it. Returns the post's new ``comment_count``."""
        count = services.delete_comment(_me(request), comment_id)
        return data_response({"comment_id": str(comment_id), "comment_count": count})


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class CommentReactionView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=ReactionSerializer, responses={200: None}, tags=["comments"])
    def post(self, request: Request, comment_id: str) -> Response:
        serializer = ReactionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        comment = services.react_comment(
            _me(request), comment_id, serializer.validated_data["type"]
        )
        return data_response(
            {"comment_id": str(comment.id), "reaction_count": comment.reaction_count}
        )

    @extend_schema(responses={204: None}, tags=["comments"])
    def delete(self, request: Request, comment_id: str) -> Response:
        services.unreact_comment(_me(request), comment_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class CommentReportView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [*APIView.throttle_classes, ReportThrottle]

    @extend_schema(request=ReportSerializer, responses={202: None}, tags=["comments"])
    def post(self, request: Request, comment_id: str) -> Response:
        """404 if the reporter cannot see the comment; a repeat report is accepted once."""
        serializer = ReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.report_comment(_me(request), comment_id, serializer.validated_data["reason"])
        return data_response({"detail": "reported"}, status=status.HTTP_202_ACCEPTED)


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class ShareView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=ShareCreateSerializer, responses={201: PostSerializer}, tags=["posts"])
    def post(self, request: Request, post_id: str) -> Response:
        serializer = ShareCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        v = serializer.validated_data
        post = services.share(_me(request), post_id, body=v["body"], audience=v.get("audience"))
        return data_response(_one(_me(request), post), status=status.HTTP_201_CREATED)


@method_decorator(transaction.non_atomic_requests, name="dispatch")  # reads; calls graph
class SharesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: SharerSerializer(many=True)}, tags=["posts"])
    def get(self, request: Request, post_id: str) -> Response:
        """Who shared the post, newest first, as their share posts. A share is
        listed only to someone who could open it, so a page can be short: keep
        following ``page.next_cursor`` until ``has_more`` is false."""
        paginator = CursorPagination()
        page = paginator.paginate_queryset(
            services.list_share_posts(_me(request), post_id), request
        )
        shares = services.only_visible(_me(request), page)
        return paginator.get_paginated_response(SharerSerializer(shares, many=True).data)


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class VoteView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=VoteSerializer, responses={200: PostSerializer}, tags=["posts"])
    def post(self, request: Request, post_id: str) -> Response:
        serializer = VoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        post = services.vote(_me(request), post_id, str(serializer.validated_data["option_id"]))
        return data_response(_one(_me(request), post))


class SaveView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=SaveIntoSerializer, responses={200: SavedItemSerializer}, tags=["saved"])
    def post(self, request: Request, post_id: str) -> Response:
        """Save a post I can see (404 otherwise), into ``collection_id`` when
        given; a saved post is moved there."""
        body = SaveIntoSerializer(data=request.data or {})
        body.is_valid(raise_exception=True)
        services.get_post(_me(request), str(post_id))
        item = saved.save_into(
            _me(request), "post", str(post_id), body.validated_data.get("collection_id")
        )
        return data_response({"detail": "saved", **SavedItemSerializer(item).data})

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
        query = SavedFilterSerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        paginator = CursorPagination()
        page = paginator.paginate_queryset(
            saved.list_saved(_me(request), item_type, query.validated_data.get("collection_id")),
            request,
        )
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


class SavedItemView(APIView):
    """Whether I saved an item, and unsave any kind (a page, a listing, a video,
    a post). Only ever about the signed-in account's own saves."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: None}, tags=["saved"])
    def get(self, request: Request, item_type: str, item_id: str) -> Response:
        found = services.list_saved(_me(request), item_type).filter(item_id=item_id).exists()
        return data_response({"saved": found})

    @extend_schema(responses={204: None}, tags=["saved"])
    def delete(self, request: Request, item_type: str, item_id: str) -> Response:
        services.unsave_item(_me(request), item_type, str(item_id))
        return Response(status=status.HTTP_204_NO_CONTENT)


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class ReportView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [*APIView.throttle_classes, ReportThrottle]

    @extend_schema(request=ReportSerializer, responses={202: None}, tags=["posts"])
    def post(self, request: Request, post_id: str) -> Response:
        """404 if the reporter cannot see the post; a repeat report is accepted once."""
        serializer = ReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.report_post(_me(request), post_id, serializer.validated_data["reason"])
        return data_response({"detail": "reported"}, status=status.HTTP_202_ACCEPTED)


# ---- the composer (2C): drafts and scheduled posts, tag settings ----------------------


class DraftsView(APIView):
    """The signed-in author's drafts and scheduled posts (nobody else's, ever)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: PostSerializer(many=True)}, tags=["drafts"])
    def get(self, request: Request) -> Response:
        """Last changed first; ``?state=draft`` or ``?state=scheduled`` keeps one kind."""
        queryset = composer.drafts_queryset(_me(request), request.query_params.get("state"))
        paginator = CursorPagination()
        page = paginator.paginate_queryset(queryset, request)
        return paginator.get_paginated_response(_serialize(_me(request), list(page)))


@method_decorator(transaction.non_atomic_requests, name="dispatch")  # tags may call graph
class DraftDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: PostSerializer}, tags=["drafts"])
    def get(self, request: Request, post_id: str) -> Response:
        post = composer.get_draft(_me(request), post_id)
        return data_response(_one(_me(request), post))

    @extend_schema(request=DraftEditSerializer, responses={200: PostSerializer}, tags=["drafts"])
    def patch(self, request: Request, post_id: str) -> Response:
        """Edit a draft; ``publish_at`` schedules it (in the future, at most 75
        days ahead) and ``null`` turns a scheduled post back into a draft."""
        serializer = DraftEditSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        post = services.edit_post(
            _me(request), post_id, draft=True, **_edit_kwargs(serializer.validated_data)
        )
        return data_response(_one(_me(request), post))

    @extend_schema(responses={204: None}, tags=["drafts"])
    def delete(self, request: Request, post_id: str) -> Response:
        composer.delete_draft(_me(request), post_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class DraftPublishView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: PostSerializer}, tags=["drafts"])
    def post(self, request: Request, post_id: str) -> Response:
        """Publish now. 404 once it is published (by the schedule, or twice)."""
        post = composer.publish_draft(_me(request), post_id)
        return data_response(_one(_me(request), post))


class PostSettingsView(APIView):
    """The account's post settings: ``who_can_tag`` (everyone, friends, nobody)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: PostSettingsSerializer}, tags=["settings"])
    def get(self, request: Request) -> Response:
        return data_response(composer.get_settings(_me(request)))

    @extend_schema(
        request=PostSettingsSerializer, responses={200: PostSettingsSerializer}, tags=["settings"]
    )
    def patch(self, request: Request) -> Response:
        serializer = PostSettingsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return data_response(
            composer.update_settings(
                _me(request), who_can_tag=serializer.validated_data["who_can_tag"]
            )
        )


@method_decorator(transaction.non_atomic_requests, name="dispatch")  # visibility calls graph
class MyTagView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={204: None}, tags=["posts"])
    def delete(self, request: Request, post_id: str) -> Response:
        """Remove my own tag from a post (even one I can no longer see)."""
        composer.remove_my_tag(_me(request), post_id)
        return Response(status=status.HTTP_204_NO_CONTENT)
