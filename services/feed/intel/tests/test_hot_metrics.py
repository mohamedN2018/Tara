"""WP 4b.0 / 4b.11: redis-hot memory gauge, refused-write counter, and the 80% alert."""

import os
import re
from pathlib import Path
from unittest import mock

import pytest

from intel import hot, metrics


class _Client:
    def __init__(self, info=None, fail=False):
        self._info, self._fail = info or {}, fail

    def info(self, section):
        assert section == "memory"
        if self._fail:
            raise ConnectionError("down")
        return self._info

    def set(self, *a, **kw):
        raise Exception("OOM command not allowed when used memory > 'maxmemory'.")


def _gauge():
    [family] = list(metrics.HotMemoryCollector().collect())
    assert family.name == "intel_redis_hot_used_ratio"
    return [s.value for s in family.samples]


def test_used_ratio_is_read_at_scrape():
    with mock.patch.object(
        hot, "raw_client", return_value=_Client({"used_memory": 322122547, "maxmemory": 402653184})
    ):
        assert _gauge() == [pytest.approx(0.8)]


def test_no_sample_without_a_limit_or_when_unreachable():
    with mock.patch.object(hot, "raw_client", return_value=_Client({"used_memory": 5})):
        assert _gauge() == []
    with mock.patch.object(hot, "raw_client", return_value=_Client(fail=True)):
        assert _gauge() == []
    with mock.patch.object(hot, "raw_client", return_value=None):
        assert _gauge() == []


def test_the_collector_is_registered_once():
    from prometheus_client import REGISTRY

    metrics.register_collectors()
    metrics.register_collectors()
    names = [
        c
        for c in REGISTRY._collector_to_names
        if isinstance(c, metrics.HotMemoryCollector)  # noqa: SLF001
    ]
    assert len(names) == 1


def test_a_refused_write_is_counted_and_never_raises():
    before = metrics.HOT_WRITE_FAILED.labels(key="head")._value.get()
    with mock.patch.object(hot, "raw_client", return_value=_Client()):
        assert hot.raw_set("feed:head:home:x", b"1", 60, "head") is False
    assert metrics.HOT_WRITE_FAILED.labels(key="head")._value.get() == before + 1


def _alerts_file() -> Path | None:
    here = Path(__file__).resolve().parents
    bases = [os.getenv("TARA_REPO", "")] + [str(p) for p in here[3:5]]
    for base in bases:
        path = Path(base) / "infra" / "observability" / "alerts.yml" if base else None
        if path and path.is_file():
            return path
    return None


def test_the_alert_fires_above_80_percent():
    """The rule in infra/observability/alerts.yml (promtool's unit test in
    infra/observability/tests/intel-alerts.test.yml runs it on a series too)."""
    path = _alerts_file()
    if path is None:
        pytest.skip("infra/ is not in the image; run with TARA_REPO or check_deploy.sh")
    text = path.read_text(encoding="utf-8")
    block = text[text.index("alert: IntelRedisHotMemoryHigh") :]
    expr = re.search(r"expr:\s*(.+)", block).group(1).strip()
    m = re.fullmatch(r"max\(intel_redis_hot_used_ratio\)\s*>\s*([0-9.]+)", expr)
    assert m, expr
    threshold = float(m.group(1))
    assert 0.81 > threshold and not 0.79 > threshold
