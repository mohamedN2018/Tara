"""``topics`` on served items (R4 API contract: every FeedItem of ``GET /feed/`` and of
the peek gains ``topics: [{slug, label_ar, label_en}]``, at most 3, best first).

A ranked page passes the topics its eligibility read already loaded (``known``, no
query); any other page reads them in one statement. Labels come from the in-process
taxonomy cache. Topics describe the content, never the viewer.
"""

from __future__ import annotations

from . import classify


def attach(
    items: list[dict], known: dict | None = None, labels: dict | None = None
) -> dict[str, list[tuple[int, float]]]:
    """Set ``item["topics"]`` in place; returns ``{post_id: [(topic_id, conf)]}``.
    ``known`` and ``labels`` (a ranked page): from its eligibility read; else one
    statement reads the topics with their labels."""
    ids = [str(i.get("post_id")) for i in items if i.get("post_id")]
    if known is None:
        found, labels = classify.topics_with_labels(ids) if ids else ({}, {})
    else:
        found = {p: known.get(p, []) for p in ids}
    labels = labels or {}
    for item in items:
        pairs = found.get(str(item.get("post_id")), [])[:3]
        missing = [t for t, _ in pairs if t not in labels]
        if missing:  # not expected: the topic rows carry their labels
            labels.update({t["id"]: t for t in _labelled(missing)})
        item["topics"] = [
            {k: labels[t][k] for k in ("slug", "label_ar", "label_en")}
            for t, _ in pairs
            if t in labels
        ]
    return found


def _labelled(topic_ids):
    topics = classify.load_aliases().topics
    return [topics[t] for t in topic_ids if t in topics]


def primary(found: dict) -> dict[str, int]:
    """``{post_id: primary topic id}`` for the serve tokens (07 WP 4b.16)."""
    return {p: pairs[0][0] for p, pairs in found.items() if pairs}
