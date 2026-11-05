"""Backfill intel_friend_edge, follow_edge (D6) and intel_block_pair from graph's exports (WP 3.2).

python manage.py intel_backfill_edges [--kind K] [--after CURSOR] [--rate 20]
"""

from ._backfill import BackfillCommand


class Command(BackfillCommand):
    help = (
        "Backfill intel_friend_edge, follow_edge (D6) and intel_block_pair "
        "from graph's exports (WP 3.2)."
    )
    kinds = (
        "friendships",
        "follows",
        "blocks",
    )
