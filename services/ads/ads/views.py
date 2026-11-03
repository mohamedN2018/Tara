"""Advertisement HTTP API: advertiser setup, campaigns, creatives, review, events."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from tara_common.pagination import CursorPagination
from tara_common.responses import data_response
from tara_resilience.idempotency import idempotent

from . import serve_tokens, services
from .models import Campaign, IdempotencyRecord
from .permissions import IsAdReviewer
from .serializers import (
    AdSetCreateSerializer,
    AdSetDetailSerializer,
    AdSetSerializer,
    CampaignCreateSerializer,
    CampaignSerializer,
    CampaignUpdateSerializer,
    CreativeCreateSerializer,
    CreativeSerializer,
    EventSerializer,
    ReviewQueueSerializer,
    ReviewSerializer,
)


def _me(request: Request) -> str:
    return request.user.account_id


class CampaignsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: CampaignSerializer(many=True)}, tags=["ads"])
    def get(self, request: Request) -> Response:
        # A read never creates the advertiser account; the first campaign does.
        campaigns = Campaign.objects.filter(advertiser__owner_account_id=_me(request))
        return data_response(CampaignSerializer(campaigns.order_by("-created_at"), many=True).data)

    @extend_schema(
        request=CampaignCreateSerializer, responses={201: CampaignSerializer}, tags=["ads"]
    )
    def post(self, request: Request) -> Response:
        serializer = CampaignCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        campaign = services.create_campaign(_me(request), serializer.validated_data)
        return data_response(CampaignSerializer(campaign).data, status=status.HTTP_201_CREATED)


class CampaignDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=CampaignUpdateSerializer, responses={200: CampaignSerializer}, tags=["ads"]
    )
    def patch(self, request: Request, campaign_id: str) -> Response:
        serializer = CampaignUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        campaign = services.set_campaign_status(
            _me(request), campaign_id, serializer.validated_data["status"]
        )
        return data_response(CampaignSerializer(campaign).data)


class CampaignReportView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: None}, tags=["ads"])
    def get(self, request: Request, campaign_id: str) -> Response:
        return data_response(services.campaign_report(_me(request), campaign_id))


class AdSetsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: AdSetDetailSerializer(many=True)}, tags=["ads"])
    def get(self, request: Request, campaign_id: str) -> Response:
        ad_sets = services.campaign_ad_sets(_me(request), campaign_id)
        return data_response(AdSetDetailSerializer(ad_sets, many=True).data)

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


class ReviewQueueView(APIView):
    permission_classes = [IsAdReviewer]

    @extend_schema(responses={200: ReviewQueueSerializer(many=True)}, tags=["ads"])
    def get(self, request: Request) -> Response:
        paginator = CursorPagination()
        page = paginator.paginate_queryset(services.review_queue(_me(request)), request)
        return paginator.get_paginated_response(ReviewQueueSerializer(page, many=True).data)


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
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "ad_events"

    @extend_schema(request=EventSerializer, responses={202: None}, tags=["ads"])
    def post(self, request: Request) -> Response:
        serializer = EventSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        v = serializer.validated_data

        creative_id = str(v["creative_id"])
        claims = serve_tokens.verify(v["token"], _me(request), creative_id)

        def handler() -> Response:
            # A token pays once, and a viewer once per window across tokens.
            if serve_tokens.spend(claims, v["kind"]) and services.first_in_window(
                v["kind"], creative_id, _me(request)
            ):
                services.record_event(v["kind"], creative_id, _me(request))
            return data_response({"detail": "recorded"}, status=status.HTTP_202_ACCEPTED)

        return idempotent(IdempotencyRecord, request, handler)
