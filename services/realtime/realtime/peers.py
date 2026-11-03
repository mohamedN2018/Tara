"""Who may see an account's presence: its DM peers (Chat) and friends (Graph).

The relation is symmetric, so "may A see B" is "B in audience(A)". Verdicts
are cached briefly (``PRESENCE_AUDIENCE_TTL``) and dropped early when a block
or friendship change arrives on the bus. A failed lookup contributes nobody
and is not cached (fail closed, retried next time).
"""

from __future__ import annotations

from django.conf import settings
from django.core.cache import cache

from . import chat_client, graph_client

MAX_AUDIENCE = 5000


def _key(account_id: str) -> str:
    return f"presence:aud:{account_id}"


def audience(account_id: str) -> set[str]:
    account_id = str(account_id)
    cached = cache.get(_key(account_id))
    if cached is not None:
        return set(cached)
    dm_peers = chat_client.presence_peers(account_id)
    friends = graph_client.friends(account_id)
    result = (set(dm_peers or []) | set(friends or [])) - {account_id}
    result = set(sorted(result)[:MAX_AUDIENCE])
    if dm_peers is not None and friends is not None:
        cache.set(_key(account_id), sorted(result), settings.PRESENCE_AUDIENCE_TTL)
    return result


def invalidate(*account_ids: str) -> None:
    cache.delete_many([_key(str(a)) for a in account_ids if a])
