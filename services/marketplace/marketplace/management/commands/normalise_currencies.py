"""Map free-text currencies onto the allow-list; list the ones flagged for review.

Migration 0004 already ran this; it is idempotent and safe to re-run.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from marketplace import backfill
from marketplace.models import Listing


class Command(BaseCommand):
    help = "Normalise listing currencies and list the listings flagged for currency review."

    def handle(self, *args, **options):
        mapped, flagged = backfill.normalise_currencies(Listing)
        self.stdout.write(f"mapped {mapped}, flagged {flagged}")
        rows = Listing.objects.filter(currency_unconfirmed=True, deleted_at__isnull=True)
        for row in rows.values("id", "seller_id", "currency", "title"):
            self.stdout.write(f"{row['id']}\t{row['seller_id']}\t{row['currency']}\t{row['title']}")
        self.stdout.write(f"{rows.count()} listing(s) flagged for currency review")
