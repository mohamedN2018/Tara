from __future__ import annotations

from django.core.validators import URLValidator
from rest_framework import serializers

from .models import AdCreative, AdSet, Campaign

# Budget currencies ads accepts (ISO 4217); billing in others is not supported.
CAMPAIGN_CURRENCIES = ("AED", "BHD", "EGP", "EUR", "GBP", "JOD", "KWD", "OMR", "QAR", "SAR", "USD")
# What the advertiser wants. Delivery is not optimised by it yet: it picks the
# headline result of the campaign report (reach: impressions; traffic and
# engagement: clicks).
CAMPAIGN_OBJECTIVES = ("reach", "traffic", "engagement")
# Placements something actually asks a slot for: feed (feed service) and
# marketplace (the browse grid, ``GET /ads/slot/``). Search has no slot yet, so
# a new ad set cannot pick it; old rows keep the model's wider choices.
SERVED_PLACEMENTS = ("feed", "marketplace")
# Placements the web client may ask a slot for directly (feed's comes from feed).
CLIENT_SLOT_PLACEMENTS = ("marketplace",)


class CampaignCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=160)
    objective = serializers.ChoiceField(
        choices=CAMPAIGN_OBJECTIVES, required=False, default="reach"
    )
    budget = serializers.DecimalField(max_digits=19, decimal_places=4, min_value=0)
    currency = serializers.CharField(max_length=3, required=False, default="USD")
    schedule_start = serializers.DateTimeField(required=False, allow_null=True)
    schedule_end = serializers.DateTimeField(required=False, allow_null=True)

    def validate_currency(self, value: str) -> str:
        code = value.strip().upper()
        if code not in CAMPAIGN_CURRENCIES:
            raise serializers.ValidationError("This currency is not supported.")
        return code

    def validate(self, attrs):
        start, end = attrs.get("schedule_start"), attrs.get("schedule_end")
        if start is not None and end is not None and end <= start:
            raise serializers.ValidationError(
                {"schedule_end": "schedule_end must be after schedule_start."}
            )
        return attrs


class CampaignSerializer(serializers.ModelSerializer):
    class Meta:
        model = Campaign
        fields = [
            "id",
            "name",
            "objective",
            "budget",
            "spent",
            "currency",
            "status",
            "schedule_start",
            "schedule_end",
            "created_at",
        ]


class AdSetCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=160, required=False, allow_blank=True, default="")
    targeting = serializers.DictField(required=False, default=dict)
    placement = serializers.ChoiceField(choices=SERVED_PLACEMENTS, default=AdSet.Placement.FEED)
    cpc = serializers.DecimalField(max_digits=19, decimal_places=4, min_value=0, default=0)
    cpm = serializers.DecimalField(max_digits=19, decimal_places=4, min_value=0, default=0)
    frequency_cap = serializers.IntegerField(min_value=0, default=0)


class AdSetSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdSet
        fields = [
            "id",
            "campaign_id",
            "name",
            "targeting",
            "placement",
            "cpc",
            "cpm",
            "frequency_cap",
            "created_at",
        ]


class CreativeCreateSerializer(serializers.Serializer):
    headline = serializers.CharField(max_length=120)
    body = serializers.CharField(max_length=400, required=False, allow_blank=True, default="")
    media_id = serializers.UUIDField(required=False, allow_null=True)
    cta = serializers.CharField(max_length=40, required=False, default="Learn more")
    link_url = serializers.URLField(
        max_length=500,
        required=False,
        allow_blank=True,
        default="",
        validators=[URLValidator(schemes=["https"])],
    )


class CreativeUpdateSerializer(serializers.Serializer):
    """Edit and resubmit: every field optional, the same rules as create."""

    headline = serializers.CharField(max_length=120, required=False)
    body = serializers.CharField(max_length=400, required=False, allow_blank=True)
    media_id = serializers.UUIDField(required=False, allow_null=True)
    cta = serializers.CharField(max_length=40, required=False)
    link_url = serializers.URLField(
        max_length=500,
        required=False,
        allow_blank=True,
        validators=[URLValidator(schemes=["https"])],
    )


class CreativeSerializer(serializers.ModelSerializer):
    # The reviewer's reason, shown to the advertiser while the ad stays rejected.
    review_notes = serializers.SerializerMethodField()

    class Meta:
        model = AdCreative
        fields = [
            "id",
            "ad_set_id",
            "headline",
            "body",
            "media_id",
            "cta",
            "link_url",
            "review_status",
            "review_notes",
            "created_at",
        ]

    def get_review_notes(self, obj) -> str | None:
        if obj.review_status != AdCreative.Review.REJECTED:
            return None
        # Prefetched by the owner's listing; newest decision first.
        reviews = sorted(obj.reviews.all(), key=lambda r: (r.created_at, str(r.id)), reverse=True)
        return reviews[0].notes if reviews else ""


class AdSetDetailSerializer(AdSetSerializer):
    creatives = CreativeSerializer(many=True, read_only=True)

    class Meta(AdSetSerializer.Meta):
        fields = [*AdSetSerializer.Meta.fields, "creatives"]


class ReviewQueueSerializer(CreativeSerializer):
    campaign_name = serializers.CharField(source="ad_set.campaign.name")
    advertiser_name = serializers.CharField(source="ad_set.campaign.advertiser.name")
    placement = serializers.CharField(source="ad_set.placement")

    class Meta(CreativeSerializer.Meta):
        fields = [*CreativeSerializer.Meta.fields, "campaign_name", "advertiser_name", "placement"]


class CampaignUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=[Campaign.Status.ACTIVE, Campaign.Status.PAUSED])


class ReviewSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(
        choices=[AdCreative.Review.APPROVED, AdCreative.Review.REJECTED]
    )
    notes = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")

    def validate(self, attrs):
        # The advertiser sees this reason: a rejection without one tells them nothing.
        if attrs["decision"] == AdCreative.Review.REJECTED and not attrs["notes"].strip():
            raise serializers.ValidationError({"notes": "Say why the ad is rejected."})
        return attrs


class SlotQuerySerializer(serializers.Serializer):
    placement = serializers.ChoiceField(choices=CLIENT_SLOT_PLACEMENTS)


class EventSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["impression", "click"])
    creative_id = serializers.UUIDField()
    token = serializers.CharField(max_length=1000)
