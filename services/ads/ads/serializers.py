from __future__ import annotations

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
            "review_status",
            "created_at",
        ]


class ReviewSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(
        choices=[AdCreative.Review.APPROVED, AdCreative.Review.REJECTED]
    )
    notes = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")


class EventSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["impression", "click"])
    creative_id = serializers.UUIDField()
