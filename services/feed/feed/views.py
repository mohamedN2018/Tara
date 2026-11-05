"""Feed API: the viewer's home feed in four modes, plus hide and snooze (2A, 1.7).

Every post-menu action handled here also writes one Tara Intelligence signal row
(``source=server``) in the request's transaction (WP 2.5); undoing it writes the
inverse row. Items carry ``st``, a serve token that attributes telemetry (WP 2.3).
"""

from __future__ import annotations

from datetime import UTC, datetime

from django.utils import timezone
from django.utils.dateparse import parse_datetime
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from intel import age, clock, config, preferences
from intel import head as first_page_head
from intel import metrics as intel_metrics
from intel.models import EventType, ItemType
from intel.ranking import serve_tokens
from intel.signals.server import record as menu_signal
from rest_framework import generics, status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from tara_common.pagination import CursorPagination
from tara_common.responses import data_response

from . import feedback, ranking, services
from .models import AuthorSnooze, PostHide
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
    """The mode to serve: ``?mode=``, else the remembered one, else ``mode_hint``
    (the client's offline fallback), else the default (WP 4.6). Resolved once."""
    cached = getattr(request, "_feed_mode", None)
    if cached:
        return cached
    asked = request.query_params.get("mode") or None
    if asked is not None and asked not in services.MODES:
        raise ValidationError({"mode": [f"Must be one of: {', '.join(services.MODES)}."]})
    mode = preferences.resolve_mode(
        request.user.account_id,
        asked,
        request.query_params.get("mode_hint"),
        services.DEFAULT_MODE,
    )
    request._feed_mode = mode
    return mode


def _since(request):
    raw = request.query_params.get("since")
    if not raw:
        return None
    when = parse_datetime(raw)
    if when is None:
        try:
            when = datetime.fromtimestamp(float(raw), tz=UTC)
        except (OverflowError, ValueError) as exc:
            raise ValidationError({"since": ["An ISO 8601 time or epoch seconds."]}) from exc
    if timezone.is_naive(when):
        when = timezone.make_aware(when, UTC)
    return when


def ad_slots() -> list[int]:
    """Home ad positions from the config (``ads.slots``, default ``[4]``, decision 14):
    distinct, non-negative indexes, in order. They place ads; they never move organic items."""
    slots = config.for_surface("home").get("ads.slots")
    return sorted({int(i) for i in slots if isinstance(i, int) and i >= 0})


