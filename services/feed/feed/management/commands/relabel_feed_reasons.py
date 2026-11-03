"""One-off data fix: label existing items between friends as `friend`.

Before milestone 1.1 every item that was not the author's own was stored as
`follow`. Unfollow now deletes only `follow` items, so an old item between
friends must be relabelled, or unfollowing a friend would still drop it.

Friendship is symmetric, so each recipient's friends (Graph's internal fan-out
endpoint) are exactly the authors whose items it got as a friend. Recipients are
paged in id order and each one commits on its own, so the command can stop and
resume (`--after`). It only ever turns `follow` into `friend`, so running it
again is safe.

    python manage.py relabel_feed_reasons [--dry-run] [--after <uuid>] [--batch-size 500]
"""

from __future__ import annotations

import uuid

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Relabel existing feed items between friends as reason=friend (idempotent)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--dry-run", action="store_true", help="Count, change nothing.")
        parser.add_argument("--after", type=uuid.UUID, help="Resume after this recipient id.")
        parser.add_argument("--batch-size", type=int, default=500)

    def handle(self, *args, **options) -> None:
        from feed import services
        from feed.clients import GraphUnavailable, fanout_audience
        from feed.models import FeedItem

        dry_run = options["dry_run"]
        batch_size = max(int(options["batch_size"]), 1)
        after = options["after"]
        recipients = relabelled = 0

        while True:
            page = FeedItem.objects.filter(reason=FeedItem.Reason.FOLLOW)
            if after is not None:
                page = page.filter(recipient_id__gt=after)
            ids = list(
                page.order_by("recipient_id")
                .values_list("recipient_id", flat=True)
                .distinct()[:batch_size]
            )
            if not ids:
                break
            for recipient_id in ids:
                try:
                    friends = fanout_audience(str(recipient_id)).get("friends", [])
                except GraphUnavailable as exc:
                    raise CommandError(
                        f"graph unavailable ({exc}); resume with --after {after}"
                        if after
                        else f"graph unavailable ({exc}); run again"
                    ) from exc
                friends = [str(f) for f in friends if str(f) != str(recipient_id)]
                relabelled += services.relabel_friend_items_for(
                    str(recipient_id), friends, dry_run=dry_run
                )
                recipients += 1
                after = recipient_id

        verb = "would relabel" if dry_run else "relabelled"
        self.stdout.write(
            self.style.SUCCESS(f"{verb} {relabelled} items across {recipients} recipients")
        )
