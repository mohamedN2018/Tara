"""Marketplace HTTP API: listings, search and facets, saves, compare, inquiries,
views, sellers and reviews, report, categories."""

from __future__ import annotations

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tara_common.pagination import CursorPagination
from tara_common.responses import data_response
from tara_resilience.idempotency import idempotent

from . import pagination, services, view_counter
from .models import IdempotencyRecord, MarketplaceCategory
from .serializers import (
    CategorySerializer,
    CompareQuerySerializer,
    FacetsSerializer,
    InquiriesQuerySerializer,
    InquiryResultSerializer,
    InquiryRowSerializer,
    InquirySerializer,
    ListingCreateSerializer,
    ListingDetailSerializer,
    ListingFilterSerializer,
    ListingSerializer,
    ListingUpdateSerializer,
    MyListingsQuerySerializer,
    ReportSerializer,
    ReviewCreateSerializer,
    SellerReviewSerializer,
    SellerSummarySerializer,
    SellingSummarySerializer,
    TransitionSerializer,
    inquiry_row,
)

SORTS = {
    "newest": pagination.Sort("newest", "created_at", True, "datetime"),
    # What the buyer pays (sale price first); listings with no price last either way.
    "price_asc": pagination.Sort("price_asc", "effective_price", False, "decimal"),
    "price_desc": pagination.Sort("price_desc", "effective_price", True, "decimal"),
}
SAVED_SORT = pagination.Sort("saved", "saved_at", True, "datetime")
REVIEWS_SORT = pagination.Sort("reviews", "created_at", True, "datetime")

_FILTER_PARAMS = [
    OpenApiParameter(name, str, required=False)
    for name in (
        "q",
        "seller_id",
        "category",
        "condition",
        "price_type",
        "availability",
        "location",
        "currency",
        "min_price",
        "max_price",
        "sort",
        "cursor",
        "limit",
    )
]


def _me(request: Request) -> str:
    return request.user.account_id


def _paginate(request, queryset, serializer_cls):
    paginator = CursorPagination()
    page = paginator.paginate_queryset(queryset, request)
    return paginator.get_paginated_response(serializer_cls(page, many=True).data)


def _listings(rows) -> list:
    return ListingSerializer(rows, many=True).data


def _detail(request: Request, listing) -> dict:
    viewer = services.viewer_state(_me(request), listing)
    return ListingDetailSerializer(listing, context={"viewer": viewer}).data


class CategoriesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: CategorySerializer(many=True)}, tags=["marketplace"])
    def get(self, request: Request) -> Response:
        return data_response(CategorySerializer(MarketplaceCategory.objects.all(), many=True).data)


class ListingsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=_FILTER_PARAMS,
        responses={200: ListingSerializer(many=True)},
        tags=["marketplace"],
    )
    def get(self, request: Request) -> Response:
        filters = ListingFilterSerializer.from_query(request.query_params)
        qs = services.search(_me(request), filters)
        return pagination.paginate(request, qs, SORTS[filters["sort"]], _listings)

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
                    "price_type": v.get("price_type"),
                    "price": v.get("price"),
                    "sale_price": v.get("sale_price"),
                    "currency": v["currency"],
                    "condition": v["condition"],
                    "location": v["location"],
                    "media_ids": [str(m) for m in v["media_ids"]],
                },
            )
            return data_response(ListingSerializer(listing).data, status=status.HTTP_201_CREATED)

        return idempotent(IdempotencyRecord, request, handler)


class FacetsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=_FILTER_PARAMS, responses={200: FacetsSerializer}, tags=["marketplace"]
    )
    def get(self, request: Request) -> Response:
        filters = ListingFilterSerializer.from_query(request.query_params)
        return data_response(services.facets(_me(request), filters))


class CompareView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[OpenApiParameter("ids", str, required=True)],
        responses={200: ListingSerializer(many=True)},
        tags=["marketplace"],
    )
    def get(self, request: Request) -> Response:
        query = CompareQuerySerializer(data={"ids": request.query_params.get("ids", "")})
        query.is_valid(raise_exception=True)
        rows = services.compare(_me(request), query.validated_data["ids"])
        return data_response(_listings(rows))


class MyListingsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[OpenApiParameter("status", str, required=False)],
        responses={200: ListingSerializer(many=True)},
        tags=["marketplace"],
    )
    def get(self, request: Request) -> Response:
        raw = (request.query_params.get("status") or "").strip()
        query = MyListingsQuerySerializer(data={"status": raw} if raw else {})
        query.is_valid(raise_exception=True)
        qs = services.my_listings(_me(request), query.validated_data.get("status"))
        return _paginate(request, qs, ListingSerializer)


