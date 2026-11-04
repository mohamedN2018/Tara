"""Make public hashtag links and documents match public posts (Postgres and OpenSearch).

Migration 0004 builds the links on deploy, but the old ``search-consumer`` keeps
running on old code until it is recreated, and it deletes or re-indexes post
documents without touching links. Run this once AFTER ``search-consumer`` runs the
new code: it rebuilds the links, drops hashtags no public post backs (OpenSearch
too, when enabled) and restores missing ones. Safe to re-run, also next to the
live consumer.
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Rebuild public hashtag links; drop hashtags no public post backs; restore missing"
        " ones; park the posts of hidden pages."
    )

    def handle(self, *args, **options) -> None:
        from searchsvc.posts import reconcile_hashtags

        r = reconcile_hashtags()
        self.stdout.write(
            self.style.SUCCESS(
                f"posts purged: {r['posts_purged']}, "
                f"links added: {r['links_added']}, links removed: {r['links_removed']}, "
                f"hashtags purged: {r['hashtags_purged']}, "
                f"hashtags restored: {r['hashtags_restored']}, "
                f"page posts parked: {r['page_posts_parked']}, "
                f"page posts restored: {r['page_posts_restored']}"
            )
        )
