"""WP 3.5: eligibility rules E1 to E11, one test per rule, each counted per rule and
fail closed for privacy. The property test is in ``test_eligibility_property.py``."""

from datetime import timedelta

import pytest
from django.utils import timezone
from feed.models import AuthorSnooze

from intel import config, eligibility, metrics
from intel.eligibility import Viewer
from intel.retrieval import Candidate

from . import world as w

pytestmark = pytest.mark.django_db
HOME = config.for_surface("home")
ADULT = {"is_minor": False, "age_band": "25-34"}


def cand(post_id, author, source="follow_pull", reason="x", type="text"):  # noqa: A002
    return Candidate(post_id, author, source, reason, w.NOW, type)


def run(viewer, *cands, cfg=HOME, **kw):
    v = Viewer(viewer, **{**ADULT, **kw})
    return eligibility.filter(v, list(cands), cfg)


def kept(viewer, *cands, **kw):
    return {c.post_id for c in run(viewer, *cands, **kw).kept}


def dropped_by(viewer, c, **kw):
    result = run(viewer, c, **kw)
    assert not result.kept, "expected a drop"
    return set(result.dropped)


# ---- E1: live --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fields", [{"state": "deleted"}, {"state": "hidden"}, {"moderation": "removed"}]
)
def test_e1_dead_content_is_dropped_everywhere(fields):
    viewer, author = w.uid(), w.uid()
    p = w.post(author, **fields)
    for source in ("connections", "follow_pull", "video"):
        assert dropped_by(viewer, cand(p, author, source)) == {"E1"}


def test_e1_an_unknown_pulled_post_is_dropped_but_a_fan_out_row_is_not():
    viewer, author, unknown = w.uid(), w.uid(), w.uid()
    assert dropped_by(viewer, cand(unknown, author, "follow_pull")) == {"E1"}
    assert dropped_by(viewer, cand(unknown, author, "reels", type="reel")) == {"E1"}
    assert kept(viewer, cand(unknown, author, "connections")) == {unknown}


# ---- E1b: group approval ------------------------------------------------------------------


def test_e1b_a_pending_group_post_reaches_no_member_through_any_source():
    viewer, author = w.uid(), w.uid()
    g = w.group(privacy="public")
    w.member(viewer, g, role="admin")  # even staff: they review it in the queue
    p = w.post(author, audience="group", group=g, approval="pending")
    for source in ("groups", "follow_pull", "connections"):
        assert dropped_by(viewer, cand(p, author, source)) == {"E1b"}
    # the author keeps their own fan-out row
    w.member(author, g)
    assert kept(author, cand(p, author, "connections")) == {p}


def test_e1b_a_group_post_with_no_known_approval_is_dropped():
    viewer, author = w.uid(), w.uid()
    g = w.group()
    w.member(viewer, g)
    p = w.post(author, audience="group", group=g, approval="")
    assert dropped_by(viewer, cand(p, author, "groups")) == {"E1b"}


# ---- E1c: reel playability ----------------------------------------------------------------


@pytest.mark.parametrize("state", ["media_missing", "media_failed", "media_elsewhere"])
def test_e1c_an_unplayable_reel_is_dropped_everywhere(state):
    viewer, author = w.uid(), w.uid()
    p = w.post(author, type="reel", reel_state=state)
    for source in ("connections", "reels", "follow_pull"):
        assert dropped_by(viewer, cand(p, author, source, type="reel")) == {"E1c"}
    published = w.post(author, type="reel")
    assert kept(viewer, cand(published, author, "reels", type="reel")) == {published}


# ---- E2: discovery audience --------------------------------------------------------------


@pytest.mark.parametrize("audience", ["friends", "followers", "only_me", ""])
def test_e2_discovery_needs_a_public_post(audience):
    viewer, author = w.uid(), w.uid()
    w.friends(viewer, author)  # even a friend: discovery is for public content only
    p = w.post(author, audience=audience, type="video")
    assert dropped_by(viewer, cand(p, author, "video", type="video")) == {"E2"}


