"""Hydration hints and the server-side drop counter (intelligence WP 3.6).

``/posts/batch/`` and ``/reels/batch/`` accept two optional hints that the web
copies from feed's response: ``surface`` (where the ids were served) and
``src`` (the candidate source of each id, one string for the whole batch or a
list parallel to ``ids``). Every requested id the batch does not return (the
viewer may not see it, or it is gone) increments
``post_batch_dropped_total{caller,surface,src}``.

The hints are labels only: they never change what is returned, a malformed
hint is ignored, and an unknown value is folded into ``other`` so a client
cannot grow the metric's label set. Client-reported drop flags are never used
for this metric.

post runs several gunicorn workers, each with its own Prometheus registry, so
an in-process counter would show only the worker a scrape happens to reach.
The counts live in the shared cache (Redis) instead, one integer per label
combination (at most ``len(CALLERS) x 11 x 13`` keys), and a collector reads
them all at scrape time. A cache failure never fails the batch.
"""

from __future__ import annotations

import itertools
import logging
from collections import Counter as _Tally

from django.core.cache import cache
from rest_framework import serializers

logger = logging.getLogger("tara.post.hydration")

METRIC = "post_batch_dropped_total"
_KEY = "post:batch_dropped:{}:{}:{}"

#: The public batch endpoints are called by the web client only.
CALLER_WEB = "web"
CALLERS = (CALLER_WEB,)
#: A hint that was not sent.
NONE = "none"
#: A hint outside the vocabulary below.
OTHER = "other"

#: Feed's surfaces (``intel.models.Surface``).
SURFACES = frozenset(
    {"home", "reels", "video", "groups", "marketplace", "discovery", "profile", "search", "link"}
)
#: Candidate sources (docs/intelligence/02 section 6.1) plus today's Home
#: fan-out reasons (feed's ``FeedItem.Reason``: self, friend, follow).
SOURCES = frozenset(
    {
        "self",
        "friend",
        "follow",
        "connections",
        "follow_pull",
        "groups",
        "discovery",
        "trending",
        "new_creators",
        "reels",
        "video",
    }
)
#: Sources whose drops must be 0 (docs/intelligence/02 section 13): every one
#: of their items already passed feed's fail-closed eligibility.
DISCOVERY_SOURCES = frozenset({"discovery", "trending", "new_creators"})


def _all_label_sets() -> list[tuple[str, str, str]]:
    return list(
        itertools.product(
            CALLERS, sorted(SURFACES | {NONE, OTHER}), sorted(SOURCES | {NONE, OTHER})
        )
    )


def _label(value, vocabulary: frozenset[str]) -> str:
    if value is None or value == "":
        return NONE
    return value if isinstance(value, str) and value in vocabulary else OTHER


class BatchHintsMixin(serializers.Serializer):
    """The optional ``surface`` and ``src`` hints of a batch request. Any JSON
    is accepted: a malformed hint is labelled, never refused."""

    surface = serializers.JSONField(required=False, allow_null=True)
    src = serializers.JSONField(
        required=False,
        allow_null=True,
        help_text="One source for every id, or a list parallel to ids.",
    )


def labels(ids: list, data: dict) -> tuple[str, list[str]]:
    """``(surface label, src label per id)`` for a validated batch body."""
    surface = _label(data.get("surface"), SURFACES)
    raw = data.get("src")
    if isinstance(raw, list):
        if len(raw) != len(ids):
            srcs = [NONE] * len(ids)
        else:
            srcs = [_label(s, SOURCES) for s in raw]
    else:
        srcs = [_label(raw, SOURCES)] * len(ids)
    return surface, srcs


def record_drops(ids: list, returned_ids, data: dict, caller: str = CALLER_WEB) -> dict:
    """Count the requested ids missing from ``returned_ids``; returns the tally
    ``{(surface, src): n}`` (for tests and logs)."""
    returned = {str(x) for x in returned_ids}
    surface, srcs = labels(ids, data)
    tally: _Tally = _Tally()
    seen: set[str] = set()
    for post_id, src in zip(ids, srcs, strict=True):
        key = str(post_id)
        if key in returned or key in seen:
            continue
        seen.add(key)
        tally[(surface, src)] += 1
    for (surface_label, src_label), n in tally.items():
        key = _KEY.format(caller, surface_label, src_label)
        try:
            cache.add(key, 0, timeout=None)
            cache.incr(key, n)
        except Exception:  # noqa: BLE001 - a metric must never fail a read
            logger.warning("batch drop counter unavailable", exc_info=True)
            break
    return dict(tally)


def counts() -> dict[tuple[str, str, str], int]:
    """Every non-zero ``(caller, surface, src)`` count, from the shared cache."""
    label_sets = _all_label_sets()
    keys = {_KEY.format(*labels): labels for labels in label_sets}
    values = cache.get_many(list(keys))
    return {keys[k]: int(v) for k, v in values.items() if v}


class DropCollector:
    """Exposes the shared counts as ``post_batch_dropped_total`` on every worker."""

    def collect(self):
        from prometheus_client.core import CounterMetricFamily

        family = CounterMetricFamily(
            METRIC,
            "Ids a hydration batch was asked for and did not return (not visible or gone).",
            labels=["caller", "surface", "src"],
        )
        try:
            for labels, value in sorted(counts().items()):
                family.add_metric(list(labels), value)
        except Exception:  # noqa: BLE001 - a scrape must not fail on the cache
            logger.warning("batch drop counter unavailable", exc_info=True)
        yield family

    def describe(self):
        return []


_registered = False


def register() -> None:
    """Register the collector once per process (``PostsConfig.ready``)."""
    global _registered  # noqa: PLW0603 - one registration per process
    if _registered:
        return
    try:
        from prometheus_client import REGISTRY
    except ImportError:  # pragma: no cover - metrics are optional
        return
    # ``describe`` names nothing, so registering never reads the cache at boot.
    REGISTRY.register(DropCollector())
    _registered = True
