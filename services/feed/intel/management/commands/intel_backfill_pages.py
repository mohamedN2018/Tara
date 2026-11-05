"""Backfill intel_page_ref (and the page authors' kind) from profile's export (WP 3.2).

python manage.py intel_backfill_pages [--kind K] [--after CURSOR] [--rate 20]
"""

from ._backfill import BackfillCommand


class Command(BackfillCommand):
    help = "Backfill intel_page_ref (and the page authors' kind) from profile's export (WP 3.2)."
    kinds = ("pages",)