class SellingSummaryView(APIView):
    """The seller's own numbers for the Selling overview (never anyone else's)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: SellingSummarySerializer}, tags=["marketplace"])
    def get(self, request: Request) -> Response:
        return data_response(SellingSummarySerializer(services.selling_summary(_me(request))).data)


class InquiriesListView(APIView):
    """The marketplace inbox: ``role=buyer`` (Buying) or ``role=seller`` (Selling)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[OpenApiParameter("role", str, required=False, enum=["buyer", "seller"])],
        responses={200: InquiryRowSerializer(many=True)},
        tags=["marketplace"],
    )
    def get(self, request: Request) -> Response:
        query = InquiriesQuerySerializer(data={"role": request.query_params.get("role", "buyer")})
        query.is_valid(raise_exception=True)
        role = query.validated_data["role"]
        me = _me(request)
        paginator = CursorPagination()
        page = paginator.paginate_queryset(services.inquiries(me, role), request)
        rows = [inquiry_row(i, role, services.inquiry_listing_visible(me, i)) for i in page or []]
        return paginator.get_paginated_response(InquiryRowSerializer(rows, many=True).data)


class ListingDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: ListingDetailSerializer}, tags=["marketplace"])
    def get(self, request: Request, listing_id: str) -> Response:
        return data_response(_detail(request, services.get_listing(_me(request), listing_id)))

    @extend_schema(
        request=ListingUpdateSerializer, responses={200: ListingSerializer}, tags=["marketplace"]
    )
    def patch(self, request: Request, listing_id: str) -> Response:
        serializer = ListingUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.update_listing(_me(request), listing_id, serializer.validated_data)
        return data_response(_detail(request, services.get_listing(_me(request), listing_id)))


class ListingViewBeacon(APIView):
    """The detail page reports one view; counted per viewer per cooldown window."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={202: None}, tags=["marketplace"])
    def post(self, request: Request, listing_id: str) -> Response:
        listing = services.get_listing(_me(request), listing_id)
        counted = False
        if str(listing.seller_id) != str(_me(request)):
            counted = view_counter.record_view(str(listing.id), _me(request))
        return data_response({"counted": counted}, status=status.HTTP_202_ACCEPTED)


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
        qs = services.list_saved(_me(request))
        return pagination.paginate(request, qs, SAVED_SORT, _listings)


class ReportView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=ReportSerializer, responses={202: None}, tags=["marketplace"])
    def post(self, request: Request, listing_id: str) -> Response:
        serializer = ReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.report_listing(_me(request), listing_id, serializer.validated_data["reason"])
        return data_response({"detail": "reported"}, status=status.HTTP_202_ACCEPTED)


class ContactView(APIView):
    """Legacy: chat opens a listing thread from the event. New clients use inquiries/."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=InquirySerializer, responses={202: None}, tags=["marketplace"])
    def post(self, request: Request, listing_id: str) -> Response:
        serializer = InquirySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.contact_seller(_me(request), listing_id, serializer.validated_data["message"])
        return data_response(
            {"detail": "Conversation requested; it will appear in your chats."},
            status=status.HTTP_202_ACCEPTED,
        )


class InquiryView(APIView):
    """Record that the buyer is messaging the seller; the client then opens the DM
    through chat's own API (``POST /conversations/``)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=InquirySerializer, responses={201: InquiryResultSerializer}, tags=["marketplace"]
    )
    def post(self, request: Request, listing_id: str) -> Response:
        serializer = InquirySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        inquiry = services.record_inquiry(
            _me(request), listing_id, serializer.validated_data["message"]
        )
        return data_response(
            {
                "inquiry_id": str(inquiry.id),
                "listing_id": str(inquiry.listing_id),
                "seller_id": str(inquiry.seller_id),
            },
            status=status.HTTP_201_CREATED,
        )


class ListingReviewsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=ReviewCreateSerializer,
        responses={201: SellerReviewSerializer},
        tags=["marketplace"],
    )
    def post(self, request: Request, listing_id: str) -> Response:
        serializer = ReviewCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        v = serializer.validated_data
        review = services.create_review(_me(request), listing_id, v["rating"], v["body"])
        return data_response(SellerReviewSerializer(review).data, status=status.HTTP_201_CREATED)


class SellerView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: SellerSummarySerializer}, tags=["marketplace"])
    def get(self, request: Request, seller_id: str) -> Response:
        summary = services.seller_summary(_me(request), str(seller_id))
        return data_response(SellerSummarySerializer(summary).data)


class SellerReviewsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: SellerReviewSerializer(many=True)}, tags=["marketplace"])
    def get(self, request: Request, seller_id: str) -> Response:
        qs = services.seller_reviews(_me(request), str(seller_id))
        return pagination.paginate(
            request, qs, REVIEWS_SORT, lambda rows: SellerReviewSerializer(rows, many=True).data
        )


class ReviewReportView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=ReportSerializer, responses={202: None}, tags=["marketplace"])
    def post(self, request: Request, review_id: str) -> Response:
        serializer = ReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.report_review(_me(request), str(review_id), serializer.validated_data["reason"])
        return data_response({"detail": "reported"}, status=status.HTTP_202_ACCEPTED)