def sponsored_for_slots(viewer, slots: list[int]) -> list[dict]:
    """One sponsored object per slot at most, never the same creative twice."""
    from .ads_client import feed_sponsored

    picked: list[dict] = []
    for _ in slots:
        ad = feed_sponsored(viewer)
        if not ad:
            break
        if any(p.get("creative_id") == ad.get("creative_id") for p in picked):
            break
        picked.append(ad)
    return picked


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
            ),
            OpenApiParameter(
                "mode_hint",
                OpenApiTypes.STR,
                enum=list(services.MODES),
                description="The client's offline fallback, used only without `mode` "
                "and without a remembered mode.",
            ),
            OpenApiParameter("peek", OpenApiTypes.BOOL, description="New rows only (D4)."),
            OpenApiParameter("since", OpenApiTypes.STR, description="Peek: rows after this."),
        ],
        responses={200: FeedItemSerializer(many=True)},
        tags=["feed"],
    )
    def get(self, request, *args, **kwargs):
        # WP 4b.14: the requesting account's own age class (rule E9b), from its own
        # token claims; safety data, captured whatever the personalization setting.
        age.capture(request.user.account_id, getattr(request.user, "claims", None))
        mode = _mode(request)
        if request.query_params.get("peek") in ("1", "true"):
            return self._peek(request, mode)
        if mode == "for_you":
            response = self._ranked(request)
        else:
            response = super().get(request, *args, **kwargs)
        if response.status_code == 200:
            if mode != "for_you":  # ranked pages are stamped in _ranked (they know positions)
                serve_tokens.stamp_home_items(
                    request.user.account_id, response.data["data"], mode, offset=None, ranked=False
                )
            response.data["mode"] = mode
            # Ads go in after the organic page is complete (02 section 18), at the
            # config's slots, on the first page only; they never block organic content.
            if request.query_params.get("cursor") is None:
                slots = ad_slots()
                ads = sponsored_for_slots(request.user.account_id, slots)
                response.data["sponsored"] = ads[0] if ads else None
                response.data["sponsored_slots"] = ads
                response.data["meta"] = {
                    **response.data.get("meta", {}),
                    "ad_slots": slots,
                    "as_of": timezone.now().isoformat(),
                }
        return response

    def _peek(self, request, mode: str) -> Response:
        """``?peek=1`` (D4, WP 4.7): new rows for the "new posts" pill. Read only:
        it never writes or replaces the ranking session and never calls ads."""
        viewer = request.user.account_id
        rows, count = services.peek(
            viewer,
            mode,
            _since(request),
            _page_size(request),
            config.for_surface("home").get("peek.max_since_hours"),
        )
        data = FeedItemSerializer(rows, many=True).data
        serve_tokens.stamp_home_items(viewer, data, mode, offset=None, ranked=False)
        return Response({"data": data, "mode": mode, "peek": True, "new_count": count})

    def _ranked(self, request) -> Response:
        viewer, size = request.user.account_id, _page_size(request)
        token = request.query_params.get("cursor")
        claims = getattr(request.user, "claims", None)  # age claims for eligibility
        try:
            if token is None:
                # WP 4b.15: the test clock (dev, flag on, seed or test account only).
                now = clock.request_now(request, viewer)
                page, offset = ranking.first_page(viewer, size, now, claims), 0
            else:
                cursor = ranking.decode_cursor(token)
                page = ranking.next_page(viewer, token, size, claims)
                offset = int(cursor.get("o", 0)) if cursor.get("k") == "r" else None
        except ranking.InvalidCursor as exc:
            raise NotFound("Invalid cursor.") from exc
        # The first page is ranked even when its session could not be stored; a later
        # page is ranked only while it reads the session (not the latest-order fallback).
        ranked = offset is not None and (token is None or not page.fallback)
        data = FeedItemSerializer(page.items, many=True).data
        if ranked and page.sources:
            # Additive (WP 4.3): the candidate source, which the web passes to post's
            # /posts/batch/ as the ``src`` hint.
            for item, source in zip(data, page.sources, strict=True):
                item["source"] = source
        serve_tokens.stamp_home_items(
            viewer,
            data,
            "for_you",
            offset=offset if ranked else None,
            ranked=ranked,
            cfg_version=page.cfg_version if ranked else None,
        )
        if page.caught_up and ranked:
            intel_metrics.caught_up()
        if token is None:
            # WP 4b.11: overlap with the previous first page (ids only; nothing stored
            # under personalization_off or a version without the head block).
            first_page_head.record(
                viewer, ranking.SURFACE, [i["post_id"] for i in data], ranking.home_config()
            )
        return Response(
            {
                "data": data,
                "page": {
                    "next_cursor": page.next_cursor,
                    "prev_cursor": None,
                    "has_more": page.has_more,
                    "fallback": page.fallback,
                },
                # WP 4b.6: where this page's items leave the connection inventory.
                "meta": {"caught_up_index": page.caught_up_index if ranked else None},
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
        viewer, post_id = request.user.account_id, body.validated_data["post_id"]
        was_hidden = PostHide.objects.filter(account_id=viewer, post_id=post_id).exists()
        hide = feedback.hide_post(viewer, post_id, body.validated_data["reason"])
        if not was_hidden:  # a repeat or a new reason is the same hide, not a new action
            menu_signal(viewer, EventType.POST_HIDE, ItemType.POST, post_id, hide.author_id)
        return data_response(PostHideSerializer(hide).data, status=status.HTTP_201_CREATED)


class UnhideView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={204: None}, tags=["feed"])
    def delete(self, request, post_id):
        viewer = request.user.account_id
        hide = PostHide.objects.filter(account_id=viewer, post_id=post_id).first()
        feedback.unhide_post(viewer, post_id)
        if hide is not None:
            menu_signal(viewer, EventType.POST_UNHIDE, ItemType.POST, post_id, hide.author_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class SnoozeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=SnoozeRequestSerializer, responses={201: AuthorSnoozeSerializer}, tags=["feed"]
    )
    def post(self, request):
        body = SnoozeRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        viewer, author_id = request.user.account_id, body.validated_data["author_id"]
        snooze = feedback.snooze_author(viewer, author_id)
        menu_signal(viewer, EventType.AUTHOR_SNOOZE, ItemType.PROFILE, author_id, author_id)
        return data_response(AuthorSnoozeSerializer(snooze).data, status=status.HTTP_201_CREATED)


class UnsnoozeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={204: None}, tags=["feed"])
    def delete(self, request, author_id):
        viewer = request.user.account_id
        was_snoozed = AuthorSnooze.objects.filter(account_id=viewer, author_id=author_id).exists()
        feedback.unsnooze_author(viewer, author_id)
        if was_snoozed:
            menu_signal(viewer, EventType.AUTHOR_UNSNOOZE, ItemType.PROFILE, author_id, author_id)
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
