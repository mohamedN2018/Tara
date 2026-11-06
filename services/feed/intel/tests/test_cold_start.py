"""04 WP 6.6 / 6.7 (feed side): cold start.

- ``account.updated`` (identity, language only) fills the account language read model,
  newest wins, and is idempotent;
- a new account gets a non-empty, language-matched first page: recommended items in
  its account language (rule E10), plus ``und``;
- the optional onboarding picker (decision 11) writes explicit ``like`` rows for the
  chosen topics and sets ``onboarded_at``; "skip" writes no row; under home@3 a chosen
  topic's pool items rank first among the recommendations.
"""

from datetime import timedelta

import pytest
from feed.models import ReactionState

from intel import discovery
from intel.models import AccountLanguage, UserInterest, UserPreference

from . import r4, variants
from . import world as w
from .helpers import ADULT_CLAIMS, client_with_claims, deliver, event

pytestmark = pytest.mark.django_db


def _pool(lang, n, *, topic=None, minutes=0):
    out = []
    for i in range(n):
        p = w.post(w.uid(), lang=lang, age=timedelta(hours=1, minutes=minutes + i))
        ReactionState.objects.create(post_id=p, reactor_id=w.uid(), active=True, occurred_at=w.NOW)
        if topic:
            r4.tag(p, (topic, 0.9))
        out.append(p)
    return out


def test_account_updated_fills_the_language_read_model():
    account = w.uid()
    deliver(
        event(
            "account.updated",
            {"account_id": account, "changed": ["language"], "language": "ar"},
            at=w.NOW,
        ),
        only_intel=True,
    )
    assert AccountLanguage.objects.get(account_id=account).language == "ar"
    older = w.NOW - timedelta(hours=1)
    deliver(
        event(
            "account.updated",
            {"account_id": account, "changed": ["language"], "language": "en"},
            at=older,
        ),
        only_intel=True,
    )
    assert AccountLanguage.objects.get(account_id=account).language == "ar"  # newest wins
    deliver(
        event(
            "account.updated", {"account_id": account, "changed": ["language"], "language": "en"}
        ),
        only_intel=True,
    )
    assert AccountLanguage.objects.get(account_id=account).language == "en"


def test_new_account_gets_a_language_matched_page(redis_hot, monkeypatch):
    monkeypatch.setattr("feed.ads_client.feed_sponsored", lambda viewer: None)
    variants.activate(variants.R15)
    arabic = set(_pool("ar", 15))
    english = set(_pool("en", 15, minutes=30))
    discovery.rebuild(variants.cfg(variants.R15), now=w.NOW)
    viewer = w.uid()
    AccountLanguage.objects.create(account_id=viewer, language="ar", event_at=w.NOW)
    body = (
        client_with_claims(viewer, **ADULT_CLAIMS)
        .get("/api/v1/feed/", {"mode": "for_you", "limit": 20})
        .json()
    )
    served = {i["post_id"] for i in body["data"]}
    assert served and served <= arabic
    assert not (served & english)


def test_onboarding_writes_explicit_rows_and_skip_writes_none(redis_hot):
    ids = r4.seed()
    viewer, skipper = w.uid(), w.uid()
    c = client_with_claims(viewer, **ADULT_CLAIMS)
    resp = c.post(
        "/api/v1/feed/preferences/onboarding/", {"topics": ["cooking", "travel"]}, format="json"
    )
    assert resp.status_code == 200 and resp.json()["data"]["onboarded_at"]
    rows = set(
        UserInterest.objects.filter(account_id=viewer).values_list("key", "polarity", "source")
    )
    assert rows == {
        (str(ids["cooking"]), "like", "explicit"),
        (str(ids["travel"]), "like", "explicit"),
    }
    s = client_with_claims(skipper, **ADULT_CLAIMS)
    assert (
        s.post(
            "/api/v1/feed/preferences/onboarding/",
            {"topics": ["x"], "skipped": True},
            format="json",
        ).status_code
        == 200
    )
    assert not UserInterest.objects.filter(account_id=skipper).exists()
    assert UserPreference.objects.get(account_id=skipper).onboarded_at is not None
    bad = c.post(
        "/api/v1/feed/preferences/onboarding/", {"topics": ["no-such-topic"]}, format="json"
    )
    assert bad.status_code == 400
    too_many = c.post(
        "/api/v1/feed/preferences/onboarding/", {"topics": list(ids)[:11]}, format="json"
    )
    assert too_many.status_code == 400


def test_onboarded_topic_leads_the_recommendations_under_home3(redis_hot, monkeypatch):
    monkeypatch.setattr("feed.ads_client.feed_sponsored", lambda viewer: None)
    ids = r4.seed()
    variants.activate(variants.H3_R15)
    chosen = set(_pool("en", 6, topic=ids["travel"], minutes=40))  # older: lower base score
    _pool("en", 20, topic=ids["gaming"])
    discovery.rebuild(variants.cfg(variants.H3_R15), now=w.NOW)
    viewer = w.uid()
    c = client_with_claims(viewer, **ADULT_CLAIMS)
    c.post("/api/v1/feed/preferences/onboarding/", {"topics": ["travel"]}, format="json")
    body = c.get("/api/v1/feed/", {"mode": "for_you", "limit": 10}).json()
    first = [i["post_id"] for i in body["data"]][:4]
    assert len(set(first) & chosen) >= 3
    assert all(i["topics"] for i in body["data"])  # every item carries its topics
