"""List (and, with --apply, classify) listings whose price was 0 under the old schema.

Migration 0004 already ran the classification; this re-runs it safely (idempotent)
and prints the listings still waiting for their seller to confirm the price.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from marketplace import backfill
from marketplace.models import Listing


class Command(BaseCommand):
    help = "Move price=0 listings to 'no price' and list those awaiting seller confirmation."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Classify before listing.")

    def handle(self, *args, apply: bool = False, **options):
        if apply:
            moved = backfill.classify_zero_price_listings(Listing)
            self.stdout.write(f"classified {moved} listing(s)")
        rows = Listing.objects.filter(price_unconfirmed=True, deleted_at__isnull=True).order_by(
            "seller_id", "created_at"
        )
        for row in rows.values("id", "seller_id", "title", "status"):
            self.stdout.write(f"{row['id']}\t{row['seller_id']}\t{row['status']}\t{row['title']}")
        self.stdout.write(f"{rows.count()} listing(s) awaiting price confirmation")
