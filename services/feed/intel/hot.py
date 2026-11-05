"""Keys in ``redis-hot`` (the ``hot`` cache, prefix ``feed``) owned by intel (03 section 2.8).

Session and profile keys are plain cache keys. Pools are sorted sets written with
the raw client under ``cache.make_key("intel:pool:...")``, so the deletion path and
the pool builder (WP 9.1) agree on one key shape.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.cache import caches

logger = logging.getLogger("tara.intel.hot")

# Every ranked surface's session key: feed:rank:{surface}:{viewer} (WP 4.10). The
# pre-v2 key feed:rank:{viewer} (feed/ranking.py) is listed too.
RANK_SURFACES = ("home", "reels", "video", "groups", "discover")


def hot():
    return caches[settings.FEED_HOT_CACHE]


def session_keys(account_id) -> list[str]:
    return [f"feed:rank:{account_id}"] + [f"feed:rank:{s}:{account_id}" for s in RANK_SURFACES]


def profile_key(account_id) -> str:
    return f"intel:prof:{account_id}"


def pool_key(surface: str, lang: str, bucket: str) -> str:
    return f"intel:pool:{surface}:{lang}:{bucket}"


def raw_client():
    """The redis-py client behind the hot cache, or None (local memory cache in tests)."""
    backend = hot()
    inner = getattr(backend, "_cache", None)
    if inner is None or not hasattr(inner, "get_client"):
        return None
    return inner.get_client(write=True)


def pool_keys() -> list[str]:
    """Every pool key, as stored (with the cache prefix and version)."""
    client = raw_client()
    if client is None:
        return []
    pattern = hot().make_key("intel:pool:*")
    return [k.decode() if isinstance(k, bytes) else k for k in client.scan_iter(match=pattern)]


def forget_account(account_id, post_ids) -> dict:
    """Drop the account's sessions and profile, and its posts from every pool now."""
    out = {"keys": 0, "pool_members": 0}
    backend = hot()
    keys = session_keys(account_id) + [profile_key(account_id)]
    backend.delete_many(keys)
    out["keys"] = len(keys)
    client = raw_client()
    if client is not None and post_ids:
        for key in pool_keys():
            out["pool_members"] += int(client.zrem(key, *post_ids) or 0)
    return out
