"""Backfill the v2 columns of rows written before 0003, in small batches.

Old rows got ``last_event_at`` = the migration time from the column default; it
becomes their ``created_at`` so the list keeps its order. ``category`` comes
from the kind registry and ``actor_count`` from ``actor_id``. Old rows keep an
empty ``aggregate_key``: they never merge, so the unique index in 0005 cannot
conflict with them. Non-atomic, so each batch commits and locks stay short.
"""

from django.db import migrations
from django.db.models import F

BATCH = 2000

# Frozen copy of the registry's kind -> category map at the time of writing.
CATEGORIES = {
    "post.reaction": "social",
    "post.comment": "social",
    "comment.reply": "social",
    "mention": "social",
    "post.share": "social",
    "friend.request": "connections",
    "friend.accepted": "connections",
    "follow": "connections",
    "message": "messages",
    "listing.status": "marketplace",
}


def backfill(apps, schema_editor):
    Notification = apps.get_model("notifications", "Notification")
    last_id = None
    while True:
        qs = Notification.objects.order_by("id")
        if last_id is not None:
            qs = qs.filter(id__gt=last_id)
        ids = list(qs.filter(category="").values_list("id", flat=True)[:BATCH])
        if not ids:
            return
        batch = Notification.objects.filter(id__in=ids)
        batch.update(last_event_at=F("created_at"))
        batch.filter(actor_id__isnull=False).update(actor_count=1)
        for kind, category in CATEGORIES.items():
            batch.filter(kind=kind).update(category=category)
        batch.filter(category="").update(category="social")
        last_id = ids[-1]


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("notifications", "0003_notification_v2_fields"),
    ]

    operations = [migrations.RunPython(backfill, migrations.RunPython.noop, elidable=True)]
