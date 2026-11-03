"""Existing rows: `deleted_at` used to mean "removed by moderation" (the only
writer was the moderation handler). Move it to `moderation_removed_at`, so
`deleted_at` now means "deleted for everyone by the sender". Also fill
`body_norm` for search."""

from django.db import migrations
from django.db.models import F


def forwards(apps, schema_editor):
    from chat.text import normalize

    Message = apps.get_model("chat", "Message")
    Message.objects.filter(deleted_at__isnull=False, deleted_by__isnull=True).update(
        moderation_removed_at=F("deleted_at"), deleted_at=None
    )
    batch = []
    for message in Message.objects.exclude(body="").only("id", "body").iterator(chunk_size=1000):
        message.body_norm = normalize(message.body)
        batch.append(message)
        if len(batch) >= 1000:
            Message.objects.bulk_update(batch, ["body_norm"])
            batch = []
    if batch:
        Message.objects.bulk_update(batch, ["body_norm"])


def backwards(apps, schema_editor):
    Message = apps.get_model("chat", "Message")
    Message.objects.filter(moderation_removed_at__isnull=False).update(
        deleted_at=F("moderation_removed_at"), moderation_removed_at=None
    )


class Migration(migrations.Migration):
    dependencies = [("chat", "0002_messenger_state")]

    operations = [migrations.RunPython(forwards, backwards)]
