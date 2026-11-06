"""Marketplace domain models (owns `market_db`)."""

from __future__ import annotations

from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Coalesce

from tara_events.envelope import uuid7
from tara_events.models import AbstractOutboxEvent, AbstractProcessedEvent
from tara_resilience.idempotency import AbstractIdempotencyRecord

from .money import ALLOWED_CURRENCIES, DEFAULT_CURRENCY


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
        REMOVED = "removed", "Removed by moderators"
        ARCHIVED = "archived", "Archived"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    seller_id = models.UUIDField()
    category = models.ForeignKey(
        MarketplaceCategory, on_delete=models.PROTECT, related_name="listings"
    )
    title = models.CharField(max_length=160)
    description = models.TextField(blank=True, default="")

    class PriceType(models.TextChoices):
        FIXED = "fixed", "Fixed price"
        NEGOTIABLE = "negotiable", "Negotiable"
        FREE = "free", "Free"

    # Null means "no price" (negotiable: make an offer); 0 only for free listings.
    price = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
    price_type = models.CharField(max_length=12, choices=PriceType.choices, default=PriceType.FIXED)
    sale_price = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
    # What a buyer pays, kept by Postgres so price sort and range filters run in SQL.
    effective_price = models.GeneratedField(
        expression=Coalesce("sale_price", "price"),
        output_field=models.DecimalField(max_digits=19, decimal_places=4, null=True),
        db_persist=True,
    )
    currency = models.CharField(max_length=3, default=DEFAULT_CURRENCY)
    # Set by the 4.3 data migration: the old schema stored 0 for both "free" and
    # "price on request", and free-text currencies; sellers confirm by editing.
    price_unconfirmed = models.BooleanField(default=False)
    currency_unconfirmed = models.BooleanField(default=False)
    condition = models.CharField(max_length=10, choices=Condition.choices, default=Condition.GOOD)
    location = models.CharField(max_length=160, blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    save_count = models.PositiveIntegerField(default=0)
    # Flushed from the Redis view buffer by a beat job, never written per hit.
    view_count = models.PositiveIntegerField(default=0)
    inquiry_count = models.PositiveIntegerField(default=0)
    # Normalised title + description; queried with `contains` so the trigram index is used.
    search_text = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    # The moderation case behind the last rejection or removal, so the seller can
    # see why and appeal it. The reason is filled only when moderation sends one.
    moderation_case_id = models.UUIDField(null=True, blank=True)
    moderation_reason = models.CharField(max_length=2000, blank=True, default="")

    class Meta:
        db_table = "listing"
        indexes = [
            models.Index(fields=["status", "category", "-created_at"], name="listing_browse_idx"),
            models.Index(fields=["seller_id"], name="listing_seller_idx"),
            models.Index(fields=["status", "created_at", "id"], name="listing_newest_idx"),
            models.Index(fields=["status", "effective_price", "id"], name="listing_price_idx"),
            GinIndex(
                fields=["search_text"], name="listing_search_trgm", opclasses=["gin_trgm_ops"]
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(price__isnull=True) | Q(price__gte=0), name="listing_price_nonneg"
            ),
            models.CheckConstraint(
                condition=Q(sale_price__isnull=True)
                | Q(price__isnull=False, sale_price__gte=0, sale_price__lt=F("price")),
                name="listing_sale_below_price",
            ),
            models.CheckConstraint(
                condition=Q(price_type="free", price=0, sale_price__isnull=True)
                | Q(price_type="fixed", price__gt=0)
                | (Q(price_type="negotiable") & (Q(price__isnull=True) | Q(price__gt=0))),
                name="listing_price_type_valid",
            ),
            models.CheckConstraint(
                condition=Q(currency__in=ALLOWED_CURRENCIES), name="listing_currency_allowed"
            ),
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
        indexes = [
            models.Index(fields=["account_id", "-created_at"], name="listing_save_recent_idx"),
        ]


class ListingReport(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="reports")
    reporter_id = models.UUIDField()
    reason = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "listing_report"


class ListingInquiry(models.Model):
    """A buyer messaged the seller about a listing (one row per buyer per listing).

    The conversation itself lives in chat; this read model is what makes a buyer
    eligible to review the seller, and later feeds response-time metrics (4.7).
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="inquiries")
    seller_id = models.UUIDField()
    buyer_id = models.UUIDField()
    first_message = models.CharField(max_length=1000, blank=True, default="")
    message_count = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    last_activity_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "listing_inquiry"
        constraints = [
            models.UniqueConstraint(fields=["listing", "buyer_id"], name="listing_inquiry_uniq"),
        ]
        indexes = [
            models.Index(fields=["seller_id", "-last_activity_at"], name="inquiry_seller_idx"),
            # The buyer's "Buying" inbox.
            models.Index(fields=["buyer_id", "-last_activity_at"], name="inquiry_buyer_idx"),
        ]


class SellerReview(models.Model):
    class Status(models.TextChoices):
        PUBLISHED = "published", "Published"
        REMOVED = "removed", "Removed by moderators"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="reviews")
    seller_id = models.UUIDField()
    buyer_id = models.UUIDField()
    rating = models.PositiveSmallIntegerField()
    body = models.TextField(max_length=2000, blank=True, default="")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PUBLISHED)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "seller_review"
        constraints = [
            models.UniqueConstraint(fields=["listing", "buyer_id"], name="review_one_per_listing"),
            models.CheckConstraint(
                condition=Q(rating__gte=1, rating__lte=5), name="review_rating_range"
            ),
        ]
        indexes = [
            models.Index(fields=["seller_id", "status", "-created_at"], name="review_seller_idx"),
        ]


class ReviewReport(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    review = models.ForeignKey(SellerReview, on_delete=models.CASCADE, related_name="reports")
    reporter_id = models.UUIDField()
    reason = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "review_report"
        constraints = [
            models.UniqueConstraint(fields=["review", "reporter_id"], name="review_report_uniq"),
        ]


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


# ---- Tara Intelligence read models (R4, WP 5.5) ----
class IntelConfig(models.Model):
    """The last published config of a surface (``intel.config.published``)."""

    surface = models.CharField(max_length=20, primary_key=True)
    version = models.PositiveIntegerField()
    params = models.JSONField(default=dict)
    experiment = models.JSONField(null=True, blank=True)
    published_at = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "intel_config"


class IntelExposureSeen(models.Model):
    """One row per (account, experiment) once its exposure was emitted."""

    id = models.BigAutoField(primary_key=True)
    account_id = models.UUIDField()
    experiment_key = models.CharField(max_length=60)
    variant = models.CharField(max_length=40)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "intel_exposure_seen"
        constraints = [
            models.UniqueConstraint(
                fields=["account_id", "experiment_key"], name="intel_exposure_seen_uniq"
            ),
        ]