@pytest.mark.parametrize(
    ("privacy", "status", "ok"),
    [
        ("public", "active", True),
        ("private", "active", False),
        ("hidden", "active", False),
        ("public", "suspended", False),
    ],
)
def test_e2_discovery_of_group_posts_needs_a_public_active_group(privacy, status, ok):
    viewer, author = w.uid(), w.uid()
    g = w.group(privacy=privacy, status=status)
    w.member(viewer, g)  # a member still does not "discover" a hidden group
    p = w.post(author, audience="group", group=g, type="video")
    result = run(viewer, cand(p, author, "video", type="video"))
    assert bool(result.kept) is ok
    if not ok:
        assert set(result.dropped) == {"E2"}


def test_e2_a_group_unknown_to_feed_is_never_discoverable():
    viewer, author = w.uid(), w.uid()
    p = w.post(author, audience="group", group=w.uid(), type="video")
    assert dropped_by(viewer, cand(p, author, "video", type="video")) == {"E2"}


# ---- E2b: pull audience ----------------------------------------------------------------


def test_e2b_pull_sources_follow_posts_audience_rule():
    viewer, friend, followed, stranger = w.uid(), w.uid(), w.uid(), w.uid()
    w.friends(viewer, friend)
    w.follow(viewer, followed)
    cases = {
        (friend, "friends"): True,
        (friend, "followers"): True,
        (friend, "only_me"): False,
        (followed, "followers"): True,
        (followed, "friends"): False,
        (followed, "public"): True,
        (stranger, "followers"): False,
        (stranger, "public"): True,
        (friend, ""): False,
        (friend, "group"): False,  # a group audience without a group
    }
    for (author, audience), ok in cases.items():
        p = w.post(author, audience=audience)
        result = run(viewer, cand(p, author, "follow_pull"))
        assert bool(result.kept) is ok, (audience, ok)
        if not ok:
            assert set(result.dropped) == {"E2b"}


def test_e2b_a_removed_friendship_is_not_a_friendship():
    viewer, author = w.uid(), w.uid()
    w.friends(viewer, author)
    from intel import readmodels

    readmodels.set_friendship(viewer, author, False, w.NOW)
    p = w.post(author, audience="friends")
    assert dropped_by(viewer, cand(p, author, "follow_pull")) == {"E2b"}


# ---- E3: group access ------------------------------------------------------------------


@pytest.mark.parametrize("privacy", ["private", "hidden"])
def test_e3_private_and_hidden_groups_need_an_active_membership(privacy):
    viewer, author = w.uid(), w.uid()
    g = w.group(privacy=privacy)
    p = w.post(author, audience="group", group=g)
    assert dropped_by(viewer, cand(p, author, "groups")) == {"E3"}
    w.member(viewer, g, state="requested")
    assert dropped_by(viewer, cand(p, author, "groups")) == {"E3"}
    w.member(viewer, g)
    assert kept(viewer, cand(p, author, "groups")) == {p}


def test_e3_banned_members_see_nothing_not_even_public_groups():
    viewer, author = w.uid(), w.uid()
    g = w.group(privacy="public")
    w.member(viewer, g, state="banned")
    p = w.post(author, audience="group", group=g)
    for source in ("groups", "connections", "follow_pull"):
        assert dropped_by(viewer, cand(p, author, source)) == {"E3"}


def test_e3_unknown_suspended_or_deleted_groups_are_dropped():
    viewer, author = w.uid(), w.uid()
    for g in (w.uid(), w.group(status="suspended"), w.group(status="deleted")):
        w.member(viewer, g)
        p = w.post(author, audience="group", group=g)
        assert dropped_by(viewer, cand(p, author, "groups")) == {"E3"}


