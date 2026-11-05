"""WP 4.3 golden test: the new scorer run with ``home@1`` gives exactly today's order.

``reference_rank_items`` below is a frozen copy of ``feed/ranking.py::rank_items`` as
it was before phase 4 (commit 940cd7f), constants included. The new code path
(``ranking.rank_items`` -> ``intel.ranking.home``: retrieval, eligibility, features,
``RulePredictor``, ``Scorer``) must return the identical order on every ranking
fixture of ``test_hide_rank.py`` and on a dense randomized one with ties. The test
fails if any ``home@1`` constant changes (``test_home_v1_params_are_todays_constants``).
"""

from __future__ import annotations

import math
import random
import uuid
from datetime import timedelta

import pytest
from django.db.models import Count
from django.utils import timezone
from intel import config

from feed import feedback, ranking, readmodels
from feed.models import Affinity, FeedItem, PostHide, PostStats, RelationshipFlag

pytestmark = pytest.mark.django_db

# ---- frozen reference (feed/ranking.py at 940cd7f) ------------------------------------

REF_REASON_AFFINITY = {"self": 0.3, "friend": 1.0, "follow": 0.6}
REF_FRESHNESS_WEIGHT = 3.0
REF_HALF_LIFE_HOURS = 24.0
REF_FAVORITE_BONUS = 1.5
REF_INTERACTION_WEIGHT = 0.25
REF_DISLIKE_WEIGHT = 0.75
REF_DISLIKE_CAP = 3
REF_ENGAGEMENT_WEIGHT = 0.5
REF_WINDOW = 500
REF_SESSION_TTL = 1800
REF_SNOOZE_DAYS = 30
REF_FLAG_WEIGHT = 0.5  # readmodels._FLAG_WEIGHT
REF_ENGAGEMENT = (1, 2, 3)  # reactions, comments, shares in readmodels.engagement_score


def _ref_engagement(stats) -> float:
    raw = max(stats.reactions, 0) + 2 * max(stats.comments, 0) + 3 * max(stats.shares, 0)
    return round(math.log1p(raw) - REF_FLAG_WEIGHT * math.log1p(max(stats.flags, 0)), 6)


def reference_rank_items(viewer_id, now, window=REF_WINDOW):
    items = list(ranking._candidates(viewer_id).order_by("-post_created_at", "-id")[:window])
    authors = {i.author_id for i in items}
    favorites = {
        str(t)
        for t in readmodels.flagged_ids(viewer_id, RelationshipFlag.Kind.FAVORITE).values_list(
            "target_id", flat=True
        )
    }
    interactions = {
        str(a): n
        for a, n in Affinity.objects.filter(
            account_id=viewer_id, author_id__in=authors
        ).values_list("author_id", "interactions")
    }
    dislikes = {
        str(r["author_id"]): r["n"]
        for r in PostHide.objects.filter(
            account_id=viewer_id,
            author_id__in=authors,
            reason__in=feedback.AUTHOR_DOWNWEIGHT_REASONS,
        )
        .values("author_id")
        .annotate(n=Count("id"))
    }
    engagement = {
        str(s.post_id): _ref_engagement(s)
        for s in PostStats.objects.filter(post_id__in={i.post_id for i in items})
    }

    def score(item):
        author = str(item.author_id)
        age_h = max((now - item.post_created_at).total_seconds() / 3600.0, 0.0)
        value = REF_FRESHNESS_WEIGHT * math.pow(2.0, -age_h / REF_HALF_LIFE_HOURS)
        value += REF_REASON_AFFINITY.get(item.reason, 0.0)
        if author in favorites:
            value += REF_FAVORITE_BONUS
        value += REF_INTERACTION_WEIGHT * math.log1p(interactions.get(author, 0))
        value -= REF_DISLIKE_WEIGHT * min(dislikes.get(author, 0), REF_DISLIKE_CAP)
        value += REF_ENGAGEMENT_WEIGHT * engagement.get(str(item.post_id), item.score or 0.0)
        return value

    return sorted(items, key=lambda i: (-score(i), -i.post_created_at.timestamp(), str(i.id)))


# ---- fixtures (the ranking fixtures of test_hide_rank.py) -----------------------------


