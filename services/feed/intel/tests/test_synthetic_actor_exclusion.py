"""WP 2.9: synthetic and test actors never move post_stats, affinity or reaction_state
unless ``INTEL_SYNTHETIC_IN_RANKING=true`` (dev)."""

import uuid

import feed.handlers  # noqa: F401
import pytest
from feed.models import Affinity, CommentState, PostStats, ReactionState

from intel import origin
from intel.models import SyntheticAccount

from .helpers import acct, deliver, event

pytestmark = pytest.mark.django_db


@pytest.fixture
def seed(settings):
    settings.INTEL_ACCEPT_SYNTHETIC = True
    account = acct()
    SyntheticAccount.objects.create(account_id=account, label="seed-2026-11")
    origin.clear_cache()
    return account


def _engage(actor, post_id, author):
    deliver(event("post.reacted", {"post_id": post_id, "reactor": actor, "author_id": author}))
    deliver(
        event(
            "post.commented",
            {
                "post_id": post_id,
                "comment_id": str(uuid.uuid4()),
                "author": actor,
                "post_author_id": author,
            },
        )
    )
    deliver(event("post.shared", {"post_id": post_id, "sharer": actor, "author_id": author}))


def _stats(post_id):
    s = PostStats.objects.filter(post_id=post_id).first()
    return (s.reactions, s.comments, s.shares) if s else None


def test_synthetic_like_changes_nothing(seed, settings):
    settings.INTEL_SYNTHETIC_IN_RANKING = False
    post_id, author = str(uuid.uuid4()), acct()
    _engage(seed, post_id, author)
    assert _stats(post_id) is None
    assert not Affinity.objects.filter(account_id=seed).exists()
    assert not ReactionState.objects.filter(reactor_id=seed).exists()
    assert not CommentState.objects.filter(post_id=post_id).exists()


def test_test_accounts_are_excluded_too(settings):
    settings.INTEL_ACCEPT_SYNTHETIC = True
    tester = acct()
    SyntheticAccount.objects.create(account_id=tester, label="test-integration")
    origin.clear_cache()
    post_id = str(uuid.uuid4())
    _engage(tester, post_id, acct())
    assert _stats(post_id) is None


def test_dev_flag_lets_synthetic_actors_rank(seed, settings):
    settings.INTEL_SYNTHETIC_IN_RANKING = True
    post_id, author = str(uuid.uuid4()), acct()
    _engage(seed, post_id, author)
    assert _stats(post_id) == (1, 1, 1)
    assert Affinity.objects.get(account_id=seed, author_id=author).interactions == 3


def test_real_actors_still_count(seed):
    post_id, author, real = str(uuid.uuid4()), acct(), acct()
    _engage(real, post_id, author)
    _engage(seed, post_id, author)
    assert _stats(post_id) == (1, 1, 1)
    assert Affinity.objects.filter(author_id=author).count() == 1
