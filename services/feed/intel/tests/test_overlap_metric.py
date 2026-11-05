"""WP 4b.11: the first-page overlap metric. The head (ids only) is written with its
TTL, the next first page's Jaccard is observed, nothing is stored under
personalization_off or a version without the head block, and a refused write never
fails the page."""

import uuid
from unittest import mock

import pytest

from intel import config, head, hot, metrics
from intel.models import UserPreference

from . import variants
from . import world as w

pytestmark = pytest.mark.django_db


def _ids(n):
    return [str(uuid.uuid4()) for _ in range(n)]


def _hist():
    count = sum(
        s.value
        for m in metrics.FIRST_PAGE_OVERLAP.collect()
        for s in m.samples
        if s.name.endswith("_count")
    )
    return count, metrics.REPEAT_DISPLAY._value.get()


def test_head_written_then_overlap_observed(redis_hot):
    cfg = variants.cfg()
    viewer = w.uid()
    first = _ids(20)
    count0, repeat0 = _hist()
    assert head.record(viewer, "home", first, cfg) is None  # nothing to compare yet
    client = hot.raw_client()
    key = redis_hot.make_key(hot.head_key("home", viewer))
    raw = client.get(key)
    assert raw == b"".join(uuid.UUID(p).bytes for p in first)  # ids only, 16 B each
    assert 0 < client.ttl(key) <= cfg.get("head.ttl_s")
    second = first[:10] + _ids(10)
    assert head.record(viewer, "home", second, cfg) == pytest.approx(10 / 30)
    count1, repeat1 = _hist()
    assert count1 == count0 + 1 and repeat1 == repeat0 + 10
    assert head.record(viewer, "home", second, cfg) == 1.0  # the same page again


def test_nothing_stored_under_personalization_off(redis_hot):
    viewer = w.uid()
    UserPreference.objects.create(account_id=viewer, personalization_off=True)
    assert head.record(viewer, "home", _ids(5), variants.cfg()) is None
    assert hot.raw_client().exists(redis_hot.make_key(hot.head_key("home", viewer))) == 0


def test_nothing_stored_without_the_head_block(redis_hot):
    viewer = w.uid()
    assert "head" not in config.for_surface("home").params  # home@1
    assert head.record(viewer, "home", _ids(5), config.for_surface("home")) is None
    assert hot.raw_client().exists(redis_hot.make_key(hot.head_key("home", viewer))) == 0


def test_a_refused_write_is_counted_and_the_page_goes_on(redis_hot):
    viewer = w.uid()
    before = metrics.HOT_WRITE_FAILED.labels(key="head")._value.get()
    real = hot.raw_client()

    class Full:
        def get(self, *a):
            return real.get(*a)

        def set(self, *a, **kw):
            raise Exception("OOM command not allowed when used memory > 'maxmemory'.")

    with mock.patch.object(hot, "raw_client", return_value=Full()):
        assert head.record(viewer, "home", _ids(3), variants.cfg()) is None
    assert metrics.HOT_WRITE_FAILED.labels(key="head")._value.get() == before + 1


def test_the_home_view_records_the_head_of_a_ranked_first_page(redis_hot, client_for):
    variants.activate(variants.CONTROL)
    viewer, friend = w.uid(), w.uid()
    for _ in range(3):
        w.feed_row(viewer, w.post(friend), friend)
    resp = client_for(viewer).get("/api/v1/feed/", {"mode": "for_you"})
    assert resp.status_code == 200
    served = [i["post_id"] for i in resp.json()["data"]]
    raw = hot.raw_client().get(redis_hot.make_key(hot.head_key("home", viewer)))
    assert raw == b"".join(uuid.UUID(p).bytes for p in served)
    # A later page never touches the head.
    assert resp.json()["meta"]["caught_up_index"] is None