def _acct():
    return str(uuid.uuid4())


def _item(viewer, author, *, minutes_ago=0, reason="follow", audience="public", at=None):
    post_id = str(uuid.uuid4())
    return FeedItem.objects.create(
        recipient_id=viewer,
        post_id=post_id,
        author_id=author,
        reason=reason,
        snapshot={"post_id": post_id, "author_id": author, "audience": audience},
        post_created_at=at or timezone.now() - timedelta(minutes=minutes_ago),
    )


def _fav(viewer, author):
    RelationshipFlag.objects.create(
        actor_id=viewer, target_id=author, kind="favorite", occurred_at=timezone.now()
    )


def world():
    viewer, author = _acct(), _acct()
    for i in range(12):
        _item(viewer, author, minutes_ago=i)
    _fav(viewer, author)
    return viewer


def mixed_reasons():
    viewer = _acct()
    authors = [_acct() for _ in range(4)]
    for i in range(23):
        _item(viewer, authors[i % 4], minutes_ago=(i * 7) % 23, reason=["follow", "friend"][i % 2])
    return viewer


def fifteen():
    viewer = _acct()
    authors = [_acct() for _ in range(3)]
    for i in range(15):
        _item(viewer, authors[i % 3], minutes_ago=i * 30, reason=["friend", "follow"][i % 2])
    return viewer


def dislikes():
    viewer, liked, disliked = _acct(), _acct(), _acct()
    for i in range(3):
        _item(viewer, disliked, minutes_ago=i)
        _item(viewer, liked, minutes_ago=10 + i)
    hidden = _item(viewer, disliked, minutes_ago=5)
    PostHide.objects.create(
        account_id=viewer, post_id=hidden.post_id, author_id=disliked, reason="dislike_creator"
    )
    return viewer


def engagement():
    viewer, author = _acct(), _acct()
    _item(viewer, author, minutes_ago=1)
    engaged = _item(viewer, author, minutes_ago=30)
    PostStats.objects.create(post_id=engaged.post_id, reactions=1, comments=3, shares=1)
    stale = _item(viewer, author, minutes_ago=45)  # a stored score, no PostStats row
    FeedItem.objects.filter(pk=stale.pk).update(score=1.25)
    return viewer


def affinity():
    viewer, close, distant = _acct(), _acct(), _acct()
    _item(viewer, close, minutes_ago=60)
    _item(viewer, distant, minutes_ago=50)
    Affinity.objects.create(account_id=viewer, author_id=close, interactions=6)
    return viewer


def cold_start():
    viewer = _acct()
    for i in range(6):
        _item(viewer, _acct(), minutes_ago=i * 120)
    return viewer


def favorite_vs_fresh():
    viewer, fav, other = _acct(), _acct(), _acct()
    _item(viewer, fav, minutes_ago=12 * 60)
    _item(viewer, other, minutes_ago=1)
    _fav(viewer, fav)
    return viewer


def self_and_spam():
    viewer, author = _acct(), _acct()
    _item(viewer, viewer, reason="self", minutes_ago=3)
    flagged = _item(viewer, author, minutes_ago=2)
    PostStats.objects.create(post_id=flagged.post_id, reactions=4, flags=2)
    _item(viewer, author, minutes_ago=4, audience="friends", reason="friend")
    return viewer


def dense_with_ties():
    """60 rows, many sharing one timestamp (ties fall to the FeedItem id), random
    stats, favorites, affinities and dislikes."""
    rng = random.Random(4_3)
    viewer = _acct()
    authors = [_acct() for _ in range(9)]
    base = timezone.now() - timedelta(hours=3)
    for i in range(60):
        at = base - timedelta(minutes=rng.choice([0, 0, 0, 15, 90, 600, 2000]))
        a = authors[i % 9]
        item = _item(viewer, a, at=at, reason=rng.choice(["follow", "friend", "self"]))
        if rng.random() < 0.4:
            PostStats.objects.create(
                post_id=item.post_id,
                reactions=rng.randint(0, 40),
                comments=rng.randint(0, 9),
                shares=rng.randint(0, 3),
                flags=rng.randint(0, 2),
            )
    for a in authors[:3]:
        _fav(viewer, a)
    for a in authors[2:6]:
        Affinity.objects.create(account_id=viewer, author_id=a, interactions=rng.randint(1, 30))
    for a in authors[5:8]:
        for _ in range(rng.randint(1, 5)):
            PostHide.objects.create(
                account_id=viewer, post_id=uuid.uuid4(), author_id=a, reason="annoying"
            )
    return viewer


