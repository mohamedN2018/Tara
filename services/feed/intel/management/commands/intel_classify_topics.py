"""Backfill post topics (04 WP 6.2) from post's export, additively.

    manage.py intel_classify_topics [--rate 20] [--limit 200] [--json]

Reads ``/internal/v1/intel/export/posts/`` (the same export as
``intel_backfill_content``: ids, enums and the 280-character excerpt), classifies
every post feed already has an ``intel_content_ref`` row for and replaces its
``intel_content_topic`` rows. The excerpt is used in memory only. Shared posts are
classified once more at the end, so they inherit their original's topics whatever
the export order. Reports the coverage: live posts with at least one topic.
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand
from django.db import connection

from intel import backfill
from intel.topics import classify


def coverage() -> dict:
    with connection.cursor() as cur:
        cur.execute(
            "SELECT count(*), count(*) FILTER (WHERE EXISTS ("
            "SELECT 1 FROM intel_content_topic t WHERE t.post_id = c.post_id)), "
            "count(*) FILTER (WHERE cardinality(c.hashtags) > 0) "
            "FROM intel_content_ref c WHERE c.state = 'live'"
        )
        total, covered, tagged = cur.fetchone()
    return {
        "live_posts": total,
        "with_topic": covered,
        "coverage": round(covered / total, 4) if total else None,
        "with_hashtag": tagged,
    }


class Command(BaseCommand):
    help = "Classify every known post into topics from post's export (WP 6.2)."

    def add_arguments(self, parser):
        parser.add_argument("--rate", type=float, default=20.0)
        parser.add_argument("--limit", type=int, default=200)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **opts):
        classify.clear_cache()
        with connection.cursor() as cur:
            cur.execute("SELECT post_id::text, shared_post_id IS NOT NULL FROM intel_content_ref")
            known = dict(cur.fetchall())
        seen = classified = 0
        shared: list[tuple[str, str | None]] = []
        src = backfill.source("posts")
        for page in backfill.pages(src, limit=opts["limit"], rate=opts["rate"]):
            for item in page.items:
                seen += 1
                post_id = str(item.get("id"))
                if post_id not in known:
                    continue
                excerpt = (item.get("payload") or {}).get("excerpt") or ""
                classify.classify_post(post_id, excerpt)
                classified += 1
                if known[post_id]:
                    shared.append((post_id, excerpt))
        for post_id, excerpt in shared:
            classify.classify_post(post_id, excerpt)
        out = {"exported": seen, "classified": classified, "shared_second_pass": len(shared)}
        out.update(coverage())
        self.stdout.write(json.dumps(out) if opts["json"] else str(out))
