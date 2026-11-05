"""Backfill ``AccountRef`` lifecycle from identity's export (intelligence WP 3.3, D5).

Accounts deactivated or suspended before graph consumed ``account.deactivated`` /
``account.suspended`` stay "active" for graph (in people suggestions and in
fan-out audiences) until their next event. This reads
``/internal/v1/intel/export/accounts/`` (only the accounts that are not active,
``{account_id, deactivated, suspended}``) and applies each flag with the export's
``as_of`` clock through the same newest-wins writer as the events, so an event
newer than the export still wins.

After a complete scan, an account graph holds as inactive that identity no longer
lists is active again (its reactivation or unsuspension event was lost); that
also goes through the writer, at the scan's start time. Safe to re-run.

    python manage.py intel_backfill_accounts [--batch-size 200] [--rate 20] [--no-sweep]
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand

from graph import intel_backfill
from graph.handlers import set_lifecycle
from graph.models import AccountRef

FLAGS = ("deactivated", "suspended")


class Command(BaseCommand):
    help = "Backfill graph's account lifecycle (deactivated, suspended) from identity."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--batch-size", type=int, default=200)
        parser.add_argument("--rate", type=float, default=20.0, help="requests per second")
        parser.add_argument("--no-sweep", action="store_true", help="never mark accounts active")

    def handle(self, *args, **options) -> None:
        listed, applied, started = set(), 0, None
        for page in intel_backfill.pages(
            settings.IDENTITY_INTERNAL_URL,
            "intel/export/accounts/",
            "identity",
            limit=options["batch_size"],
            rate=options["rate"],
        ):
            started = started or page.as_of
            for item in page.items:
                p = item["payload"]
                listed.add(str(item["id"]))
                for flag in FLAGS:
                    applied += set_lifecycle(item["id"], flag, bool(p.get(flag)), page.as_of)

        swept = 0
        if not options["no_sweep"] and started is not None:
            stale = AccountRef.objects.filter(active=False).values_list("account_id", flat=True)
            for account_id in [a for a in stale if str(a) not in listed]:
                changed = [set_lifecycle(account_id, flag, False, started) for flag in FLAGS]
                swept += any(changed)
        self.stdout.write(
            self.style.SUCCESS(f"listed {len(listed)}, flags applied {applied}, swept {swept}")
        )
