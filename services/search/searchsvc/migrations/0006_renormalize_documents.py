"""Fill the search v2 columns of documents indexed before 1.15.

``title_norm``/``body_norm`` are the Arabic-normalised copies the trigram
indexes are built on (0007). Each batch commits on its own; re-running is safe.
Fields the old events never carried (a post's type and media, a listing's price)
are filled by ``manage.py backfill_search`` from the owners' export endpoints.
"""

from django.db import migrations

from tara_common.text import normalize_ar

_BATCH = 500


def _norm(value, limit):
    return normalize_ar(value).lstrip("#").strip()[:limit]


def forwards(apps, schema_editor):
    SearchDocument = apps.get_model("searchsvc", "SearchDocument")
    last = 0
    while True:
        batch = list(
            SearchDocument.objects.filter(id__gt=last, title_norm="", body_norm="")
            .order_by("id")
            .only("id", "doc_type", "title", "body", "extra")[:_BATCH]
        )
        if not batch:
            return
        for doc in batch:
            doc.title_norm = _norm(doc.title, 400)
            doc.body_norm = _norm(doc.body, 2000)
            if doc.doc_type == "hashtag":
                doc.extra = {**(doc.extra or {}), "tag": doc.doc_id}
        SearchDocument.objects.bulk_update(batch, ["title_norm", "body_norm", "extra"])
        last = batch[-1].id


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("searchsvc", "0005_search_v2"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
