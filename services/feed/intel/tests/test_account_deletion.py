"""WP 2.10: no ``intel_*`` row, ``redis-hot`` key or pool member survives account deletion."""

import uuid
from datetime import timedelta

import pytest
from django.apps import apps
from django.core.cache import caches
from django.db import connection
from django.utils import timezone
from feed.models import FeedItem

import intel.handlers  # noqa: F401
from intel import deletion, hot
from intel.models import SignalBatch, SyntheticAccount
from intel.signals import store

from .helpers import acct, deliver, event

pytestmark = pytest.mark.django_db


def _signal(account, item_type="post", item_id=None, **kw):
    now = timezone.now()
    store.insert_row(
        store.SignalRow(
            account_id=account,
            event_type=kw.pop("event_type", "post_open"),
            item_type=item_type,
            item_id=item_id or uuid.uuid4(),
            source="client",
            data_origin="real",
            occurred_at=now,
            received_at=kw.pop("received_at", now),
            **kw,
        )
    )


def _engagement(account, item_id=None):
    now = timezone.now()
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO intel_user_item_engagement (account_id, item_id, item_type, first_at, "
            "last_at, data_origin) VALUES (%s, %s, 'post', %s, %s, 'real')",
            [account, item_id or uuid.uuid4(), now, now],
        )


def _count(table, column, value) -> int:
    with connection.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {table} WHERE {column} = %s", [value])  # noqa: S608
        return cur.fetchone()[0]


def _count_where(table, where, account) -> int:
    with connection.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {table} WHERE {where}", {"a": account})  # noqa: S608
        return cur.fetchone()[0]


def _populate(account):
    _signal(account)
    _signal(account, received_at=timezone.now() - timedelta(days=3))  # an older partition
    _engagement(account)
    SignalBatch.objects.create(
        account_id=account, batch_id=uuid.uuid4(), received_at=timezone.now()
    )
    SyntheticAccount.objects.create(account_id=account, label="test-deletion")


def test_every_intel_table_is_covered():
    covered = (
        {t for t, _ in deletion.ACCOUNT_TABLES}
        | {t for t, _ in deletion.ACCOUNT_SCRUBS}
        | set(deletion.NOT_ACCOUNT_KEYED)
    )
    tables = {m._meta.db_table for m in apps.get_app_config("intel").get_models()}
    assert tables <= covered, tables - covered


def test_account_deleted_erases_every_intel_row_of_the_account():
    gone, kept = acct(), acct()
    _populate(gone)
    _populate(kept)
    # Another viewer's visit to the deleted account's profile names it too.
    _signal(kept, item_type="profile", item_id=gone, event_type="profile_visit")
    _engagement(kept, item_id=gone)

    deliver(event("account.deleted", {"account_id": gone}), times=2)

    for table, where in deletion.ACCOUNT_TABLES:
        assert _count_where(table, where, gone) == 0, table
    assert _count("intel_signal_event", "item_id", gone) == 0
    assert _count("intel_user_item_engagement", "item_id", gone) == 0
    # The other account keeps its own rows.
    assert _count("intel_signal_event", "account_id", kept) == 2
    assert _count("intel_signal_batch", "account_id", kept) == 1
    assert _count("intel_synthetic_account", "account_id", kept) == 1


def test_redis_session_and_profile_keys_are_gone():
    gone, kept = acct(), acct()
    cache = caches["hot"]
    for account in (gone, kept):
        for key in hot.session_keys(account) + [hot.profile_key(account)]:
            cache.set(key, b"x", 600)
    deletion.erase_account(gone)
    for key in hot.session_keys(gone) + [hot.profile_key(gone)]:
        assert cache.get(key) is None, key
    assert cache.get(hot.profile_key(kept)) == b"x"
    assert cache.get(f"feed:rank:{kept}") == b"x"


def test_pool_members_are_removed_at_once(redis_hot):
    gone, other = acct(), acct()
    mine = [str(uuid.uuid4()) for _ in range(3)]
    theirs = str(uuid.uuid4())
    for post_id in mine:
        FeedItem.objects.create(
            recipient_id=other,
            post_id=post_id,
            author_id=gone,
            reason="follow",
            snapshot={},
            post_created_at=timezone.now(),
        )
    client = hot.raw_client()
    keys = [
        redis_hot.make_key(hot.pool_key("home", "ar", "_trending")),
        redis_hot.make_key(hot.pool_key("reels", "en", "food")),
    ]
    for key in keys:
        client.zadd(key, {mine[0]: 3.0, mine[1]: 2.0, theirs: 1.0})
    redis_hot.set(hot.profile_key(gone), b"x", 600)

    counts = deletion.erase_account(gone)

    assert counts["pool_members"] == 4
    for key in keys:
        assert client.zrange(key, 0, -1) == [theirs.encode()]
    assert redis_hot.get(hot.profile_key(gone)) is None


def test_raw_keys_are_gone_as_stored(redis_hot):
    """WP 4b.0: feed:exp, feed:sess, feed:si, feed:head:* and intel:age, written with
    the raw client under make_key, are deleted with the account (exists == 0)."""
    gone, kept = acct(), acct()
    client = hot.raw_client()
    names = {a: hot.raw_keys(a) for a in (gone, kept)}
    assert {n.split(":")[1] for n in names[gone] if n.startswith("feed:")} == {
        "exp",
        "sess",
        "si",
        "head",
    }
    assert hot.head_key("home", gone) in names[gone]
    for keys in names.values():
        for name in keys:
            client.set(redis_hot.make_key(name), b"x" * 16, ex=600)
    deletion.erase_account(gone)
    for name in names[gone]:
        assert client.exists(redis_hot.make_key(name)) == 0, name
    for name in names[kept]:
        assert client.exists(redis_hot.make_key(name)) == 1, name


def test_home_pool_members_of_the_account_are_removed(redis_hot):
    """WP 4b.6: the popular / fresh pools are under the pool_key shape, so deletion's
    ZREM reaches them at once."""
    from intel import discovery

    gone = acct()
    post_id = str(uuid.uuid4())
    FeedItem.objects.create(
        recipient_id=acct(),
        post_id=post_id,
        author_id=gone,
        reason="follow",
        snapshot={},
        post_created_at=timezone.now(),
    )
    client = hot.raw_client()
    keys = [
        redis_hot.make_key(hot.pool_key("home", lang, bucket))
        for lang in ("ar", "en")
        for bucket in discovery.BUCKETS
    ]
    for key in keys:
        client.zadd(key, {post_id: 1.0, str(uuid.uuid4()): 0.5})
    client.set(redis_hot.make_key(discovery.STAMP), b"1")
    counts = deletion.erase_account(gone)
    assert counts["pool_members"] == len(keys)
    for key in keys:
        assert client.zscore(key, post_id) is None
