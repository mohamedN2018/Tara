"""Marketplace domain models (owns `market_db`)."""

from __future__ import annotations

from django.db import models

from tara_events.envelope import uuid7
from tara_events.models import AbstractOutboxEvent, AbstractProcessedEvent
from tara_resilience.idempotency import AbstractIdempotencyRecord


class MarketplaceCategory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    parent = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="children"
    )
    slug = models.SlugField(max_length=80, unique=True)
    name = models.CharField(max_length=120)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "marketplace_category"
        ordering = ["position", "name"]

    def __str__(self) -> str:
        return self.name


class SellerProfile(models.Model):
    account_id = models.UUIDField(primary_key=True)
    rating_avg = models.FloatField(default=0.0)
    rating_count = models.PositiveIntegerField(default=0)
    response_time_ms = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "seller_profile"


class Listing(models.Model):
    class Condition(models.TextChoices):
        NEW = "new", "New"
        LIKE_NEW = "like_new", "Like new"
        GOOD = "good", "Good"
        FAIR = "fair", "Fair"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING = "pending_review", "Pending review"
        ACTIVE = "active", "Active"
        RESERVED = "reserved", "Reserved"
        SOLD = "sold", "Sold"
        REJECTED = "rejected", "Rejected"
        ARCHIVED = "archived", "Archived"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    seller_id = models.UUIDField()
    category = models.ForeignKey(
        MarketplaceCategory, on_delete=models.PROTECT, related_name="listings"
    )
    title = models.CharField(max_length=160)
    description = models.TextField(blank=True, default="")
    price = models.DecimalField(max_digits=19, decimal_places=4, default=0)
    currency = models.CharField(max_length=3, default="USD")
    condition = models.CharField(max_length=10, choices=Condition.choices, default=Condition.GOOD)
    location = models.CharField(max_length=160, blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    save_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "listing"
        indexes = [
            models.Index(fields=["status", "category", "-created_at"], name="listing_browse_idx"),
            models.Index(fields=["seller_id"], name="listing_seller_idx"),
        ]


class ListingMedia(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="media")
    media_id = models.UUIDField()
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "listing_media"
        ordering = ["position"]


class ListingSave(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    account_id = models.UUIDField()
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="saves")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "listing_save"
        constraints = [
            models.UniqueConstraint(fields=["account_id", "listing"], name="listing_save_uniq"),
        ]


class ListingReport(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="reports")
    reporter_id = models.UUIDField()
    reason = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "listing_report"


class BlockedPair(models.Model):
    blocker_id = models.UUIDField()
    blocked_id = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "blocked_pair"
        constraints = [
            models.UniqueConstraint(
                fields=["blocker_id", "blocked_id"], name="market_blocked_pair_uniq"
            ),
        ]


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
