"""Media HTTP API: signed upload, completion, metadata, download URL."""

from __future__ import annotations

from django.conf import settings
from django.db import transaction
from django.utils.decorators import method_decorator
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tara_common.responses import data_response

from . import services
from .serializers import SignUploadSerializer


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


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class DownloadUrlView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: None}, tags=["media"])
    def get(self, request: Request, media_id: str) -> Response:
        url = services.download_url(request.user.account_id, media_id)
        return data_response({"download_url": url, "expires_in": settings.SIGNED_URL_TTL})
