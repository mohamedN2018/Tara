"""Presence tracking via the cache (Redis in prod). Best-effort, TTL-based."""

from __future__ import annotations

from django.conf import settings
from django.core.cache import cache


def _key(account_id: str) -> str:
    return f"presence.{account_id}"


def mark_online(account_id: str) -> None:
    cache.set(_key(account_id), "online", settings.PRESENCE_TTL)


def refresh(account_id: str) -> None:
    cache.set(_key(account_id), "online", settings.PRESENCE_TTL)


def mark_offline(account_id: str) -> None:
    cache.delete(_key(account_id))


def is_online(account_id: str) -> bool:
    return cache.get(_key(account_id)) == "online"
