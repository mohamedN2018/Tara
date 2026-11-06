"""WP 4c.8-B3 (08 section 7.3): the keyset index is built ``CONCURRENTLY``.

``feed_item`` is the service's largest table: the migration runs outside a
transaction (``atomic = False``) and uses the concurrent operations, so writes are
never locked out while the index builds; the old index goes the same way."""

import importlib

import pytest
from django.contrib.postgres.operations import AddIndexConcurrently, RemoveIndexConcurrently
from django.db import connection

from feed.models import FeedItem

MIGRATION = importlib.import_module("feed.migrations.0012_feed_recipient_keyset_idx").Migration


def test_the_migration_is_not_atomic_and_both_steps_are_concurrent():
    assert MIGRATION.atomic is False
    add, remove = MIGRATION.operations
    assert type(add) is AddIndexConcurrently
    assert type(remove) is RemoveIndexConcurrently
    assert add.index.name == "feed_recipient_ts_idx"
    assert add.index.fields == ["recipient_id", "-post_created_at", "-id"]
    assert remove.name == "feed_recipient_idx"


def test_the_model_declares_the_new_index_only():
    names = {i.name: i.fields for i in FeedItem._meta.indexes}
    assert names["feed_recipient_ts_idx"] == ["recipient_id", "-post_created_at", "-id"]
    assert "feed_recipient_idx" not in names


@pytest.mark.django_db
def test_the_database_has_the_new_index_and_not_the_old_one():
    with connection.cursor() as cur:
        cur.execute("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'feed_item'")
        found = dict(cur.fetchall())
    assert "feed_recipient_idx" not in found
    assert "(recipient_id, post_created_at DESC, id DESC)" in found["feed_recipient_ts_idx"]


COMMENT_MIGRATION = importlib.import_module("feed.migrations.0013_comment_state_indexes").Migration


def test_the_comment_state_indexes_are_built_concurrently():
    """R3 verifier: the first page's commenter reads no longer scan ``comment_state``."""
    assert COMMENT_MIGRATION.atomic is False
    assert all(type(op) is AddIndexConcurrently for op in COMMENT_MIGRATION.operations)
    assert {op.index.name: op.index.fields for op in COMMENT_MIGRATION.operations} == {
        "comment_state_post_idx": ["post_id", "occurred_at"],
        "comment_state_author_idx": ["author_id", "occurred_at"],
        "comment_state_post_author_idx": ["post_author_id", "occurred_at"],
    }


@pytest.mark.django_db
def test_the_database_has_the_comment_state_indexes():
    with connection.cursor() as cur:
        cur.execute("SELECT indexname FROM pg_indexes WHERE tablename = 'comment_state'")
        found = {r[0] for r in cur.fetchall()}
    assert {
        "comment_state_post_idx",
        "comment_state_author_idx",
        "comment_state_post_author_idx",
    } <= found
