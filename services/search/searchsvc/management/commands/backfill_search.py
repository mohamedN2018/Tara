"""Index existing data from the owners' internal export endpoints (search v2, 1.15).

Each owner pages through what may be searched today (public profiles, published
pages, public and private groups, live public posts, public events, active
listings) and returns it in the
same shape as its events, so the same builders index it. Snapshots go through
the event-order guard with ``version = as_of - 60 s`` (``as_of`` is the owner's
clock when it read the page), so a change that committed during the read is
applied again by its own event, and nothing newer is ever overwritten. Events
use their own ``updated_at``. Safe to re-run, and next to the live consumer.

    python manage.py backfill_search [--kinds people,pages,groups,posts,gatherings,listings]
"""

from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError

KINDS = ["people", "pages", "groups", "posts", "gatherings", "listings"]
MARGIN = timedelta(seconds=60)


class Command(BaseCommand):
    help = "Index existing people, pages, groups, posts, events and listings (idempotent)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--kinds", default=",".join(KINDS))
        parser.add_argument("--batch-size", type=int, default=200)

    def handle(self, *args, **options) -> None:
        from searchsvc import clients

        kinds = [k.strip() for k in options["kinds"].split(",") if k.strip()]
        unknown = set(kinds) - set(KINDS)
        if unknown:
            raise CommandError(f"unknown kinds: {', '.join(sorted(unknown))}")
        for kind in kinds:
            after, seen, indexed = None, 0, 0
            while True:
                try:
                    page = clients.export_page(kind, after, options["batch_size"])
                except clients.Unavailable as exc:
                    raise CommandError(f"{exc}; resume with --kinds {kind}") from exc
                for item in page["items"]:
                    seen += 1
                    indexed += apply_item(kind, item, page["as_of"])
                after = page.get("next")
                if not after:
                    break
            self.stdout.write(self.style.SUCCESS(f"{kind}: {seen} read, {indexed} applied"))


def apply_item(kind: str, item: dict, as_of: str) -> int:
    from searchsvc import indexing, posts
    from tara_events.envelope import EventEnvelope

    version = (indexing.when(as_of) or indexing.when("1970-01-01T00:00:00Z")) - MARGIN
    item_id, payload = str(item["id"]), item["payload"]
    if kind == "people":
        return int(indexing.apply("user", item_id, version, indexing.person_doc(item_id, payload)))
    if kind == "pages":
        return int(indexing.apply("page", item_id, version, indexing.page_doc(payload)))
    if kind == "groups":
        return int(indexing.apply("group", item_id, version, indexing.group_doc(payload)))
    if kind == "listings":
        return int(indexing.apply("listing", item_id, version, indexing.listing_doc(payload)))
    if kind == "gatherings":
        at = indexing.when(payload.get("updated_at")) or version
        return int(indexing.apply("gathering", item_id, at, indexing.gathering_doc(payload)))
    # posts: the same path as post.updated, so hashtags follow.
    posts.apply_post_event(
        EventEnvelope(
            event_type="post.updated",
            subject_id=item_id,
            producer="search-backfill",
            occurred_at=version.isoformat(),
            payload={"post_id": item_id, **payload},
        )
    )
    return 1
