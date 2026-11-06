"""Owner decision 12: no inferred interest on a sensitive topic (politics, religion,
Quran) without the account's opt-in, in every writer: the aggregator, the feedback
service and the session vector. Explicit rows stay the user's own choice. Turning the
opt-in off deletes the inferred sensitive rows."""

from datetime import timedelta

import pytest
from django.utils import timezone

from intel import config, feedback, preferences, session_ctx
from intel.models import UserInterest, UserPreference
from intel.signals import interests_agg, store

from . import r4
from . import world as w

pytestmark = pytest.mark.django_db


def _like(account, post_id, author, at):
    store.insert_row(
        store.SignalRow(
            account_id=account,
            event_type="post_like",
            item_type="post",
            item_id=post_id,
            author_id=author,
            source="bus",
            data_origin="real",
            occurred_at=at,
            received_at=at,
        )
    )


def _topic_keys(account) -> set[str]:
    return set(
        UserInterest.objects.filter(account_id=account, dim="topic", source="inferred").values_list(
            "key", flat=True
        )
    )


def test_aggregator_skips_sensitive_topics_without_opt_in():
    ids = r4.seed()
    viewer, opted, author = w.uid(), w.uid(), w.uid()
    UserPreference.objects.create(account_id=opted, sensitive_inference=True)
    p = w.post(author)
    r4.tag(p, (ids["politics"], 0.9), (ids["history"], 0.6))
    at = timezone.now() - timedelta(minutes=10)
    _like(viewer, p, author, at)
    _like(opted, p, author, at)
    interests_agg.aggregate(timezone.now(), timedelta(minutes=2), config.for_surface("home"))
    assert _topic_keys(viewer) == {str(ids["history"])}
    assert _topic_keys(opted) == {str(ids["history"]), str(ids["politics"])}
    # Turning the opt-in off deletes the inferred sensitive rows (explicit ones stay).
    r4.explicit(opted, "topic", ids["quran"], "like")
    preferences.patch(opted, {"sensitive_inference": False})
    assert _topic_keys(opted) == {str(ids["history"])}
    assert UserInterest.objects.filter(account_id=opted, key=str(ids["quran"])).exists()


def test_feedback_writes_no_inferred_sensitive_delta():
    ids = r4.seed()
    viewer, author = w.uid(), w.uid()
    p = w.post(author)
    r4.tag(p, (ids["religion"], 0.9), (ids["books"], 0.7))
    item = feedback.item_for_system("post", p, author)
    feedback.act(viewer, item, "more_like_this")
    assert _topic_keys(viewer) == {str(ids["books"])}
    # A mute of a sensitive topic is the user's explicit choice: stored.
    feedback.act(viewer, item, "mute_topic", topic_slug="religion")
    assert UserInterest.objects.filter(
        account_id=viewer, key=str(ids["religion"]), source="explicit", polarity="muted"
    ).exists()


def test_session_vector_skips_a_sensitive_topic():
    deltas = session_ctx.si_deltas(
        topic_id=7, fmt="text", author_prefix=b"\x01" * 8, weight=1.0, sensitive=True
    )
    assert [name for name, _ in deltas] == ["f:text", "c:" + "01" * 8]
