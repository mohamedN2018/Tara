"""Marketplace HTTP API: listings, search, saves, report, contact, categories."""

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
from .models import IdempotencyRecord, MarketplaceCategory
from .serializers import (
    CategorySerializer,
    ListingCreateSerializer,
    ListingSerializer,
    ListingUpdateSerializer,
    ReportSerializer,
    TransitionSerializer,
)


def _me(request: Request) -> str:
    return request.user.account_id


def _paginate(request, queryset, serializer_cls):
    paginator = CursorPagination()
    page = paginator.paginate_queryset(queryset, request)
    return paginator.get_paginated_response(serializer_cls(page, many=True).data)


class CategoriesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: CategorySerializer(many=True)}, tags=["marketplace"])
    def get(self, request: Request) -> Response:
        return data_response(CategorySerializer(MarketplaceCategory.objects.all(), many=True).data)


class ListingsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: ListingSerializer(many=True)}, tags=["marketplace"])
    def get(self, request: Request) -> Response:
        qp = request.query_params
        filters = {
            "category": qp.get("category"),
            "condition": qp.get("condition"),
            "location": qp.get("location"),
            "min_price": qp.get("min_price"),
            "max_price": qp.get("max_price"),
            "q": qp.get("q"),
        }
        return _paginate(request, services.search(_me(request), filters), ListingSerializer)

    @extend_schema(
        request=ListingCreateSerializer, responses={201: ListingSerializer}, tags=["marketplace"]
    )
    def post(self, request: Request) -> Response:
        serializer = ListingCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        v = serializer.validated_data

        def handler() -> Response:
            listing = services.create_listing(
                _me(request),
                {
                    "category_id": str(v["category_id"]),
                    "title": v["title"],
                    "description": v["description"],
                    "price": v["price"],
                    "currency": v["currency"],
                    "condition": v["condition"],
                    "location": v["location"],
                    "media_ids": [str(m) for m in v["media_ids"]],
                },
            )
            return data_response(ListingSerializer(listing).data, status=status.HTTP_201_CREATED)

        return idempotent(IdempotencyRecord, request, handler)


class MyListingsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: ListingSerializer(many=True)}, tags=["marketplace"])
    def get(self, request: Request) -> Response:
        return _paginate(request, services.my_listings(_me(request)), ListingSerializer)


class ListingDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: ListingSerializer}, tags=["marketplace"])
    def get(self, request: Request, listing_id: str) -> Response:
        return data_response(ListingSerializer(services.get_listing(_me(request), listing_id)).data)

    @extend_schema(
        request=ListingUpdateSerializer, responses={200: ListingSerializer}, tags=["marketplace"]
    )
    def patch(self, request: Request, listing_id: str) -> Response:
        serializer = ListingUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        listing = services.update_listing(_me(request), listing_id, serializer.validated_data)
        return data_response(ListingSerializer(listing).data)


class PublishView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: ListingSerializer}, tags=["marketplace"])
    def post(self, request: Request, listing_id: str) -> Response:
        return data_response(
            ListingSerializer(services.publish_listing(_me(request), listing_id)).data
        )


class TransitionView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=TransitionSerializer, responses={200: ListingSerializer}, tags=["marketplace"]
    )
    def post(self, request: Request, listing_id: str) -> Response:
        serializer = TransitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        listing = services.transition(_me(request), listing_id, serializer.validated_data["action"])
        return data_response(ListingSerializer(listing).data)


class SaveView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: None}, tags=["marketplace"])
    def post(self, request: Request, listing_id: str) -> Response:
        services.save_listing(_me(request), listing_id)
        return data_response({"detail": "saved"})

    @extend_schema(responses={204: None}, tags=["marketplace"])
    def delete(self, request: Request, listing_id: str) -> Response:
        services.unsave_listing(_me(request), listing_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class SavedListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: ListingSerializer(many=True)}, tags=["marketplace"])
    def get(self, request: Request) -> Response:
        return _paginate(request, services.list_saved(_me(request)), ListingSerializer)


class ReportView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=ReportSerializer, responses={202: None}, tags=["marketplace"])
    def post(self, request: Request, listing_id: str) -> Response:
        serializer = ReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.report_listing(_me(request), listing_id, serializer.validated_data["reason"])
        return data_response({"detail": "reported"}, status=status.HTTP_202_ACCEPTED)


class ContactView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={202: None}, tags=["marketplace"])
    def post(self, request: Request, listing_id: str) -> Response:
        services.contact_seller(_me(request), listing_id)
        return data_response(
            {"detail": "Conversation requested; it will appear in your chats."},
            status=status.HTTP_202_ACCEPTED,
        )
