"""Multi-tab presence (ported from QTech ``core/realtime.py``, with its fixes).

One self-expiring sorted set per account, ``presence:sock:<account>``: member =
socket channel name, score = that socket's last heartbeat (epoch seconds).

- An account is online while any socket heartbeated within ``PRESENCE_TTL``
  (~70 s; clients ping every 30 s). Closing one tab removes only its own
  socket, so the user stays online until the LAST tab closes.
- A crashed gateway leaves no counter to drift (QTech's ``HINCRBY`` hash did):
  stale sockets age out by score, and the whole key expires on its own
  (``PRESENCE_KEY_TTL``).
- ``presence:last_seen:<account>`` is written when the last socket goes. For a
  crash it falls back to the newest heartbeat still in the set.

Transitions (first socket in, last socket out) are what the consumer
announces, and only to authorised peers (``peers.audience``); nothing is
broadcast globally.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime

from django.conf import settings

LAST_SEEN_TTL = 30 * 24 * 3600


def _sock_key(account_id: str) -> str:
    return f"presence:sock:{account_id}"


def _seen_key(account_id: str) -> str:
    return f"presence:last_seen:{account_id}"


class RedisPresence:
    def __init__(self, url: str) -> None:
        import redis

        self.redis = redis.Redis.from_url(url, socket_timeout=2, socket_connect_timeout=2)

    def touch(self, account_id: str, channel: str, now: float) -> bool:
        """Heartbeat one socket. True when the account just came online."""
        key = _sock_key(account_id)
        pipe = self.redis.pipeline(transaction=True)
        pipe.zremrangebyscore(key, "-inf", now - settings.PRESENCE_TTL)
        pipe.zcard(key)
        pipe.zadd(key, {channel: now})
        pipe.expire(key, settings.PRESENCE_KEY_TTL)
        _, before, _, _ = pipe.execute()
        return int(before) == 0

    def drop(self, account_id: str, channel: str, now: float) -> bool:
        """Forget one socket. True when it was the account's last one."""
        key = _sock_key(account_id)
        pipe = self.redis.pipeline(transaction=True)
        pipe.zrem(key, channel)
        pipe.zremrangebyscore(key, "-inf", now - settings.PRESENCE_TTL)
        pipe.zcard(key)
        _, _, remaining = pipe.execute()
        if int(remaining) == 0:
            self.redis.set(_seen_key(account_id), str(now), ex=LAST_SEEN_TTL)
            return True
        return False

    def state(self, account_id: str, now: float) -> tuple[bool, float | None]:
        key = _sock_key(account_id)
        pipe = self.redis.pipeline(transaction=False)
        pipe.zcount(key, now - settings.PRESENCE_TTL, "+inf")
        pipe.zrange(key, -1, -1, withscores=True)
        pipe.get(_seen_key(account_id))
        live, newest, seen = pipe.execute()
        if int(live) > 0:
            return True, None
        candidates = [float(seen)] if seen else []
        if newest:
            candidates.append(float(newest[0][1]))
        return False, max(candidates) if candidates else None


class MemoryPresence:
    """Same semantics in-process (tests, and a dev box without Redis)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sockets: dict[str, dict[str, float]] = {}
        self._seen: dict[str, float] = {}

    def _live(self, account_id: str, now: float) -> dict[str, float]:
        sockets = self._sockets.setdefault(account_id, {})
        for channel, at in list(sockets.items()):
            if at < now - settings.PRESENCE_TTL:
                del sockets[channel]
        return sockets

    def touch(self, account_id: str, channel: str, now: float) -> bool:
        with self._lock:
            sockets = self._live(account_id, now)
            before = len(sockets)
            sockets[channel] = now
            return before == 0

    def drop(self, account_id: str, channel: str, now: float) -> bool:
        with self._lock:
            sockets = self._live(account_id, now)
            sockets.pop(channel, None)
            if not sockets:
                self._seen[account_id] = now
                return True
            return False

    def state(self, account_id: str, now: float) -> tuple[bool, float | None]:
        with self._lock:
            sockets = self._sockets.get(account_id, {})
            if any(at >= now - settings.PRESENCE_TTL for at in sockets.values()):
                return True, None
            candidates = list(sockets.values())
            if account_id in self._seen:
                candidates.append(self._seen[account_id])
            return False, max(candidates) if candidates else None


_store: RedisPresence | MemoryPresence | None = None
_store_lock = threading.Lock()


def store() -> RedisPresence | MemoryPresence:
    global _store
    with _store_lock:
        if _store is None:
            if settings.PRESENCE_BACKEND == "memory":
                _store = MemoryPresence()
            else:
                _store = RedisPresence(settings.REDIS_URL)
        return _store


def reset_store() -> None:
    global _store
    with _store_lock:
        _store = None


def _iso(epoch: float | None) -> str | None:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, tz=UTC).isoformat()


def connect(account_id: str, channel: str) -> bool:
    return store().touch(str(account_id), channel, time.time())


def heartbeat(account_id: str, channel: str) -> bool:
    """Any frame counts as a heartbeat (pings included). True if back online."""
    return store().touch(str(account_id), channel, time.time())


def disconnect(account_id: str, channel: str) -> bool:
    return store().drop(str(account_id), channel, time.time())


def state(account_id: str) -> dict:
    online, last_seen = store().state(str(account_id), time.time())
    return {"account_id": str(account_id), "online": online, "last_seen": _iso(last_seen)}


def is_online(account_id: str) -> bool:
    return store().state(str(account_id), time.time())[0]


def last_seen_now() -> str:
    return _iso(time.time()) or ""
