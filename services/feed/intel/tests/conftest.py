"""Fixtures shared by the intel tests."""

from __future__ import annotations

import os
import uuid

import pytest
from django.core.cache import caches


@pytest.fixture
def redis_hot(settings):
    """A real Redis behind the hot cache (pools are sorted sets and the raw keys of
    WP 4b.0 are written with the raw client: no local-memory stand-in). Every key
    gets a per-test prefix and is deleted afterwards."""
    from intel import hot

    url = os.getenv("REDIS_URL", "")
    if not url.startswith("redis://"):
        pytest.skip("needs Redis (REDIS_URL)")
    settings.CACHES = {
        **settings.CACHES,
        "hot": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": url,
            "KEY_PREFIX": f"feed-test-{uuid.uuid4().hex[:8]}",
        },
    }
    # Changing CACHES resets Django's cache handler (django.test.signals).
    try:
        hot.raw_client().ping()
    except Exception:  # noqa: BLE001
        pytest.skip("Redis unreachable")
    yield caches["hot"]
    client = hot.raw_client()
    for key in client.scan_iter(match=caches["hot"].make_key("*")):
        client.delete(key)
