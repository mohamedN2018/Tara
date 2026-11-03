"""Who may see an account's presence: its DM peers (Chat) and friends (Graph).

The relation is symmetric, so "may A see B" is "B in audience(A)". Verdicts
are cached briefly (``PRESENCE_AUDIENCE_TTL``) and dropped early when a block
or friendship change arrives on the bus. A failed lookup contributes nobody
and is not cached (fail closed, retried next time).

Chat learns about a block from the same bus, possibly after Realtime does, so
its answer can still list the blocked account. A block seen here is therefore
remembered (``PRESENCE_BLOCK_MEMORY_TTL``) and always subtracted.
"""

from __future__ import annotations

from django.conf import settings
from django.core.cache import cache

from . import chat_client, graph_client

MAX_AUDIENCE = 5000


def _key(account_id: str) -> str:
    return f"presence:aud:{account_id}"


def _blocked_key(account_id: str) -> str:
    return f"presence:blocked:{account_id}"


def audience(account_id: str) -> set[str]:
    account_id = str(account_id)
    found = cache.get_many([_key(account_id), _blocked_key(account_id)])
    blocked = set(found.get(_blocked_key(account_id)) or [])
    cached = found.get(_key(account_id))
    if cached is not None:
        return set(cached) - blocked
    dm_peers = chat_client.presence_peers(account_id)
    friends = graph_client.friends(account_id)
    result = (set(dm_peers or []) | set(friends or [])) - {account_id} - blocked
    result = set(sorted(result)[:MAX_AUDIENCE])
    if dm_peers is not None and friends is not None:
        cache.set(_key(account_id), sorted(result), settings.PRESENCE_AUDIENCE_TTL)
    return result


def invalidate(*account_ids: str) -> None:
    cache.delete_many([_key(str(a)) for a in account_ids if a])


def _update_blocked(account_id: str, other: str, add: bool) -> None:
    key = _blocked_key(account_id)
    current = set(cache.get(key) or [])
    current = current | {other} if add else current - {other}
    if current:
        cache.set(key, sorted(current), settings.PRESENCE_BLOCK_MEMORY_TTL)
    else:
        cache.delete(key)


def remember_block(a: str, b: str) -> None:
    for viewer, target in ((str(a), str(b)), (str(b), str(a))):
        _update_blocked(viewer, target, add=True)
    invalidate(a, b)


def forget_block(a: str, b: str) -> None:
    for viewer, target in ((str(a), str(b)), (str(b), str(a))):
        _update_blocked(viewer, target, add=False)
    invalidate(a, b)
