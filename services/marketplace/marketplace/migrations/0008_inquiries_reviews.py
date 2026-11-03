# Roadmap 4.7/4.8 (first slice): buyer inquiries, seller reviews and review reports.
# New tables only.

import django.db.models.deletion
import tara_events.envelope
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("marketplace", "0007_search_indexes"),
    ]

    operations = [
        migrations.CreateModel(
            name="ListingInquiry",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=tara_events.envelope.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("seller_id", models.UUIDField()),
                ("buyer_id", models.UUIDField()),
                ("first_message", models.CharField(blank=True, default="", max_length=1000)),
                ("message_count", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("last_activity_at", models.DateTimeField(auto_now=True)),
                (
                    "listing",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="inquiries",
                        to="marketplace.listing",
                    ),
                ),
            ],
            options={
                "db_table": "listing_inquiry",
                "indexes": [
                    models.Index(
                        fields=["seller_id", "-last_activity_at"], name="inquiry_seller_idx"
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("listing", "buyer_id"), name="listing_inquiry_uniq"
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="SellerReview",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=tara_events.envelope.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("seller_id", models.UUIDField()),
                ("buyer_id", models.UUIDField()),
                ("rating", models.PositiveSmallIntegerField()),
                ("body", models.TextField(blank=True, default="", max_length=2000)),
                (
                    "status",
                    models.CharField(
                        choices=[("published", "Published"), ("removed", "Removed by moderators")],
                        default="published",
                        max_length=12,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "listing",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="reviews",
                        to="marketplace.listing",
                    ),
                ),
            ],
            options={
                "db_table": "seller_review",
                "indexes": [
                    models.Index(
                        fields=["seller_id", "status", "-created_at"], name="review_seller_idx"
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("listing", "buyer_id"), name="review_one_per_listing"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("rating__gte", 1), ("rating__lte", 5)),
                        name="review_rating_range",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="ReviewReport",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=tara_events.envelope.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("reporter_id", models.UUIDField()),
                ("reason", models.CharField(max_length=200)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "review",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="reports",
                        to="marketplace.sellerreview",
                    ),
                ),
            ],
            options={
                "db_table": "review_report",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("review", "reporter_id"), name="review_report_uniq"
                    )
                ],
            },
        ),
    ]