def test_e3_a_non_member_blocked_with_a_public_groups_owner_sees_nothing():
    viewer, author, owner = w.uid(), w.uid(), w.uid()
    g = w.group(privacy="public", owner=owner)
    p = w.post(author, audience="group", group=g)
    assert kept(viewer, cand(p, author, "follow_pull")) == {p}
    w.block(owner, viewer)
    assert dropped_by(viewer, cand(p, author, "follow_pull")) == {"E3"}


# ---- E4: blocks ------------------------------------------------------------------------


@pytest.mark.parametrize("direction", ["viewer_blocks", "author_blocks"])
def test_e4_a_block_either_way_drops_from_every_source(direction):
    viewer, author = w.uid(), w.uid()
    if direction == "viewer_blocks":
        w.block(viewer, author)
    else:
        w.block(author, viewer)
    p = w.post(author)
    for source in ("connections", "follow_pull", "video"):
        assert dropped_by(viewer, cand(p, author, source)) == {"E4"}


def test_e4_a_block_with_the_owner_of_a_page_drops_its_posts():
    viewer, owner = w.uid(), w.uid()
    pg = w.page(owner)
    p = w.post(pg, author_type="page")
    assert kept(viewer, cand(p, pg, "follow_pull")) == {p}
    w.block(owner, viewer)
    assert dropped_by(viewer, cand(p, pg, "follow_pull")) == {"E4"}


def test_e4_an_unblock_lifts_it():
    viewer, author = w.uid(), w.uid()
    w.block(viewer, author)
    from intel import readmodels

    readmodels.set_block(viewer, author, False, w.NOW)
    p = w.post(author)
    assert kept(viewer, cand(p, author)) == {p}


# ---- E5: hides, snoozes, mutes ----------------------------------------------------------


def test_e5_hidden_posts_and_snoozed_or_muted_authors_are_dropped():
    viewer, a, b, c = w.uid(), w.uid(), w.uid(), w.uid()
    hidden = w.post(a)
    w.hide(viewer, hidden, a)
    snoozed = w.post(b)
    AuthorSnooze.objects.create(
        account_id=viewer,
        author_id=b,
        until=timezone.now() + timedelta(days=1),
        snoozed_at=timezone.now(),
    )
    muted = w.post(c)
    w.mute(viewer, c)
    for p, author in ((hidden, a), (snoozed, b), (muted, c)):
        assert dropped_by(viewer, cand(p, author, "follow_pull")) == {"E5"}


# ---- E6: author active and discoverable ------------------------------------------------


def test_e6_inactive_authors_are_dropped_outside_connections():
    viewer, author = w.uid(), w.uid()
    w.author(author, active=False)
    p = w.post(author)
    for source in ("follow_pull", "video"):
        assert dropped_by(viewer, cand(p, author, source)) == {"E6"}
    assert kept(viewer, cand(p, author, "connections")) == {p}


def test_e6_non_searchable_authors_are_not_discovered_but_still_pulled():
    viewer, author = w.uid(), w.uid()
    w.author(author, searchable=False)
    p = w.post(author, type="video")
    assert dropped_by(viewer, cand(p, author, "video", type="video")) == {"E6"}
    assert kept(viewer, cand(p, author, "follow_pull")) == {p}


# ---- E6b: page status ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "deleted"), [("draft", False), ("suspended", False), ("published", True)]
)
def test_e6b_posts_of_unpublished_or_deleted_pages_are_dropped_everywhere(status, deleted):
    viewer, owner = w.uid(), w.uid()
    pg = w.page(owner, status=status, deleted=deleted)
    p = w.post(pg, author_type="page")
    for source in ("connections", "follow_pull", "video"):
        assert dropped_by(viewer, cand(p, pg, source)) == {"E6b"}


def test_e6b_a_page_unknown_to_feed_is_dropped():
    viewer, pg = w.uid(), w.uid()
    p = w.post(pg, author_type="page")
    assert dropped_by(viewer, cand(p, pg, "follow_pull")) == {"E6b"}


# ---- E7: pending integrity -----------------------------------------------------------------


