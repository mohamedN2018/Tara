from __future__ import annotations

from rest_framework import serializers

from .models import Listing, ListingMedia, MarketplaceCategory


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = MarketplaceCategory
        fields = ["id", "slug", "name", "parent_id", "position"]


class ListingMediaSerializer(serializers.ModelSerializer):
    class Meta:
        model = ListingMedia
        fields = ["media_id", "position"]


class ListingCreateSerializer(serializers.Serializer):
    category_id = serializers.UUIDField()
    title = serializers.CharField(max_length=160)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    price = serializers.DecimalField(max_digits=19, decimal_places=4, min_value=0)
    currency = serializers.CharField(max_length=3, default="USD")
    condition = serializers.ChoiceField(
        choices=Listing.Condition.values, default=Listing.Condition.GOOD
    )
    location = serializers.CharField(max_length=160, required=False, allow_blank=True, default="")
    media_ids = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)


class ListingUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=160, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    price = serializers.DecimalField(max_digits=19, decimal_places=4, min_value=0, required=False)
    currency = serializers.CharField(max_length=3, required=False)
    condition = serializers.ChoiceField(choices=Listing.Condition.values, required=False)
    location = serializers.CharField(max_length=160, required=False, allow_blank=True)


class ListingSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    media = ListingMediaSerializer(many=True, read_only=True)

    class Meta:
        model = Listing
        fields = [
            "id",
            "seller_id",
            "category",
            "title",
            "description",
            "price",
            "currency",
            "condition",
            "location",
            "status",
            "save_count",
            "media",
            "created_at",
            "updated_at",
        ]


class TransitionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["reserve", "reactivate", "mark_sold", "archive"])


class ReportSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=200)
