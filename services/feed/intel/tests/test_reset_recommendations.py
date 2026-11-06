"""07 WP 8.4-B2: Reset recommendations.

Two steps (a confirm token first); one reset per ``reset.min_interval_h`` (429 with
``Retry-After``); in one transaction ``reset_at``, the change log and
``feed.recommendations.reset``; then the Celery task deletes, per weekly partition,
the engagement rows, the inferred interests, the decayed affinity, the visit rows and
the behavioural keys (``feed:exp``, ``feed:sess``, ``feed:si``, ``feed:head:*``,
``feed:rank:*``, ``intel:prof``). Kept: explicit topics, mutes, hidden creators,
follows, blocks, hides and item-level Not interested. Afterwards Home page 1 equals a
cold-start page for the same connections."""

from datetime import timedelta

import pytest
from django.db import connection
from django.utils import timezone
from feed import ranking
from feed.models import Affinity, FollowEdge, OutboxEvent, PostHide

from intel import hot
from intel.models import FeedbackAction, FeedSession, PreferenceChange, UserInterest, UserPreference
from intel.signals import partitions

from . import r4
from . import world as w
from .helpers import ADULT_CLAIMS, client_with_claims

pytestmark = pytest.mark.django_db
URL = "/api/v1/feed/preferences/reset/"


def _engagement_rows(account):
    with connection.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM intel_user_item_engagement WHERE account_id = %s", [account]
        )
        return cur.fetchone()[0]


def _seed_behaviour(viewer, ids, redis_hot):
    now = timezone.now()
    for days in (1, 9, 16):  # three weekly partitions
        first = now - timedelta(days=days)
        partitions.ensure(partitions.ENGAGEMENT, first.date())
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO intel_user_item_engagement (account_id, item_id, item_type, "
                "impressions, opens, max_watch_ms, completions, rewatches, skips, positive, "
                "negative, first_at, last_at, data_origin, dwell_ms, consumed_dwell_only, visits) "
                "VALUES (%s, %s, 'post', 1, 0, 0, 0, 0, 0, 0, 0, %s, %s, 'real', 0, false, 1)",
                [viewer, w.uid(), first, first],
            )
    r4.inferred(viewer, "topic", ids["cooking"], 3.0)
    r4.explicit(viewer, "topic", ids["travel"], "like")
    r4.explicit(viewer, "topic", ids["politics"], "muted")
    r4.explicit(viewer, "creator", w.uid(), "hidden")
    author = w.uid()
    Affinity.objects.create(account_id=viewer, author_id=author, interactions=7)
    FeedSession.objects.create(
        id=w.uid(), account_id=viewer, kind="new", entry_surface="home", started_at=now,
        last_activity_at=now, data_origin="real",
    )  # fmt: skip
    for key in hot.behaviour_keys(viewer):
        hot.raw_client().set(redis_hot.make_key(key), b"x", ex=600)
    w.follow(viewer, author)
    p = w.post(author)
    w.feed_row(viewer, p, author)
    PostHide.objects.create(
        account_id=viewer, post_id=w.post(author), author_id=author, reason="spam"
    )
    FeedbackAction.objects.create(
        id=w.uid(), account_id=viewer, item_type="post", item_id=p, action="not_interested",
        created_at=now,
    )  # fmt: skip


def test_two_step_reset_deletes_behaviour_and_keeps_explicit_choices(
    redis_hot, django_capture_on_commit_callbacks
):
    ids = r4.seed()
    viewer = w.uid()
    _seed_behaviour(viewer, ids, redis_hot)
    client = client_with_claims(viewer, **ADULT_CLAIMS)
    step1 = client.post(URL, {}, format="json")
    assert step1.status_code == 200
    data = step1.json()["data"]
    assert data["confirm_token"] and "inferred_interests" in data["scope"]
    assert "explicit_topics" in data["keeps"]
    bad = client.post(URL, {"confirm_token": "forged"}, format="json")
    assert bad.status_code == 400
    with django_capture_on_commit_callbacks(execute=True):
        step2 = client.post(URL, {"confirm_token": data["confirm_token"]}, format="json")
    assert step2.status_code == 202
    assert UserPreference.objects.get(account_id=viewer).reset_at is not None
    # Deleted.
    assert _engagement_rows(viewer) == 0
    assert not UserInterest.objects.filter(account_id=viewer, source="inferred").exists()
    assert not Affinity.objects.filter(account_id=viewer).exists()
    assert not FeedSession.objects.filter(account_id=viewer).exists()
    stored = hot.raw_client()
    assert [k for k in hot.behaviour_keys(viewer) if stored.exists(redis_hot.make_key(k))] == []
    # Kept.
    kept = set(UserInterest.objects.filter(account_id=viewer).values_list("polarity", flat=True))
    assert kept == {"like", "muted", "hidden"}
    assert FollowEdge.objects.filter(follower_id=viewer).exists()
    assert PostHide.objects.filter(account_id=viewer).exists()
    assert FeedbackAction.objects.filter(account_id=viewer).exists()
    event = OutboxEvent.objects.filter(event_type="feed.recommendations.reset").last()
    assert event.payload["payload"]["account_id"] == viewer
    assert PreferenceChange.objects.filter(account_id=viewer, source="reset").count() == 1
    # A second reset within 24 h: 429 with Retry-After.
    token = client.post(URL, {}, format="json").json()["data"]["confirm_token"]
    again = client.post(URL, {"confirm_token": token}, format="json")
    assert again.status_code == 429 and int(again["Retry-After"]) > 23 * 3600
    body = client.get("/api/v1/feed/preferences/").json()["data"]
    assert body["reset_available_at"] is not None


def test_after_reset_page_1_equals_a_cold_start_page(redis_hot, django_capture_on_commit_callbacks):
    r4.seed()
    viewer, twin = w.uid(), w.uid()  # the twin has the same connections and no history
    for i in range(15):
        f = w.uid()
        p = w.post(f, age=timedelta(minutes=3 + 5 * i))
        w.feed_row(viewer, p, f)
        w.feed_row(twin, p, f)
    r4.inferred(viewer, "creator", w.uid(), 4.0)
    Affinity.objects.create(account_id=viewer, author_id=w.uid(), interactions=9)
    client = client_with_claims(viewer, **ADULT_CLAIMS)
    token = client.post(URL, {}, format="json").json()["data"]["confirm_token"]
    with django_capture_on_commit_callbacks(execute=True):
        client.post(URL, {"confirm_token": token}, format="json")
    claims = {"sub": viewer, **ADULT_CLAIMS}
    mine = [str(i.post_id) for i in ranking.rank_items(viewer, w.NOW, claims=claims)]
    cold = [str(i.post_id) for i in ranking.rank_items(twin, w.NOW, claims={**claims, "sub": twin})]
    assert mine == cold
