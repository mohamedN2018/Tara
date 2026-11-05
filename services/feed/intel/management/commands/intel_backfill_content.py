"""Backfill intel_content_ref from post's export (WP 3.2).

python manage.py intel_backfill_content [--kind K] [--after CURSOR] [--rate 20]
"""

from ._backfill import BackfillCommand


class Command(BackfillCommand):
    help = "Backfill intel_content_ref from post's export (WP 3.2)."
    kinds = ("posts",)
