"""Advertisement HTTP API: advertiser setup, campaigns, creatives, review, events."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tara_common.responses import data_response
from tara_resilience.idempotency import idempotent

from . import services
from .models import IdempotencyRecord
from .permissions import IsAdReviewer
from .serializers import (
    AdSetCreateSerializer,
    AdSetSerializer,
    CampaignCreateSerializer,
    CampaignSerializer,
    CreativeCreateSerializer,
    CreativeSerializer,
    EventSerializer,
    ReviewSerializer,
)


def _me(request: Request) -> str:
    return request.user.account_id


class CampaignsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: CampaignSerializer(many=True)}, tags=["ads"])
    def get(self, request: Request) -> Response:
        advertiser = services.ensure_advertiser(_me(request))
        return data_response(
            CampaignSerializer(advertiser.campaigns.order_by("-created_at"), many=True).data
        )

    @extend_schema(
        request=CampaignCreateSerializer, responses={201: CampaignSerializer}, tags=["ads"]
    )
    def post(self, request: Request) -> Response:
        serializer = CampaignCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        campaign = services.create_campaign(_me(request), serializer.validated_data)
        return data_response(CampaignSerializer(campaign).data, status=status.HTTP_201_CREATED)


class CampaignReportView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: None}, tags=["ads"])
    def get(self, request: Request, campaign_id: str) -> Response:
        return data_response(services.campaign_report(_me(request), campaign_id))


class AdSetsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=AdSetCreateSerializer, responses={201: AdSetSerializer}, tags=["ads"])
    def post(self, request: Request, campaign_id: str) -> Response:
        serializer = AdSetCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ad_set = services.create_ad_set(_me(request), campaign_id, serializer.validated_data)
        return data_response(AdSetSerializer(ad_set).data, status=status.HTTP_201_CREATED)


class CreativesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=CreativeCreateSerializer, responses={201: CreativeSerializer}, tags=["ads"]
    )
    def post(self, request: Request, ad_set_id: str) -> Response:
        serializer = CreativeCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        if data.get("media_id"):
            data["media_id"] = str(data["media_id"])
        creative = services.create_creative(_me(request), ad_set_id, data)
        return data_response(CreativeSerializer(creative).data, status=status.HTTP_201_CREATED)


class ReviewView(APIView):
    permission_classes = [IsAdReviewer]

    @extend_schema(request=ReviewSerializer, responses={200: CreativeSerializer}, tags=["ads"])
    def post(self, request: Request, creative_id: str) -> Response:
        serializer = ReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        creative = services.review_creative(
            _me(request),
            creative_id,
            serializer.validated_data["decision"],
            serializer.validated_data["notes"],
        )
        return data_response(CreativeSerializer(creative).data)


class EventsView(APIView):
    """Impression/click ingest. Deduplicated via Idempotency-Key; rate-limited."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "ad_events"

    @extend_schema(request=EventSerializer, responses={202: None}, tags=["ads"])
    def post(self, request: Request) -> Response:
        serializer = EventSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        v = serializer.validated_data

        def handler() -> Response:
            services.record_event(v["kind"], str(v["creative_id"]), _me(request))
            return data_response({"detail": "recorded"}, status=status.HTTP_202_ACCEPTED)

        return idempotent(IdempotencyRecord, request, handler)
