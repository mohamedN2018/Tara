from __future__ import annotations

from rest_framework import serializers

from .models import Listing, ListingMedia, MarketplaceCategory, SellerReview
from .money import ALLOWED_CURRENCIES, PRICE_TYPES, effective_price
from .services import AVAILABILITY, PUBLIC_STATUSES, availability_of

_MONEY = serializers.DecimalField(max_digits=19, decimal_places=4, read_only=True)


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = MarketplaceCategory
        fields = ["id", "slug", "name", "parent_id", "position"]


class ListingMediaSerializer(serializers.ModelSerializer):
    class Meta:
        model = ListingMedia
        fields = ["media_id", "position"]


def _money_field(**kw):
    return serializers.DecimalField(
        max_digits=19, decimal_places=4, min_value=0, allow_null=True, **kw
    )


class ListingCreateSerializer(serializers.Serializer):
    category_id = serializers.UUIDField()
    title = serializers.CharField(max_length=160)
    description = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=5000
    )
    price_type = serializers.ChoiceField(choices=PRICE_TYPES, required=False)
    # Omitted or null: no price (negotiable). Checked as a whole in money.resolve_pricing.
    price = _money_field(required=False, default=None)
    sale_price = _money_field(required=False, default=None)
    currency = serializers.CharField(max_length=8, default="USD")
    condition = serializers.ChoiceField(
        choices=Listing.Condition.values, default=Listing.Condition.GOOD
    )
    location = serializers.CharField(max_length=160, required=False, allow_blank=True, default="")
    media_ids = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)


class ListingUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=160, required=False)
    description = serializers.CharField(required=False, allow_blank=True, max_length=5000)
    price_type = serializers.ChoiceField(choices=PRICE_TYPES, required=False)
    price = _money_field(required=False)
    sale_price = _money_field(required=False)
    currency = serializers.CharField(max_length=8, required=False)
    condition = serializers.ChoiceField(choices=Listing.Condition.values, required=False)
    location = serializers.CharField(max_length=160, required=False, allow_blank=True)


class ListingSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    media = ListingMediaSerializer(many=True, read_only=True)
    effective_price = serializers.SerializerMethodField()
    availability = serializers.SerializerMethodField()
    is_saved = serializers.SerializerMethodField()

    class Meta:
        model = Listing
        fields = [
            "id",
            "seller_id",
            "category",
            "title",
            "description",
            "price_type",
            "price",
            "sale_price",
            "effective_price",
            "currency",
            "price_unconfirmed",
            "currency_unconfirmed",
            "condition",
            "location",
            "status",
            "availability",
            "save_count",
            "view_count",
            "inquiry_count",
            "is_saved",
            "media",
            "created_at",
            "updated_at",
        ]

    def get_effective_price(self, obj) -> str | None:
        value = effective_price(obj.price, obj.sale_price)
        return None if value is None else _MONEY.to_representation(value)

    def get_availability(self, obj) -> str | None:
        return availability_of(obj.status)

    def get_is_saved(self, obj) -> bool:
        return bool(getattr(obj, "is_saved", False))


class ViewerStateSerializer(serializers.Serializer):
    is_owner = serializers.BooleanField()
    is_saved = serializers.BooleanField()
    has_inquired = serializers.BooleanField()
    can_review = serializers.BooleanField()
    has_reviewed = serializers.BooleanField()


class ListingDetailSerializer(ListingSerializer):
    viewer = serializers.SerializerMethodField()

    class Meta(ListingSerializer.Meta):
        fields = [*ListingSerializer.Meta.fields, "viewer"]

    def get_viewer(self, obj) -> dict:
        return self.context.get("viewer", {})


class TransitionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["reserve", "reactivate", "mark_sold", "archive"])


class ReportSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=200)


class InquirySerializer(serializers.Serializer):
    message = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")


class InquiryResultSerializer(serializers.Serializer):
    inquiry_id = serializers.UUIDField()
    listing_id = serializers.UUIDField()
    seller_id = serializers.UUIDField()


# ---- search filters ---------------------------------------------------------


class CSVChoiceField(serializers.Field):
    """``a,b,c`` -> ``["a", "b", "c"]``, each one of ``choices``."""

    default_error_messages = {"invalid_choice": '"{input}" is not a valid choice.'}

    def __init__(self, choices, **kwargs):
        self.choices = tuple(choices)
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        items = []
        for raw in str(data).split(","):
            item = raw.strip()
            if not item:
                continue
            if item not in self.choices:
                self.fail("invalid_choice", input=item[:40])
            if item not in items:
                items.append(item)
        return items

    def to_representation(self, value):
        return ",".join(value)


