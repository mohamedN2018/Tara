"""Advertisement domain models (owns `ads_db`).

High-volume impression/click tables are day-partition candidates and, at scale,
move to the Kafka firehose + OLAP (ADR-003 / doc 05). Money is numeric(19,4).
"""

from __future__ import annotations

from django.db import models

from tara_events.envelope import uuid7
from tara_events.models import AbstractOutboxEvent, AbstractProcessedEvent
from tara_resilience.idempotency import AbstractIdempotencyRecord


class AdvertiserAccount(models.Model):
    # The only billing status that serves (WP 4.11); every other value is refused.
    BILLING_ACTIVE = "active"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    owner_account_id = models.UUIDField(unique=True)
    name = models.CharField(max_length=160)
    billing_status = models.CharField(max_length=16, default="active")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "advertiser_account"


class Campaign(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        PAUSED = "paused", "Paused"
        COMPLETED = "completed", "Completed"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    advertiser = models.ForeignKey(
        AdvertiserAccount, on_delete=models.CASCADE, related_name="campaigns"
    )
    name = models.CharField(max_length=160)
    objective = models.CharField(max_length=40, default="reach")
    budget = models.DecimalField(max_digits=19, decimal_places=4, default=0)
    spent = models.DecimalField(max_digits=19, decimal_places=4, default=0)
    currency = models.CharField(max_length=3, default="USD")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    schedule_start = models.DateTimeField(null=True, blank=True)
    schedule_end = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "campaign"

    @property
    def budget_remaining(self):
        return self.budget - self.spent


class AdSet(models.Model):
    class Placement(models.TextChoices):
        FEED = "feed", "Feed"
        MARKETPLACE = "marketplace", "Marketplace"
        SEARCH = "search", "Search"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name="ad_sets")
    name = models.CharField(max_length=160, blank=True, default="")
    targeting = models.JSONField(default=dict, blank=True)  # architecture only (not evaluated yet)
    placement = models.CharField(max_length=12, choices=Placement.choices, default=Placement.FEED)
    cpc = models.DecimalField(max_digits=19, decimal_places=4, default=0)  # cost per click
    cpm = models.DecimalField(
        max_digits=19, decimal_places=4, default=0
    )  # cost per 1000 impressions
    frequency_cap = models.PositiveSmallIntegerField(default=0)  # 0 = service default
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ad_set"


class AdCreative(models.Model):
    class Review(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    ad_set = models.ForeignKey(AdSet, on_delete=models.CASCADE, related_name="creatives")
    headline = models.CharField(max_length=120)
    body = models.CharField(max_length=400, blank=True, default="")
    media_id = models.UUIDField(null=True, blank=True)
    cta = models.CharField(max_length=40, default="Learn more")
    link_url = models.URLField(max_length=500, blank=True, default="")
    review_status = models.CharField(max_length=10, choices=Review.choices, default=Review.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ad_creative"
        indexes = [models.Index(fields=["review_status"], name="creative_review_idx")]


class AdReview(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    creative = models.ForeignKey(AdCreative, on_delete=models.CASCADE, related_name="reviews")
    reviewer_id = models.UUIDField()
    decision = models.CharField(max_length=10)  # approved | rejected
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ad_review"


class AdImpressionEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    creative = models.ForeignKey(AdCreative, on_delete=models.CASCADE, related_name="impressions")
    viewer_bucket = models.CharField(max_length=8)  # coarse, privacy-safe (not raw viewer id)
    placement = models.CharField(max_length=12)
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ad_impression_event"
        indexes = [models.Index(fields=["creative", "occurred_at"], name="impr_creative_idx")]


class AdClickEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    creative = models.ForeignKey(AdCreative, on_delete=models.CASCADE, related_name="clicks")
    viewer_bucket = models.CharField(max_length=8)
    placement = models.CharField(max_length=12)
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ad_click_event"
        indexes = [models.Index(fields=["creative", "occurred_at"], name="click_creative_idx")]


class AdBudgetLedger(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    advertiser = models.ForeignKey(
        AdvertiserAccount, on_delete=models.CASCADE, related_name="ledger"
    )
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name="ledger")
    entry_type = models.CharField(max_length=12, default="debit")
    amount = models.DecimalField(max_digits=19, decimal_places=4)
    currency = models.CharField(max_length=3, default="USD")
    balance_after = models.DecimalField(max_digits=19, decimal_places=4)
    reason = models.CharField(max_length=40, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ad_budget_ledger"


class OutboxEvent(AbstractOutboxEvent):
    class Meta(AbstractOutboxEvent.Meta):
        abstract = False
        db_table = "outbox_event"


class ProcessedEvent(AbstractProcessedEvent):
    class Meta(AbstractProcessedEvent.Meta):
        abstract = False
        db_table = "processed_event"


class IdempotencyRecord(AbstractIdempotencyRecord):
    class Meta(AbstractIdempotencyRecord.Meta):
        abstract = False
        db_table = "idempotency_record"
