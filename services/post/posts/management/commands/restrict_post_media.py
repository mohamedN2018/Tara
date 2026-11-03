"""Restrict the media of existing non-public posts to their audience.

New and edited posts restrict their media as they are written. Posts written
before that have public media that anyone with a media id can fetch, so run
this once after the release that adds restricted media (media and post both
deployed). It is idempotent, and safe to re-run or interrupt: restricting only
ever narrows who can see a media, and post's visibility check still lets the
post's own audience in. Deleted posts are included, so their media become
owner-only.

    python manage.py restrict_post_media [--dry-run] [--batch 200]

Run media's ``sanitize_existing_images`` in the same release: it removes
EXIF/GPS from images that were already ready before images were cleaned.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import Exists, OuterRef

from tara_common.exceptions import TaraAPIError

from ... import media_client
from ...models import Audience, Post, PostMedia


class Command(BaseCommand):
    help = "Restrict media of existing non-public posts (one-off, idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--batch", type=int, default=200)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        size, dry_run = options["batch"], options["dry_run"]
        posts = (
            Post.objects.exclude(audience=Audience.PUBLIC)
            .filter(Exists(PostMedia.objects.filter(post=OuterRef("pk"))))
            .order_by("id")
        )
        done = failed = skipped = 0
        last_id = None
        while True:
            page = posts.filter(id__gt=last_id) if last_id else posts
            batch = list(page.prefetch_related("media")[:size])
            if not batch:
                break
            for post in batch:
                ids = [str(m.media_id) for m in post.media.all()]
                if dry_run:
                    done += 1
                    continue
                try:
                    skipped += len(
                        media_client.bind(str(post.author_id), str(post.id), ids, restricted=True)
                    )
                    done += 1
                except TaraAPIError:
                    failed += 1
                    self.stderr.write(f"post {post.id}: media unavailable, re-run later")
            last_id = batch[-1].id
        verb = "would restrict" if dry_run else "restricted"
        self.stdout.write(
            f"{verb} media of {done} posts; {failed} failed; "
            f"{skipped} media skipped (deleted or not the author's)"
        )