SORTS = ("newest", "price_asc", "price_desc")


class ListingFilterSerializer(serializers.Serializer):
    q = serializers.CharField(max_length=100, required=False, allow_blank=True)
    category = serializers.SlugField(max_length=80, required=False)
    condition = CSVChoiceField(Listing.Condition.values, required=False)
    price_type = CSVChoiceField(PRICE_TYPES, required=False)
    availability = CSVChoiceField(tuple(AVAILABILITY.values()), required=False)
    location = serializers.CharField(max_length=160, required=False)
    currency = serializers.ChoiceField(choices=ALLOWED_CURRENCIES, required=False)
    min_price = serializers.DecimalField(
        max_digits=19, decimal_places=4, min_value=0, required=False
    )
    max_price = serializers.DecimalField(
        max_digits=19, decimal_places=4, min_value=0, required=False
    )
    sort = serializers.ChoiceField(choices=SORTS, default="newest")

    # Old names kept as aliases (roadmap 4.1).
    ALIASES = {"price_min": "min_price", "price_max": "max_price", "ordering": "sort"}

    @classmethod
    def from_query(cls, query_params) -> dict:
        data = {}
        for key in query_params:
            value = query_params.get(key)
            if value is None or str(value).strip() == "":
                continue  # `?min_price=` means "no filter", not an error
            name = cls.ALIASES.get(key, key)
            if name in data and key != name:
                continue  # the canonical name wins
            data[name] = value.strip()
        if "currency" in data:
            data["currency"] = data["currency"].upper()
        serializer = cls(data=data)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    def validate(self, attrs):
        lo, hi = attrs.get("min_price"), attrs.get("max_price")
        if lo is not None and hi is not None and lo > hi:
            raise serializers.ValidationError(
                {"max_price": "max_price must be greater than or equal to min_price."}
            )
        return attrs


class FacetValueSerializer(serializers.Serializer):
    value = serializers.CharField()
    count = serializers.IntegerField()


class FacetCategorySerializer(serializers.Serializer):
    slug = serializers.CharField()
    name = serializers.CharField()
    parent_id = serializers.UUIDField(allow_null=True)
    count = serializers.IntegerField()


class FacetsSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    category = FacetCategorySerializer(many=True)
    condition = FacetValueSerializer(many=True)
    price_type = FacetValueSerializer(many=True)
    availability = FacetValueSerializer(many=True)


class CompareQuerySerializer(serializers.Serializer):
    ids = serializers.CharField()

    def validate_ids(self, value):
        import uuid

        out = []
        for raw in value.split(","):
            item = raw.strip()
            if not item:
                continue
            try:
                item = str(uuid.UUID(item))
            except ValueError as exc:
                raise serializers.ValidationError("Each id must be a UUID.") from exc
            if item not in out:
                out.append(item)
        if not 1 <= len(out) <= 4:
            raise serializers.ValidationError("Compare between 1 and 4 listings.")
        return out


# ---- sellers and reviews ----------------------------------------------------


class SellerSummarySerializer(serializers.Serializer):
    seller_id = serializers.UUIDField()
    member_since = serializers.DateTimeField()
    active_listings_count = serializers.IntegerField()
    sold_listings_count = serializers.IntegerField()
    rating_avg = serializers.FloatField(allow_null=True)
    rating_count = serializers.IntegerField()
    response_hint = serializers.CharField(allow_null=True)


class ReviewCreateSerializer(serializers.Serializer):
    rating = serializers.IntegerField(min_value=1, max_value=5)
    body = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")


class SellerReviewSerializer(serializers.ModelSerializer):
    listing_title = serializers.SerializerMethodField()

    class Meta:
        model = SellerReview
        fields = [
            "id",
            "listing_id",
            "listing_title",
            "seller_id",
            "buyer_id",
            "rating",
            "body",
            "created_at",
        ]

    def get_listing_title(self, obj) -> str | None:
        # Only titles of listings anyone may still open.
        listing = obj.listing
        if listing.deleted_at is None and listing.status in PUBLIC_STATUSES:
            return listing.title
        return None
