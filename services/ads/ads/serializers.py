from __future__ import annotations

from django.core.validators import URLValidator
from rest_framework import serializers

from .models import AdCreative, AdSet, Campaign


class CampaignCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=160)
    objective = serializers.CharField(max_length=40, required=False, default="reach")
    budget = serializers.DecimalField(max_digits=19, decimal_places=4, min_value=0)
    currency = serializers.CharField(max_length=3, required=False, default="USD")
    schedule_start = serializers.DateTimeField(required=False, allow_null=True)
    schedule_end = serializers.DateTimeField(required=False, allow_null=True)


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
    placement = serializers.ChoiceField(
        choices=AdSet.Placement.values, default=AdSet.Placement.FEED
    )
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


class CreativeSerializer(serializers.ModelSerializer):
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
            "created_at",
        ]


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


class EventSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["impression", "click"])
    creative_id = serializers.UUIDField()
    token = serializers.CharField(max_length=1000)