FIXTURES = [
    world,
    mixed_reasons,
    fifteen,
    dislikes,
    engagement,
    affinity,
    cold_start,
    favorite_vs_fresh,
    self_and_spam,
    dense_with_ties,
]


@pytest.mark.parametrize("build", FIXTURES, ids=[f.__name__ for f in FIXTURES])
def test_home_v1_reproduces_todays_order(build):
    viewer = build()
    now = timezone.now()
    expected = [str(i.id) for i in reference_rank_items(viewer, now)]
    assert config.for_surface("home").version == "home@1"
    got = [str(i.id) for i in ranking.rank_items(viewer, now)]
    assert got == expected and got


def test_the_window_is_the_config_window():
    viewer = world()
    now = timezone.now()
    assert [str(i.id) for i in ranking.rank_items(viewer, now, window=5)] == [
        str(i.id) for i in reference_rank_items(viewer, now, window=5)
    ]


def test_home_v1_params_are_todays_constants():
    """Fails when any home@1 constant changes (stored version and package file)."""
    for cfg in (config.for_version("home", 1), config.from_params("home", {})):
        p = cfg.params
        assert p["version"] == 1
        assert p["weights"]["freshness"] == REF_FRESHNESS_WEIGHT
        assert p["freshness"]["half_life_hours"] == REF_HALF_LIFE_HOURS
        assert p["weights"]["relationship"] == 1.0
        assert p["relationship"]["reason_prior"] == REF_REASON_AFFINITY
        assert p["relationship"]["favorite_bonus"] == REF_FAVORITE_BONUS
        assert p["relationship"]["affinity_weight"] == REF_INTERACTION_WEIGHT
        assert p["relationship"]["dislike_weight"] == REF_DISLIKE_WEIGHT
        assert p["relationship"]["dislike_cap"] == REF_DISLIKE_CAP
        assert p["weights"]["engagement"] == REF_ENGAGEMENT_WEIGHT
        e = p["engagement"]
        assert (e["reaction"], e["comment"], e["share"]) == REF_ENGAGEMENT
        assert e["flag_weight"] == REF_FLAG_WEIGHT
        assert p["window"]["connections"] == REF_WINDOW
        assert p["session"]["ttl_s"] == REF_SESSION_TTL
        assert p["feedback"]["snooze_days"] == REF_SNOOZE_DAYS
        assert p["ranking"]["sources"] == ["connections"]
        assert p["diversity"]["enabled"] is False
        # Every term today's formula lacks has weight 0, every multiplier is 1.
        zero = set(p["weights"]) - {
            "freshness",
            "relationship",
            "engagement",
            "explicit_multiplier",
        }
        assert all(p["weights"][k] == 0.0 for k in zero), zero
        assert p["relationship"]["shared_group_weight"] == 0.0
        assert p["relationship"]["conversation_weight"] == 0.0
        i = p["integrity"]
        assert all(
            i[k] == 1.0
            for k in (
                "pending_report_multiplier",
                "duplicate_multiplier",
                "bait_multiplier",
                "spam_flag_multiplier",
            )
        )
        assert i["suspect_account_age_hours"] == 0 and i["suspect_burst_per_min"] == 0


def test_a_changed_constant_changes_the_order():
    """The golden comparison is sensitive: a new freshness weight reorders world()."""
    viewer = favorite_vs_fresh()
    now = timezone.now()
    expected = [str(i.id) for i in reference_rank_items(viewer, now)]
    params = config.store.defaults("home")
    params["relationship"]["favorite_bonus"] = 0.0
    version = config.store.create("home", params)
    config.store.activate("home", version, reason="sensitivity check")
    assert [str(i.id) for i in ranking.rank_items(viewer, now)] != expected
