"""R3 WP 4b.3 acceptance against a real full redis-hot (``maxmemory`` reached,
``noeviction``): ingest returns 202, the SQL rows are stored and the refusal is
counted. Not collected by default; run it against a throwaway Redis:

    docker run -d --rm --name tara-redis-oom --network tara_default redis:7-alpine \\
        redis-server --maxmemory-policy noeviction
    REDIS_OOM_URL=redis://tara-redis-oom:6379/0 \\
        python -m pytest -q -s intel/tests/bench_exposure_oom.py

Never point it at a shared Redis: it fills the instance.
"""

import json
import os
import uuid

import pytest
from django.core.cache import caches

from intel import exposure, hot, metrics

from .helpers import acct, batch, ev, signal_rows

pytestmark = pytest.mark.django_db


@pytest.fixture
def full_redis(settings):
    url = os.getenv("REDIS_OOM_URL", "")
    if not url.startswith("redis://"):
        pytest.skip("needs REDIS_OOM_URL (a throwaway Redis; the test fills it)")
    settings.CACHES = {
        **settings.CACHES,
        "hot": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": url},
    }
    client = hot.raw_client()
    assert client.config_get("maxmemory-policy")["maxmemory-policy"] == "noeviction"
    # Fill it, then put maxmemory well below what is used: noeviction refuses every
    # write from then on (filling up to the limit alone leaves a few-byte margin that
    # moves with client buffers).
    for n in range(8):
        client.set(f"filler:{n}", b"x" * 64 * 1024)
    used = int(client.info("memory")["used_memory"])
    client.config_set("maxmemory", str(used - 256 * 1024))
    yield caches["hot"]
    client.config_set("maxmemory", "0")
    client.flushdb()


def test_ingest_under_real_oom(full_redis, client_for):
    me = acct()
    from redis.exceptions import OutOfMemoryError

    with pytest.raises(OutOfMemoryError):  # really full
        hot.raw_client().set("probe", b"x" * 13)
    before = metrics.HOT_WRITE_FAILED.labels(key="exp")._value.get()
    events = [ev("feed_impression", f"post:{uuid.uuid4()}") for _ in range(50)]
    resp = client_for(me).post(
        "/api/v1/feed/signals/", data=json.dumps(batch(*events)), content_type="application/json"
    )
    after = metrics.HOT_WRITE_FAILED.labels(key="exp")._value.get()
    rows = signal_rows(account_id=me)
    stored = hot.raw_client().get(full_redis.make_key(exposure.ledger_key(me)))
    mem = hot.raw_client().info("memory")
    print(
        f"\nreal OOM: used {mem['used_memory']} of {mem['maxmemory']} B; status "
        f"{resp.status_code}, rows {len(rows)}, refusals {after - before}, ledger {stored!r}"
    )
    assert resp.status_code == 202
    assert resp.json()["data"]["accepted"] == 50 and len(rows) == 50
    assert after == before + 1 and stored is None
