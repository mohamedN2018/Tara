"""Trigram index for message search. Built concurrently (no write lock), so
this migration is non-atomic and holds nothing else."""

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.operations import AddIndexConcurrently, TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("chat", "0003_split_moderation_removal")]

    operations = [
        TrigramExtension(),
        AddIndexConcurrently(
            model_name="message",
            index=GinIndex(
                fields=["body_norm"], opclasses=["gin_trgm_ops"], name="message_body_trgm"
            ),
        ),
    ]
