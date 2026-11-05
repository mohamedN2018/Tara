"""The only imports ``intel`` makes from the ``feed`` app (02 section 7).

Keeping them in one module makes a later split of ``intel`` into its own service
mechanical: replace these functions, not every call site.
"""

from __future__ import annotations


def post_ids_by_author(author_id) -> list[str]:
    """Every post id of ``author_id`` that feed knows (its fan-out rows)."""
    from feed.models import FeedItem

    return [
        str(p)
        for p in FeedItem.objects.filter(author_id=author_id)
        .values_list("post_id", flat=True)
        .distinct()
    ]


def visible_feed_rows(viewer_id) -> list[tuple]:
    """``[(post_id, author_id, snapshot type, post_created_at)]`` of the viewer's own
    feed rows minus what they hid, snoozed or muted: content they were authorized
    to receive (fan-out follows post's visibility rules)."""
    from feed.ranking import visible_items

    return [
        (
            row["post_id"],
            row["author_id"],
            (row["snapshot"] or {}).get("type"),
            row["post_created_at"],
        )
        for row in visible_items(viewer_id).values(
            "post_id", "author_id", "snapshot", "post_created_at"
        )
    ]