def test_e7_posts_under_review_are_not_discovered_but_stay_in_connections():
    viewer, author = w.uid(), w.uid()
    reported = w.post(author, type="video", pending_reports=3, moderation_open=True)
    open_case = w.post(author, type="video", moderation="pending", moderation_open=True)
    few = w.post(author, type="video", pending_reports=2)
    for p in (reported, open_case):
        assert dropped_by(viewer, cand(p, author, "video", type="video")) == {"E7"}
        assert kept(viewer, cand(p, author, "connections")) == {p}
    assert kept(viewer, cand(few, author, "video", type="video")) == {few}
    cfg = config.for_surface("home", {"integrity": {"pending_report_min_reporters": 2}})
    assert not kept(viewer, cand(few, author, "video", type="video"), cfg=cfg)


# ---- E8: explicit dislikes ---------------------------------------------------------------


def test_e8_a_disliked_creator_is_not_recommended():
    viewer, author = w.uid(), w.uid()
    w.hide(viewer, w.post(author), author, reason="dislike_creator")
    p = w.post(author, type="video")
    assert dropped_by(viewer, cand(p, author, "video", type="video")) == {"E8"}


# ---- E9: age ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "claims",
    [
        {"is_minor": True, "age_band": "13-17"},
        {"is_minor": False, "age_band": "unknown"},
        {"is_minor": None, "age_band": None},
    ],
)
def test_e9_minor_and_unknown_age_viewers_get_no_unlisted_discovery(claims):
    viewer, author = w.uid(), w.uid()
    p = w.post(author, type="video")
    assert dropped_by(viewer, cand(p, author, "video", type="video"), **claims) == {"E9"}
    # connections and pulls are not discovery
    assert kept(viewer, cand(p, author, "follow_pull"), **claims) == {p}


def test_e9_allow_listed_topics_on_pages_reach_limited_viewers():
    viewer, owner = w.uid(), w.uid()
    pg = w.page(owner)
    p = w.post(pg, author_type="page", type="video")
    v = Viewer(viewer, is_minor=True, age_band="13-17")
    cfg = config.for_surface("home", {"eligibility": {"minor_allowed_topics": [7]}})
    c = cand(p, pg, "video", type="video")
    ctx = eligibility.load_context(v, [c], cfg)
    assert eligibility.evaluate(c, ctx) == "E9"
    ctx.topics = {p: {7}}  # topics arrive in phase 6
    assert eligibility.evaluate(c, ctx) is None


# ---- E9b: the author's age (WP 4b.14) ----------------------------------------------------


@pytest.mark.parametrize("age_class", ["minor", "unknown", None])
@pytest.mark.parametrize("source", ["discovery", "reels", "video"])
def test_e9b_minor_or_unknown_user_authors_never_reach_strangers(age_class, source):
    viewer, author = w.uid(), w.uid()
    kind = {"reels": "reel", "video": "video"}.get(source, "text")
    p = w.post(author, type=kind, author_age=age_class)
    assert dropped_by(viewer, cand(p, author, source, type=kind)) == {"E9b"}


@pytest.mark.parametrize("source", ["connections", "follow_pull", "groups"])
def test_e9b_leaves_friends_and_followers_untouched(source):
    viewer, author = w.uid(), w.uid()
    g = None
    if source == "groups":
        g = w.group()
        w.member(viewer, g)
    p = w.post(author, author_age="minor", group=g, audience="group" if g else "public")
    assert kept(viewer, cand(p, author, source)) == {p}


def test_e9b_pages_carry_no_age_and_are_not_excluded():
    viewer, owner = w.uid(), w.uid()
    pg = w.page(owner)
    p = w.post(pg, author_type="page")
    assert kept(viewer, cand(p, pg, "discovery", reason="rec_popular")) == {p}


