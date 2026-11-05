"""Run the reels reconcile job by hand (beat runs it every 15 minutes).

    python manage.py reconcile_reels [--limit 500] [--dry-run]

Hides reels whose video media deleted, failed or bound elsewhere, binds an
unbound video back to its reel, and restores reels whose video is back. It
never deletes anything; ``--dry-run`` reports without writing or binding.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from ... import reconcile


class Command(BaseCommand):
    help = "Repair reels whose video was deleted, failed or unbound in media (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=reconcile.DEFAULT_LIMIT)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        stats = reconcile.reconcile(limit=options["limit"], dry_run=options["dry_run"])
        self.stdout.write(
            "checked={checked} hidden={hidden} restored={restored} rebound={rebound}"
            " stopped={stopped}".format(**stats)
        )
