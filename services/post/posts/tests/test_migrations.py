"""0006 flattens threads written before 1.3 and backfills the new counters."""

import uuid

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE = [("posts", "0004_post_media_media_idx")]
AFTER = [("posts", "0006_backfill_comment_threads_and_reaction_counts")]


def _migrate(target):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(target)
    return executor.loader.project_state(target).apps


@pytest.mark.django_db(transaction=True)
def test_backfill_flattens_nested_replies_and_counts():
    old = _migrate(BEFORE)
    Post = old.get_model("posts", "Post")
    Comment = old.get_model("posts", "Comment")
    PostReaction = old.get_model("posts", "PostReaction")
    author = uuid.uuid4()
    post = Post.objects.create(id=uuid.uuid4(), author_id=author, body="p")
    root = Comment.objects.create(id=uuid.uuid4(), post=post, author_id=author, body="root")
    child = Comment.objects.create(
        id=uuid.uuid4(), post=post, author_id=author, parent=root, body="child"
    )
    grandchild = Comment.objects.create(
        id=uuid.uuid4(), post=post, author_id=author, parent=child, body="grandchild"
    )
    for kind in ("love", "love", "like"):
        PostReaction.objects.create(id=uuid.uuid4(), post=post, account_id=uuid.uuid4(), type=kind)

    try:
        new = _migrate(AFTER)
        Comment = new.get_model("posts", "Comment")
        PostReactionCount = new.get_model("posts", "PostReactionCount")

        flat = Comment.objects.get(id=grandchild.id)
        assert flat.parent_id == root.id and flat.reply_to_id == child.id
        direct = Comment.objects.get(id=child.id)
        assert direct.parent_id == root.id and direct.reply_to_id == root.id
        assert Comment.objects.get(id=root.id).reply_count == 2
        counts = dict(
            PostReactionCount.objects.filter(post_id=post.id).values_list("type", "count")
        )
        assert counts == {"love": 2, "like": 1}
    finally:
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes("posts"))
