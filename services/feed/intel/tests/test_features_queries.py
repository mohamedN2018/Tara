"""WP 4.2: features for 1,050 candidates in at most 12 queries, and no HTTP call."""

import random
from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from feed.models import Affinity, FeedItem, PostHide, PostStats, RelationshipFlag

from intel import config
from intel.ranking import features
from intel.retrieval.sources import CONNECTIONS, FOLLOW_PULL, GROUPS, Candidate
from intel.tests import world as w

pytestmark = pytest.mark.django_db


@pytest.fixture
def no_http(monkeypatch):
    calls = []

    def refuse(*args, **kwargs):
        calls.append(args)
        raise AssertionError("features must not call another service")

    import requests

    monkeypatch.setattr(requests.Session, "request", refuse)
    monkeypatch.setattr(requests, "request", refuse)
    return calls


def _candidates(viewer, n=1050):
    rng = random.Random(7)
    authors = [w.uid() for _ in range(80)]
    out = []
    for i in range(n):
        author = authors[i % len(authors)]
        post = w.post(author, age=timedelta(minutes=i))
        source = [CONNECTIONS, FOLLOW_PULL, GROUPS][i % 3]
        out.append(Candidate(post, author, source, "friend", w.NOW - timedelta(minutes=i), "text"))
        if rng.random() < 0.3:
            PostStats.objects.create(post_id=post, reactions=rng.randint(0, 9))
    for a in authors[:10]:
        Affinity.objects.create(account_id=viewer, author_id=a, interactions=3)
        RelationshipFlag.objects.create(
            actor_id=viewer, target_id=a, kind="favorite", occurred_at=w.NOW
        )
    PostHide.objects.create(
        account_id=viewer, post_id=out[0].post_id, author_id=authors[0], reason="annoying"
    )
    FeedItem.objects.create(
        recipient_id=viewer, post_id=out[0].post_id, author_id=authors[0], post_created_at=w.NOW
    )
    g = w.group(owner=authors[1])
    w.member(viewer, g)
    return out


def test_1050_candidates_take_at_most_12_queries_and_no_http(no_http):
    viewer = w.uid()
    cands = _candidates(viewer)
    cfg = config.for_surface("home")
    with CaptureQueriesContext(connection) as ctx:
        feats = features.build(viewer, cands, cfg, w.NOW)
    assert len(feats) == 1050
    assert len(ctx.captured_queries) <= 12
    assert len(ctx.captured_queries) <= features.MAX_QUERIES
    assert no_http == []
    # The batched lookups really ran: one favorite, one dislike, one reach row.
    first = feats[0]
    assert first.favorite and first.affinity == 3 and first.author_dislikes == 1
    assert first.reach == 1 and first.hides == 1
    assert [f.post_id for f in feats] == [c.post_id for c in cands]


def test_query_count_does_not_grow_with_the_candidates():
    viewer = w.uid()
    cfg = config.for_surface("home")
    counts = []
    for n in (10, 200):
        cands = _candidates(viewer, n)
        with CaptureQueriesContext(connection) as ctx:
            features.build(viewer, cands, cfg, w.NOW)
        counts.append(len(ctx.captured_queries))
    assert counts[0] == counts[1]


def test_no_candidates_no_queries():
    cfg = config.for_surface("home")
    with CaptureQueriesContext(connection) as ctx:
        assert features.build(w.uid(), [], cfg, w.NOW) == []
    assert not ctx.captured_queries
