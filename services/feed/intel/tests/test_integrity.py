"""WP 4.4: integrity signals. Pending reports demote (never remove), near copies are
demoted except the oldest, bait is scored from the lexicons, and suspect reactions
are excluded from rates. Thresholds come from the home config's integrity block."""

from datetime import timedelta

import pytest
from django.utils import timezone
from feed import readmodels as feed_readmodels
from feed.models import Affinity, AuthorRef, PostStats, ReactionState

import intel.handlers  # noqa: F401 - registers the read-model handlers
from intel import config, integrity, readmodels
from intel.models import ContentRef
from intel.tests.helpers import deliver, event

pytestmark = pytest.mark.django_db

TEXT = "Our bakery opens at eight tomorrow with fresh sourdough and cinnamon rolls for everyone"


def _created(author, text, *, at, audience="public", post_id=None):
    import uuid

    post_id = post_id or str(uuid.uuid4())
    readmodels.content_created(
        {
            "post_id": post_id,
            "author_id": author,
            "author_type": "user",
            "type": "text",
            "audience": audience,
            "excerpt": text,
            "media_ids": [],
            "hashtags": [],
            "created_at": at.isoformat(),
            "group_id": None,
            "approval_state": "approved",
        },
        at,
    )
    return post_id


def _v2():
    params = config.store.defaults("home", 2)
    config.store.activate("home", config.store.create("home", params), reason="test")


# ---- SimHash ------------------------------------------------------------------------


def test_simhash_is_deterministic_signed_and_tolerant_to_small_edits():
    a = integrity.simhash(TEXT, 4)
    assert a == integrity.simhash(TEXT, 4)
    assert -(2**63) <= a < 2**63
    edited = integrity.simhash(TEXT.replace("eight", "nine") + "!!", 4)
    other = integrity.simhash("Traffic on the ring road is terrible today, leave early please", 4)
    assert integrity.hamming(a, edited) <= 12
    assert integrity.hamming(a, other) > 3
    # Case, Arabic spelling variants and punctuation do not change the hash.
    assert integrity.simhash(TEXT.upper(), 4) == a
    ar = "الإسكندرية جميلة جدا في الشتاء والبحر هادي"
    assert integrity.simhash(ar, 4) == integrity.simhash(
        "الاسكندريه جميله جدا في الشتاء، والبحر هادي!", 4
    )


def test_short_texts_are_never_copies():
    assert integrity.simhash("hi", 4) is None
    assert integrity.simhash("", 4) is None


def test_a_copy_points_at_the_oldest_live_original_and_the_original_at_nothing():
    author, other = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
    now = timezone.now()
    first = _created(author, TEXT, at=now - timedelta(days=3), audience="friends")
    second = _created(author, TEXT, at=now - timedelta(days=1), audience="friends")
    stranger = _created(other, TEXT, at=now - timedelta(hours=2))
    refs = {r.post_id: r for r in ContentRef.objects.all()}
    assert refs[_uuid(first)].dup_of is None
    assert str(refs[_uuid(second)].dup_of) == first  # same author within 30 days
    # A stranger's copy: only a public original of the last 24 h counts.
    assert refs[_uuid(stranger)].dup_of is None
    third = _created(other, TEXT, at=now - timedelta(hours=1))
    assert str(ContentRef.objects.get(post_id=third).dup_of) == stranger


def test_events_out_of_order_still_mark_the_later_copy():
    author = "33333333-3333-3333-3333-333333333333"
    now = timezone.now()
    later = _created(author, TEXT, at=now - timedelta(hours=1))
    assert ContentRef.objects.get(post_id=later).dup_of is None
    earlier = _created(author, TEXT, at=now - timedelta(hours=5))
    assert ContentRef.objects.get(post_id=earlier).dup_of is None
    assert str(ContentRef.objects.get(post_id=later).dup_of) == earlier


def test_an_unrelated_post_is_no_copy_and_the_distance_is_configurable():
    author = "44444444-4444-4444-4444-444444444444"
    now = timezone.now()
    _created(author, TEXT, at=now - timedelta(hours=3))
    unrelated = _created(
        author, "Lost my keys in Zamalek near the bookshop, black keychain", at=now
    )
    assert ContentRef.objects.get(post_id=unrelated).dup_of is None


def _uuid4():
    import uuid

    return uuid.uuid4()


def _uuid(s):
    import uuid

    return uuid.UUID(s)


# ---- bait -----------------------------------------------------------------------------


def test_bait_score_is_stored_from_the_excerpt():
    post = _created(
        "55555555-5555-5555-5555-555555555555", "اعمل شير ومنشن صاحبك", at=timezone.now()
    )
    assert ContentRef.objects.get(post_id=post).bait_score == 0.75
    clean = _created("55555555-5555-5555-5555-555555555555", TEXT, at=timezone.now())
    assert ContentRef.objects.get(post_id=clean).bait_score == 0.0


