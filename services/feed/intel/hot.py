"""Keys in ``redis-hot`` (the ``hot`` cache, prefix ``feed``) owned by intel (03 section 2.8).

Session and profile keys are plain cache keys. Pools are sorted sets written with
the raw client under ``cache.make_key("intel:pool:...")``, so the deletion path and
the pool builder (WP 4b.6, later 9.1) agree on one key shape.

Raw keys (07 WP 4b.0): values written with the raw client, not pickled by the cache,
always named through ``hot().make_key(name)``, so the cache's own ``delete_many``
removes them too. Registered here, all deleted by ``forget_account``:

- ``feed:exp:{viewer}``: exposure ledger (R3, 06 section 5.2);
- ``feed:sess:{viewer}``: visit state (R3, 06 section 4.3);
- ``feed:si:{viewer}``: session interests (R3, 06 section 4.4);
- ``feed:head:{surface}:{viewer}``: the ids of the last first page (WP 4b.11);
- ``intel:age:{account}``: the author age class memo (WP 4b.14).

``redis-hot`` runs ``noeviction``: a full instance refuses writes. Every writer here
is fail-soft: the refusal is counted in ``intel_hot_write_failed_total{key}`` and the
request goes on without that state.
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


def exposure_key(viewer_id) -> str:
    return f"feed:exp:{viewer_id}"


def visit_key(viewer_id) -> str:
    return f"feed:sess:{viewer_id}"


def session_interest_key(viewer_id) -> str:
    return f"feed:si:{viewer_id}"


def head_key(surface: str, viewer_id) -> str:
    if surface not in RANK_SURFACES:
        raise KeyError(f"no first-page head for surface {surface!r}")
    return f"feed:head:{surface}:{viewer_id}"


def age_key(account_id) -> str:
    return f"intel:age:{account_id}"


def raw_keys(account_id) -> list[str]:
    """Every raw key of one account (names, before ``make_key``)."""
    return [
        exposure_key(account_id),
        visit_key(account_id),
        session_interest_key(account_id),
        *[head_key(s, account_id) for s in RANK_SURFACES],
        age_key(account_id),
    ]


def raw_client():
    """The redis-py client behind the hot cache, or None (local memory cache in tests)."""
    backend = hot()
    inner = getattr(backend, "_cache", None)
    if inner is None or not hasattr(inner, "get_client"):
        return None
    return inner.get_client(write=True)


def raw_set(name: str, value: bytes, ttl_s: int, label: str) -> bool:
    """SET ``name`` (stored as ``make_key(name)``) with a TTL. False, and counted,
    when redis-hot refuses (``noeviction`` OOM) or is down; never raises."""
    from . import metrics

    client = raw_client()
    if client is None:
        return False
    try:
        client.set(hot().make_key(name), value, ex=max(int(ttl_s), 1))
        return True
    except Exception:  # noqa: BLE001 - a full or down redis-hot only costs this state
        metrics.hot_write_failed(label)
        logger.warning("redis-hot refused a %s write", label, exc_info=True)
        return False


def raw_get(name: str) -> bytes | None:
    client = raw_client()
    if client is None:
        return None
    try:
        return client.get(hot().make_key(name))
    except Exception:  # noqa: BLE001
        logger.warning("redis-hot unreadable", exc_info=True)
        return None


def used_ratio() -> float | None:
    """``used_memory / maxmemory`` of redis-hot, or None (no limit, unreachable)."""
    client = raw_client()
    if client is None:
        return None
    try:
        info = client.info("memory")
    except Exception:  # noqa: BLE001 - a scrape never fails on redis-hot
        return None
    limit = int(info.get("maxmemory") or 0)
    if limit <= 0:
        return None
    return int(info.get("used_memory") or 0) / limit


def pool_keys() -> list[str]:
    """Every pool key, as stored (with the cache prefix and version)."""
    client = raw_client()
    if client is None:
        return []
    pattern = hot().make_key("intel:pool:*")
    return [k.decode() if isinstance(k, bytes) else k for k in client.scan_iter(match=pattern)]


def forget_account(account_id, post_ids) -> dict:
    """Drop the account's sessions, profile and raw keys, and its posts from every
    pool now."""
    out = {"keys": 0, "pool_members": 0}
    backend = hot()
    keys = session_keys(account_id) + [profile_key(account_id)] + raw_keys(account_id)
    backend.delete_many(keys)
    out["keys"] = len(keys)
    client = raw_client()
    if client is not None and post_ids:
        for key in pool_keys():
            out["pool_members"] += int(client.zrem(key, *post_ids) or 0)
    return out
