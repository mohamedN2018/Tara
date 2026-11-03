"""Data fix for milestone 1.1: hashtag documents only from public posts.

Before 0003 every post's hashtags were indexed, whatever its audience, and never
removed. Post documents, however, only ever held public posts, so their excerpts
are the one trustworthy source: rebuild the public links from them, then delete
every hashtag document no public post backs. Tags that only appeared after the
280-character excerpt are dropped too (fail closed); the next public post using
them indexes them again.

Frozen copy of the logic in `searchsvc.posts` on purpose. Not atomic, so each
batch commits on its own; re-running is safe. The old `search-consumer` keeps
running while this migrates and does not maintain links, so run
`manage.py reconcile_hashtags` once after `search-consumer` runs the new code:
it rebuilds these links from the post documents and clears OpenSearch.
"""

import re

from django.db import migrations

_HASHTAG_RE = re.compile(r"(?<![\w/&#])#(\w{1,80})")
_EXCERPT_LIMIT = 280
_BATCH = 1000


def _tags(excerpt):
    excerpt = excerpt or ""
    truncated = len(excerpt) >= _EXCERPT_LIMIT
    return {
        m.group(1).lower()
        for m in _HASHTAG_RE.finditer(excerpt)
        if not (truncated and m.end() == len(excerpt))
    }


def forwards(apps, schema_editor):
    SearchDocument = apps.get_model("searchsvc", "SearchDocument")
    Link = apps.get_model("searchsvc", "PublicPostHashtag")

    batch = []
    posts = SearchDocument.objects.filter(doc_type="post").only("doc_id", "body", "owner_id")
    for doc in posts.iterator(chunk_size=500):
        batch += [Link(post_id=doc.doc_id, tag=t, author_id=doc.owner_id) for t in _tags(doc.body)]
        if len(batch) >= _BATCH:
            Link.objects.bulk_create(batch, ignore_conflicts=True)
            batch = []
    if batch:
        Link.objects.bulk_create(batch, ignore_conflicts=True)

    SearchDocument.objects.filter(doc_type="hashtag").exclude(
        doc_id__in=Link.objects.values("tag")
    ).delete()


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("searchsvc", "0003_public_hashtags"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
