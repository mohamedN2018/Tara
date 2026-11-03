"""Data for comments v2 (1.3) and per-type reaction counts (1.4).

1. Flatten old threads: before 1.3 a reply to a reply pointed at that reply.
   Now ``parent`` is always the thread root and ``reply_to`` the comment answered.
2. ``reply_count`` on every root: its live replies.
3. ``PostReactionCount`` rows from the existing reactions.

Reverse is a no-op: the new columns and table are dropped by 0005's reverse, and
the old code reads ``parent`` the same way (it walked up to the root itself).
"""

from django.db import migrations
from django.db.models import Count, F, Q

BATCH = 1000


def forwards(apps, schema_editor):
    Comment = apps.get_model("posts", "Comment")
    PostReaction = apps.get_model("posts", "PostReaction")
    PostReactionCount = apps.get_model("posts", "PostReactionCount")

    # 1. Replies whose parent is itself a reply.
    nested = Comment.objects.filter(parent__parent__isnull=False).values_list(
        "id", "parent_id"
    )
    # Only replies have a parent, so this holds replies only, not every comment.
    parent_of = dict(Comment.objects.filter(parent__isnull=False).values_list("id", "parent_id"))
    for comment_id, parent_id in nested.iterator(chunk_size=BATCH):
        root, guard = parent_id, 0
        while parent_of.get(root) and guard < 100:
            root, guard = parent_of[root], guard + 1
        Comment.objects.filter(id=comment_id).update(parent_id=root, reply_to_id=parent_id)
    # Direct replies to a root answered that root.
    Comment.objects.filter(parent__isnull=False, reply_to__isnull=True).update(
        reply_to_id=F("parent_id")
    )

    # 2. reply_count on roots.
    roots = (
        Comment.objects.filter(parent__isnull=True)
        .annotate(n=Count("replies", filter=Q(replies__deleted_at__isnull=True)))
        .filter(n__gt=0)
        .values_list("id", "n")
    )
    for root_id, n in roots.iterator(chunk_size=BATCH):
        Comment.objects.filter(id=root_id).update(reply_count=n)

    # 3. Per-type reaction counts.
    rows = (
        PostReaction.objects.values("post_id", "type").annotate(n=Count("id")).order_by()
    )
    batch = []
    for row in rows.iterator(chunk_size=BATCH):
        batch.append(PostReactionCount(post_id=row["post_id"], type=row["type"], count=row["n"]))
        if len(batch) >= BATCH:
            PostReactionCount.objects.bulk_create(batch, ignore_conflicts=True)
            batch = []
    if batch:
        PostReactionCount.objects.bulk_create(batch, ignore_conflicts=True)


class Migration(migrations.Migration):
    dependencies = [("posts", "0005_comments_v2_reaction_counts")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