def test_e9b_an_adult_author_is_discovered_and_the_rule_is_re_checked_between_pages():
    viewer, author = w.uid(), w.uid()
    p = w.post(author, author_age="adult")
    c = cand(p, author, "discovery", reason="rec_fresh")
    assert kept(viewer, c) == {p}
    v = Viewer(viewer, **ADULT)
    assert [k.post_id for k in eligibility.recheck(v, [c], HOME).kept] == [p]
    w.author(author, age_class="minor")  # the author's own token said minor since
    result = eligibility.recheck(v, [c], HOME)
    assert result.kept == [] and dict(result.dropped) == {"E9b": 1}


# ---- E10: languages ---------------------------------------------------------------------


def test_e10_recommended_content_is_in_the_viewers_languages():
    viewer, author = w.uid(), w.uid()
    en = w.post(author, type="video", lang="en")
    und = w.post(author, type="video", lang="und")
    langs = frozenset({"ar"})
    assert dropped_by(viewer, cand(en, author, "video", type="video"), languages=langs) == {"E10"}
    assert kept(viewer, cand(und, author, "video", type="video"), languages=langs) == {und}
    assert kept(
        viewer, cand(en, author, "video", type="video"), languages=langs, other_languages=True
    ) == {en}
    assert kept(viewer, cand(en, author, "follow_pull"), languages=langs) == {en}


# ---- E11: account restriction -----------------------------------------------------------


@pytest.mark.parametrize("kind", ["restrict", "shadow"])
def test_e11_restricted_accounts_reach_no_stranger_but_keep_connections(kind):
    viewer, author = w.uid(), w.uid()
    w.restrict(author, kind)
    p = w.post(author, type="video")
    assert dropped_by(viewer, cand(p, author, "video", type="video")) == {"E11"}
    assert kept(viewer, cand(p, author, "connections")) == {p}
    assert kept(viewer, cand(p, author, "follow_pull")) == {p}


def test_e11_a_restricted_owners_page_is_not_discovered():
    viewer, owner = w.uid(), w.uid()
    pg = w.page(owner)
    w.restrict(owner, "restrict")
    p = w.post(pg, author_type="page", type="video")
    assert dropped_by(viewer, cand(p, pg, "video", type="video")) == {"E11"}


# ---- the filter -----------------------------------------------------------------------------


def test_an_unknown_source_is_never_eligible():
    viewer, author = w.uid(), w.uid()
    p = w.post(author)
    assert dropped_by(viewer, cand(p, author, "made_up")) == {"E0"}


def test_drops_are_counted_per_rule(monkeypatch):
    seen = []
    monkeypatch.setattr(metrics, "eligibility_dropped", lambda rule, n=1: seen.append((rule, n)))
    viewer, author = w.uid(), w.uid()
    w.block(viewer, author)
    a, b = w.post(author), w.post(author)
    gone = w.post(w.uid(), state="deleted")
    result = run(viewer, cand(a, author), cand(b, author), cand(gone, author))
    assert result.dropped == {"E4": 2, "E1": 1}
    assert sorted(seen) == [("E1", 1), ("E4", 2)]


def test_the_counter_is_registered():
    if metrics.ELIGIBILITY_DROPS is None:
        pytest.skip("prometheus_client not installed")
    metrics.eligibility_dropped("E4", 2)
    assert metrics.ELIGIBILITY_DROPS.labels(rule="E4")._value.get() >= 2


def test_every_rule_has_a_function_and_the_rule_set_is_complete():
    assert eligibility.RULE_NAMES == (
        "E1",
        "E1b",
        "E1c",
        "E2",
        "E2b",
        "E3",
        "E4",
        "E5",
        "E6",
        "E6b",
        "E7",
        "E8",
        "E9",
        "E9b",
        "E10",
        "E11",
        "E12",
    )


def test_a_fixed_number_of_queries_whatever_the_candidate_count(django_assert_max_num_queries):
    viewer = w.uid()
    cands = []
    for _ in range(60):
        author = w.uid()
        cands.append(cand(w.post(author), author))
    with django_assert_max_num_queries(16):
        eligibility.filter(Viewer(viewer, **ADULT), cands, HOME)
