"""Backfill ``AccountRef.restriction`` from moderation's export (intelligence WP 3.3,
rule E11, D14).

A ``restrict`` or ``shadow`` decided before graph consumed ``moderation.actioned``
keeps the account in people suggestions until its next decision. This reads
``/internal/v1/intel/export/restrictions/`` (every user case decided
``restrict`` / ``shadow`` that no appeal overturned) and applies it with the
export's ``as_of`` clock through the same newest-wins writer as the event.

After a complete scan, an account graph holds as restricted that moderation no
longer lists has no restriction standing (its ``reinstate`` was lost): it is
cleared, at the scan's start time. Safe to re-run.

    python manage.py intel_backfill_restrictions [--batch-size 200] [--rate 20] [--no-sweep]
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.core.management.base import BaseCommand

from graph import intel_backfill
from graph.handlers import RESTRICTING_ACTIONS, set_restriction
from graph.models import AccountRef


class Command(BaseCommand):
    help = "Backfill graph's account restrictions (restrict, shadow) from moderation."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--batch-size", type=int, default=200)
        parser.add_argument("--rate", type=float, default=20.0, help="requests per second")
        parser.add_argument("--no-sweep", action="store_true", help="never lift a restriction")

    def handle(self, *args, **options) -> None:
        listed, applied, started = set(), 0, None
        for page in intel_backfill.pages(
            settings.MODERATION_INTERNAL_URL,
            "intel/export/restrictions/",
            "moderation",
            limit=options["batch_size"],
            rate=options["rate"],
        ):
            started = started or page.as_of
            for item in page.items:
                p = item["payload"]
                try:
                    account_id = uuid.UUID(str(p.get("account_id")))
                except ValueError:
                    continue
                if p.get("action") not in RESTRICTING_ACTIONS:
                    continue
                listed.add(str(account_id))
                applied += set_restriction(account_id, p["action"], p.get("case_id"), page.as_of)

        swept = 0
        if not options["no_sweep"] and started is not None:
            held = AccountRef.objects.exclude(restriction="").values_list("account_id", flat=True)
            for account_id in [a for a in held if str(a) not in listed]:
                swept += set_restriction(account_id, "reinstate", None, started)
        self.stdout.write(
            self.style.SUCCESS(f"listed {len(listed)}, applied {applied}, swept {swept}")
        )
