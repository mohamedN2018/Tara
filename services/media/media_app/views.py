"""Media HTTP API: signed upload, completion, metadata, download URL."""

from __future__ import annotations

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse
from django.utils.decorators import method_decorator
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tara_common.responses import data_response

from . import playback, services
from .serializers import ResolveSerializer, SignUploadSerializer
from .throttling import ResolveThrottle


class SignUploadView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=SignUploadSerializer, responses={201: None}, tags=["media"])
    def post(self, request: Request) -> Response:
        serializer = SignUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        v = serializer.validated_data
        result = services.sign_upload(
            request.user.account_id,
            kind=v["kind"],
            mime=v["mime"],
            size=v["size"],
            visibility=v["visibility"],
            purpose=v["purpose"],
        )
        return data_response(result, status=201)


# Completion commits its single-use claim, and the failed state of a rejected
# file, on its own, so a 400 does not roll them back; storage is called outside
# any transaction.
@method_decorator(transaction.non_atomic_requests, name="dispatch")
class CompleteUploadView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: None}, tags=["media"])
    def post(self, request: Request, media_id: str) -> Response:
        """Verify the uploaded object and start processing. A second call returns 409."""
        asset = services.complete_upload(request.user.account_id, media_id)
        return data_response(services.asset_payload(asset))


# Reads only; restricted media call post, which should not hold a transaction open.
@method_decorator(transaction.non_atomic_requests, name="dispatch")
class MediaDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: None}, tags=["media"])
    def get(self, request: Request, media_id: str) -> Response:
        asset = services.get_asset_for_viewer(request.user.account_id, media_id)
        return data_response(services.asset_payload(asset))


def _batch_ids(request: Request) -> list[str]:
    serializer = ResolveSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    return [str(i) for i in serializer.validated_data["ids"]]


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class ResolveView(APIView):
    """``POST {"ids": [...]}`` (at most 100): the detail payload of each media
    the viewer may see, in request order. Unknown and forbidden ids are simply
    absent, so a page resolves all its images in one call instead of one each."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [ResolveThrottle]

    @extend_schema(request=ResolveSerializer, responses={200: None}, tags=["media"])
    def post(self, request: Request) -> Response:
        assets = services.assets_for_viewer(request.user.account_id, _batch_ids(request))
        return data_response([services.asset_payload(a) for a in assets])


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class DownloadUrlView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: None}, tags=["media"])
    def get(self, request: Request, media_id: str) -> Response:
        url = services.download_url(request.user.account_id, media_id)
        return data_response({"download_url": url, "expires_in": settings.SIGNED_URL_TTL})


# ---- video playback (roadmap 5.3) ----------------------------------------------------


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class PlaybackView(APIView):
    """Where and how to play a transcoded video: a tokenised HLS playlist URL
    (relative to the API root), the poster and the MP4 fallback. 404 for a
    viewer who may not see the video's post, and for anyone but the owner
    before it is ready (the owner then gets its status and failure code)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: None}, tags=["media"])
    def get(self, request: Request, media_id: str) -> Response:
        return data_response(playback.playback(request.user.account_id, str(media_id)))


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class PlaybackResolveView(APIView):
    """``POST {"ids": [...]}`` (at most 100): ``playback`` for each video the
    viewer may watch, in request order; the others are absent."""

    permission_classes = [IsAuthenticated]
    throttle_classes = [ResolveThrottle]

    @extend_schema(request=ResolveSerializer, responses={200: None}, tags=["media"])
    def post(self, request: Request) -> Response:
        return data_response(playback.playback_many(request.user.account_id, _batch_ids(request)))


def _playlist_response(text: str) -> HttpResponse:
    response = HttpResponse(text, content_type=playback.PLAYLIST_TYPE)
    # Per viewer (the token is in the URL): never stored by a shared cache.
    response["Cache-Control"] = f"private, max-age={settings.MEDIA_PLAYBACK_ACCESS_CACHE_SECONDS}"
    response["Referrer-Policy"] = "no-referrer"
    return response


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class MasterPlaylistView(APIView):
    """The HLS master playlist. Authorised by ``?token=`` (native HLS players
    cannot send headers); access is checked again on every request."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(responses={200: None}, tags=["media"])
    def get(self, request: Request, media_id: str) -> HttpResponse:
        token = request.query_params.get("token", "")
        return _playlist_response(playback.master_playlist(token, str(media_id)))


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class RenditionPlaylistView(APIView):
    """One rendition's playlist, its segment URLs presigned for the current time bucket."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(responses={200: None}, tags=["media"])
    def get(self, request: Request, media_id: str, rung: int) -> HttpResponse:
        token = request.query_params.get("token", "")
        return _playlist_response(playback.rendition_playlist(token, str(media_id), int(rung)))
