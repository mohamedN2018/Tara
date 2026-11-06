"""Builders for the R4 tests: the seeded taxonomy, post topics, interest rows."""

from __future__ import annotations

from datetime import datetime

from django.utils import timezone

import intel.handlers  # noqa: F401 - registers the bus handlers the R4 tests deliver to
from intel.management.commands import intel_seed_topics
from intel.models import ContentTopic, Topic, UserInterest
from intel.topics import classify


def seed() -> dict[str, int]:
    """The real taxonomy (``intel_seed_topics``); ``{slug: id}``."""
    intel_seed_topics.seed()
    classify.clear_cache()
    from intel import search_signal

    search_signal.clear_cache()
    return dict(Topic.objects.values_list("slug", "id"))


def tag(post_id: str, *pairs: tuple[int, float], source: str = "hashtag") -> None:
    """Give ``post_id`` its topics directly (best first)."""
    ContentTopic.objects.filter(post_id=post_id).delete()
    for topic_id, conf in pairs:
        ContentTopic.objects.create(
            post_id=post_id,
            topic_id=topic_id,
            confidence=conf,
            source=source,
            classified_at=timezone.now(),
        )


def inferred(
    account: str, dim: str, key, value: float, *, at: datetime | None = None, events: int = 4
):
    at = at or timezone.now()
    return UserInterest.objects.create(
        account_id=account,
        dim=dim,
        key=str(key),
        source="inferred",
        short_v=value,
        short_at=at,
        mid_v=value,
        mid_at=at,
        long_v=value,
        long_at=at,
        events_n=events,
        counts={"post_like": events},
        updated_at=at,
    )


def explicit(account: str, dim: str, key, polarity: str):
    return UserInterest.objects.create(
        account_id=account,
        dim=dim,
        key=str(key),
        source="explicit",
        polarity=polarity,
        updated_at=timezone.now(),
    )


def rows(account: str) -> list[tuple]:
    return sorted(
        UserInterest.objects.filter(account_id=account).values_list(
            "dim", "key", "source", "polarity"
        )
    )
