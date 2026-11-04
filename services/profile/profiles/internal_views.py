"""Internal (service-to-service) API — never exposed at the public edge.

Returns a minimal public profile snapshot for other services (e.g. Posts/Chat
need author display data). Authenticated with a short-lived internal service
token (HS256), NOT a user token.
"""

from __future__ import annotations

import uuid

from django.db.models import Q
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tara_common.auth import verify_internal_token
from tara_common.exceptions import TaraAPIError
from tara_common.pagination import CursorPagination
from tara_common.responses import data_response

from .models import UserProfile
from .services import page_access, page_team, visible_page_ids


def _require_internal(request: Request) -> None:
    header = request.META.get("HTTP_AUTHORIZATION", "")
    parts = header.split()
    if len(parts) != 2 or parts[0] != "Bearer":
        raise TaraAPIError("Internal auth required.", code="unauthenticated", http_status_code=401)
    try:
        verify_internal_token(parts[1], expected_audience="profile-internal")
    except Exception as exc:  # noqa: BLE001
        raise TaraAPIError(
            "Invalid internal token.", code="unauthenticated", http_status_code=401
        ) from exc


MAX_HANDLES = 50


class _HandlesSerializer(serializers.Serializer):
    handles = serializers.ListField(child=serializers.CharField(max_length=60), default=list)


class ProfilesByHandleView(APIView):
    """Resolve @handles to accounts. Unknown handles are simply left out.

    Handles are stored lowercase, so the lookup uses the unique index.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes: list = []  # internal: no per-IP throttle (roadmap 3.3)

    def post(self, request: Request) -> Response:
        _require_internal(request)
        serializer = _HandlesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        handles = [h.lower() for h in serializer.validated_data["handles"]][:MAX_HANDLES]
        rows = UserProfile.objects.filter(handle__in=handles, deleted_at__isnull=True).values_list(
            "handle", "account_id"
        )
        return data_response({handle: str(account) for handle, account in rows})


class ProfileSnapshotView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes: list = []  # internal: no per-IP throttle (roadmap 3.3)

    def get(self, request: Request, account_id: str) -> Response:
        _require_internal(request)
        profile = UserProfile.objects.filter(account_id=account_id, deleted_at__isnull=True).first()
        if profile is None:
            raise TaraAPIError("Profile not found.", code="not_found", http_status_code=404)
        return data_response(
            {
                "account_id": str(profile.account_id),
                "handle": profile.handle,
                "display_name": profile.display_name,
                "avatar_media_id": str(profile.avatar_media_id)
                if profile.avatar_media_id
                else None,
            }
        )


class _SearchPagination(CursorPagination):
    page_size = 20
    max_page_size = 50


SEARCH_MIN_LENGTH = 2


class ProfileSearchView(APIView):
    """Admin's user console (8.6): profiles whose handle starts with ``q``, or
    whose display name contains it. ``@name`` or ``field=handle`` matches
    handles only, ``field=name`` display names only.

    Keyset-paginated on the unique handle. Returns ids and the public name
    fields only; admin joins identity's account status itself.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes: list = []  # internal: no per-IP throttle (roadmap 3.3)

    def get(self, request: Request) -> Response:
        _require_internal(request)
        q = request.query_params.get("q", "").strip()
        field = request.query_params.get("field", "any")
        if q.startswith("@"):
            field = "handle"
        q = q.lstrip("@").strip()
        if len(q) < SEARCH_MIN_LENGTH or len(q) > 80:
            raise TaraAPIError(
                f"Search for {SEARCH_MIN_LENGTH} to 80 characters.",
                code="validation_error",
                http_status_code=400,
            )
        by_handle, by_name = Q(handle__startswith=q.lower()), Q(display_name__icontains=q)
        match = {"handle": by_handle, "name": by_name}.get(field, by_handle | by_name)
        rows = (
            UserProfile.objects.filter(match, deleted_at__isnull=True)
            .only("account_id", "handle", "display_name")
            .order_by("handle")
        )
        paginator = _SearchPagination()
        page = paginator.paginate_queryset(rows, request, view=self)
        return paginator.get_paginated_response(
            [
                {
                    "account_id": str(p.account_id),
                    "handle": p.handle,
                    "display_name": p.display_name,
                }
                for p in page
            ]
        )


class _AccountIdsSerializer(serializers.Serializer):
    account_ids = serializers.ListField(
        child=serializers.UUIDField(), allow_empty=True, max_length=MAX_HANDLES
    )


class ProfilesByAccountView(APIView):
    """Handles and names for a page of accounts (admin's user console, 8.6).

    ``{account_id: {"handle", "display_name"}}``; accounts without a profile are
    left out.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes: list = []  # internal: no per-IP throttle (roadmap 3.3)

    def post(self, request: Request) -> Response:
        _require_internal(request)
        serializer = _AccountIdsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        rows = UserProfile.objects.filter(
            account_id__in=serializer.validated_data["account_ids"], deleted_at__isnull=True
        ).values_list("account_id", "handle", "display_name")
        return data_response({str(a): {"handle": h, "display_name": n} for a, h, n in rows})


class PageAccessView(APIView):
    """May ``account_id`` publish or delete posts as this page? Post asks before
    it writes a page post (and fails closed when profile cannot answer)."""

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes: list = []  # internal: no per-IP throttle (roadmap 3.3)

    def get(self, request: Request, page_id) -> Response:
        _require_internal(request)
        try:
            account_id = str(uuid.UUID(request.query_params.get("account_id", "")))
        except ValueError as exc:
            raise TaraAPIError(
                "account_id must be a UUID.", code="validation_error", http_status_code=400
            ) from exc
        found = page_access(str(page_id), account_id)
        if found is None:
            raise TaraAPIError("Page not found.", code="not_found", http_status_code=404)
        return data_response(found)


class PageTeamView(APIView):
    """Who is on this page's team, with their role. Chat asks when a member
    writes to the page, so the team hears of the message (page inbox)."""

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes: list = []  # internal

    def get(self, request: Request, page_id) -> Response:
        _require_internal(request)
        found = page_team(str(page_id))
        if found is None:
            raise TaraAPIError("Page not found.", code="not_found", http_status_code=404)
        return data_response({"members": found})


MAX_PAGE_IDS = 200


class _PageVisibilitySerializer(serializers.Serializer):
    page_ids = serializers.ListField(
        child=serializers.UUIDField(), allow_empty=True, max_length=MAX_PAGE_IDS
    )
    viewer_id = serializers.UUIDField(required=False, allow_null=True)


class PageVisibilityView(APIView):
    """Which of these pages may ``viewer_id`` see? Post asks before it shows a
    page's posts (detail, timelines, feed hydration, comments, the media check),
    so a draft, suspended or deleted page's posts are hidden from everyone
    outside the page's team. Without ``viewer_id``: published, live pages only.

    ``{"visible": [page_id, ...]}``; unknown ids are simply not listed.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes: list = []  # internal: no per-IP throttle (roadmap 3.3)

    def post(self, request: Request) -> Response:
        _require_internal(request)
        serializer = _PageVisibilitySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        v = serializer.validated_data
        viewer = str(v["viewer_id"]) if v.get("viewer_id") else None
        return data_response({"visible": visible_page_ids(v["page_ids"], viewer)})