def test_the_excerpt_is_never_stored():
    post = _created("66666666-6666-6666-6666-666666666666", TEXT, at=timezone.now())
    row = ContentRef.objects.filter(post_id=post).values().get()
    assert TEXT not in str(row)


# ---- pending reports ----------------------------------------------------------------


def test_reports_count_distinct_reporters_and_a_decision_clears_them():
    post = _created("77777777-7777-7777-7777-777777777777", TEXT, at=timezone.now())
    now = timezone.now()
    for _ in range(3):
        deliver(
            event("post.reported", {"post_id": post, "reporter": str(_uuid4())}, at=now),
            only_intel=True,
        )
    row = ContentRef.objects.get(post_id=post)
    assert row.pending_reports == 3 and row.moderation_open and row.state == "live"
    deliver(
        event(
            "moderation.actioned",
            {"target_type": "post", "target_id": post, "action": "dismiss", "case_id": None},
            at=now + timedelta(minutes=1),
        ),
        only_intel=True,
    )
    row.refresh_from_db()
    assert row.pending_reports == 0 and not row.moderation_open


# ---- suspect engagement ---------------------------------------------------------------


def _react(post, reactor, author, at, active=True):
    return feed_readmodels.set_reaction(post, reactor, author, active, at)


def test_home_v1_counts_every_reaction():
    now = timezone.now()
    reactor = "88888888-8888-8888-8888-888888888888"
    AuthorRef.objects.create(account_id=reactor, occurred_at=now, registered_at=now)
    post, author = "99999999-9999-9999-9999-999999999999", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert _react(post, reactor, author, now) == 1
    assert PostStats.objects.get(post_id=post).reactions == 1


def test_a_brand_new_account_reacts_but_is_not_counted():
    _v2()
    now = timezone.now()
    reactor = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    AuthorRef.objects.create(
        account_id=reactor, occurred_at=now, registered_at=now - timedelta(hours=2)
    )
    post, author = "cccccccc-cccc-cccc-cccc-cccccccccccc", "dddddddd-dddd-dddd-dddd-dddddddddddd"
    assert _react(post, reactor, author, now) == 0
    assert ReactionState.objects.get(post_id=post, reactor_id=reactor).suspect is True
    assert not PostStats.objects.filter(post_id=post, reactions__gt=0).exists()
    assert not Affinity.objects.filter(account_id=reactor, interactions__gt=0).exists()
    # Its unreact subtracts nothing (the counted reactions stay correct).
    PostStats.objects.update_or_create(post_id=post, defaults={"reactions": 4})
    assert _react(post, reactor, author, now + timedelta(minutes=1), active=False) == 0
    assert PostStats.objects.get(post_id=post).reactions == 4


def test_an_old_or_unknown_account_is_counted():
    _v2()
    now = timezone.now()
    old = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
    AuthorRef.objects.create(account_id=old, occurred_at=now, registered_at=now - timedelta(days=3))
    unknown = "ffffffff-ffff-ffff-ffff-fffffffffff0"  # registered before feed kept the time
    post, author = "12121212-1212-1212-1212-121212121212", "13131313-1313-1313-1313-131313131313"
    assert _react(post, old, author, now) == 1
    assert _react(post, unknown, author, now) == 1
    assert PostStats.objects.get(post_id=post).reactions == 2


def test_a_reaction_burst_is_excluded_from_rates():
    _v2()
    burst = config.for_surface("home").get("integrity.suspect_burst_per_min")
    reactor, author = "14141414-1414-1414-1414-141414141414", "15151515-1515-1515-1515-151515151515"
    now = timezone.now()
    import uuid

    posts = [str(uuid.uuid4()) for _ in range(burst + 5)]
    counted = sum(
        _react(p, reactor, author, now + timedelta(milliseconds=100 * i))
        for i, p in enumerate(posts)
    )
    assert counted == burst
    assert ReactionState.objects.filter(reactor_id=reactor, suspect=True).count() == 5
    # A minute later the same account counts again.
    later = str(uuid.uuid4())
    assert _react(later, reactor, author, now + timedelta(minutes=2)) == 1


def test_account_registered_is_kept_once():
    import uuid

    from tara_events.envelope import EventEnvelope

    account = str(uuid.uuid4())
    first = timezone.now() - timedelta(hours=1)
    env = EventEnvelope(
        event_type="account.registered",
        subject_id=account,
        producer="identity-service",
        payload={"email_verified": True, "language": "ar", "display_name": "x", "handle": "x"},
        occurred_at=first.isoformat(),
    )
    deliver(env, only_intel=True)
    deliver(env, only_intel=True)
    assert AuthorRef.objects.get(account_id=account).registered_at == first
