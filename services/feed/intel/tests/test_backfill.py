"""WP 3.2: backfills from the owners' paged exports, with fixtures in place of HTTP.

They write through the event writers (newest-wins at the export's ``as_of``), resume
from a cursor, and, after a complete scan, switch off what the owner no longer has.
"""

import io
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from django.core.management import call_command
from feed.models import AuthorRef, FollowEdge

from intel import backfill, readmodels
from intel.models import (
    BlockPair,
    ContentRef,
    FriendEdge,
    GroupMembership,
    GroupRef,
    PageRef,
)

pytestmark = pytest.mark.django_db
AS_OF = datetime(2026, 11, 5, 15, 51, tzinfo=UTC)


def uid():
    return str(uuid.uuid4())


def fake(pages_by_cursor, as_of=AS_OF, calls=None):
    """``fetch`` serving ``{cursor: (items, next)}``."""

    def fetch(src, *, after, limit, timeout):
        if calls is not None:
            calls.append((src.service, src.path, after, limit))
        items, nxt = pages_by_cursor[after]
        return backfill.Page(as_of, [{"id": i["_id"], "payload": i} for i in items], nxt)

    return fetch


def post_item(**kw):
    post_id = uid()
    return {
        "_id": post_id,
        "post_id": post_id,
        "author_id": uid(),
        "author_type": "user",
        "type": "text",
        "audience": "public",
        "excerpt": "مرحبا بكم جميعا في صفحتنا الجديدة",
        "media_ids": [],
        "hashtags": ["news"],
        "shared_post_id": None,
        "created_at": (AS_OF - timedelta(days=1)).isoformat(),
        "group_id": None,
        "approval_state": "approved",
        "removed": False,
        "held": False,
        "reel_state": None,
        "moderation_open": False,
        "open_reports": 0,
        **kw,
    }


def test_sources_name_the_owner_and_its_internal_audience(settings):
    settings.GRAPH_INTERNAL_URL = "http://graph:8000"
    src = backfill.source("follows")
    assert (src.service, src.audience, src.path) == (
        "graph",
        "graph-internal",
        "intel/export/follows/",
    )
    assert backfill.source("posts").audience == "post-internal"
    assert backfill.source("pages").audience == "profile-internal"


def test_posts_backfill_pages_through_and_writes_the_current_state():
    live, held, removed = post_item(), post_item(held=True), post_item(removed=True)
    reel = post_item(type="reel", reel_state="media_missing")
    review = post_item(moderation_open=True, open_reports=4)
    calls = []
    fetch = fake({None: ([live, held], "c1"), "c1": ([removed, reel, review], None)}, calls=calls)
    result = backfill.run("posts", fetch=fetch, rate=0)
    assert (result.items, result.pages, result.complete) == (5, 2, True)
    assert [c[2] for c in calls] == [None, "c1"]
    rows = {str(r.post_id): r for r in ContentRef.objects.all()}
    assert rows[live["post_id"]].state == "live"
    assert rows[live["post_id"]].lang == "ar"
    assert rows[held["post_id"]].state == "hidden"
    assert (rows[removed["post_id"]].state, rows[removed["post_id"]].moderation_state) == (
        "deleted",
        "removed",
    )
    assert rows[reel["post_id"]].reel_state == "media_missing"
    r = rows[review["post_id"]]
    assert (r.moderation_open, r.pending_reports, r.moderation_state) == (True, 4, "pending")


def test_a_newer_event_wins_over_the_backfill():
    item = post_item()
    readmodels.content_deleted(item["post_id"], AS_OF + timedelta(minutes=1))
    backfill.run("posts", fetch=fake({None: ([item], None)}), rate=0)
    assert ContentRef.objects.get(post_id=item["post_id"]).state == "deleted"


def test_a_complete_scan_sweeps_posts_the_owner_no_longer_has():
    kept, gone = post_item(), uid()
    readmodels.content_created(
        {"post_id": gone, "author_id": uid(), "audience": "public"}, AS_OF - timedelta(days=2)
    )
    result = backfill.run("posts", fetch=fake({None: ([kept], None)}), rate=0)
    assert result.swept == 1
    assert ContentRef.objects.get(post_id=gone).state == "deleted"
    assert ContentRef.objects.get(post_id=kept["post_id"]).state == "live"


def test_a_resumed_scan_never_sweeps():
    gone = uid()
    readmodels.content_created(
        {"post_id": gone, "author_id": uid(), "audience": "public"}, AS_OF - timedelta(days=2)
    )
    result = backfill.run("posts", after="c1", fetch=fake({"c1": ([post_item()], None)}), rate=0)
    assert result.swept == 0
    assert ContentRef.objects.get(post_id=gone).state == "live"


def test_edges_backfill_fixes_the_follow_edge_drift():
    """D6: follows made before feed consumed the events, and follows that ended while
    their event was lost."""
    a, b, c, page = uid(), uid(), uid(), uid()
    FollowEdge.objects.create(follower_id=a, target_id=c, occurred_at=AS_OF - timedelta(days=9))
    follows = [
        {"_id": 1, "follower": a, "target": b, "target_type": "user"},
        {"_id": 2, "follower": b, "target": page, "target_type": "page"},
    ]
    backfill.run("follows", fetch=fake({None: (follows, None)}), rate=0)
    active = set(FollowEdge.objects.filter(active=True).values_list("follower_id", "target_id"))
    assert {(str(x), str(y)) for x, y in active} == {(a, b), (b, page)}
    assert FollowEdge.objects.get(target_id=page).target_type == "page"
    assert FollowEdge.objects.get(follower_id=a, target_id=c).active is False


def test_friendships_are_stored_both_ways_and_ended_ones_swept():
    a, b, c = uid(), uid(), uid()
    readmodels.set_friendship(a, c, True, AS_OF - timedelta(days=3))
    items = [{"_id": 1, "a": a, "b": b, "accepted_at": (AS_OF - timedelta(days=5)).isoformat()}]
    backfill.run("friendships", fetch=fake({None: (items, None)}), rate=0)
    assert FriendEdge.objects.filter(active=True).count() == 2
    assert FriendEdge.objects.get(account_id=a, friend_id=b).since == AS_OF - timedelta(days=5)
    assert not FriendEdge.objects.filter(active=True, friend_id=c).exists()


def test_blocks_backfill_and_sweep_keep_each_direction():
    a, b, c = uid(), uid(), uid()
    readmodels.set_block(c, a, True, AS_OF - timedelta(days=2))  # lifted while unseen
    items = [{"_id": 1, "blocker_id": a, "blocked_id": b}]
    backfill.run("blocks", fetch=fake({None: (items, None)}), rate=0)
    ab = BlockPair.objects.get(low=min(a, b), high=max(a, b))
    assert (ab.low_blocks if a < b else ab.high_blocks) is True
    ac = BlockPair.objects.get(low=min(a, c), high=max(a, c))
    assert not (ac.low_blocks or ac.high_blocks)


def test_groups_members_and_pages():
    g, member, page, owner = uid(), uid(), uid(), uid()
    stale = uid()
    readmodels.set_group({"group_id": stale, "privacy": "public"}, AS_OF - timedelta(days=1))
    backfill.run(
        "groups",
        fetch=fake(
            {
                None: (
                    [
                        {
                            "_id": g,
                            "group_id": g,
                            "privacy": "private",
                            "status": "active",
                            "category": "food",
                            "member_count": 4,
                        }
                    ],
                    None,
                )
            }
        ),
        rate=0,
    )
    assert GroupRef.objects.get(group_id=g).privacy == "private"
    assert GroupRef.objects.get(group_id=stale).status == "deleted"
    backfill.run(
        "group-members",
        fetch=fake(
            {
                None: (
                    [
                        {
                            "_id": 1,
                            "group_id": g,
                            "account_id": member,
                            "role": "member",
                            "state": "active",
                            "notify_posts": True,
                            "joined_at": (AS_OF - timedelta(days=4)).isoformat(),
                        }
                    ],
                    None,
                )
            }
        ),
        rate=0,
    )
    m = GroupMembership.objects.get(group_id=g, account_id=member)
    assert (m.state, m.notify_posts, m.joined_at) == ("active", True, AS_OF - timedelta(days=4))
    backfill.run(
        "pages",
        fetch=fake(
            {None: ([{"_id": page, "owner": owner, "status": "draft", "deleted": False}], None)}
        ),
        rate=0,
    )
    assert PageRef.objects.get(page_id=page).status == "draft"
    assert AuthorRef.objects.get(account_id=page).kind == "page"


def test_the_backfill_is_idempotent():
    item = post_item()
    for _ in range(2):
        backfill.run("posts", fetch=fake({None: ([item], None)}), rate=0)
    assert ContentRef.objects.count() == 1


def test_commands_run_each_kind_and_print_json(monkeypatch):
    seen = []

    def run(kind, **kw):
        seen.append((kind, kw["after"], kw["sweep"]))
        return backfill.Result(kind, items=1, complete=True)

    monkeypatch.setattr(backfill, "run", run)
    out = io.StringIO()
    call_command("intel_backfill_edges", stdout=out)
    assert [s[0] for s in seen] == ["friendships", "follows", "blocks"]
    assert out.getvalue().count('"complete": true') == 3
    seen.clear()
    call_command("intel_backfill_content", "--after", "x", "--no-sweep", stdout=io.StringIO())
    assert seen == [("posts", "x", False)]
    for name, kinds in (
        ("intel_backfill_groups", ["groups", "group-members"]),
        ("intel_backfill_pages", ["pages"]),
    ):
        seen.clear()
        call_command(name, stdout=io.StringIO())
        assert [s[0] for s in seen] == kinds


def test_the_rate_limit_spaces_requests(monkeypatch):
    sleeps = []
    monkeypatch.setattr(backfill.time, "sleep", sleeps.append)
    fetch = fake({None: ([], "a"), "a": ([], "b"), "b": ([], None)})
    list(backfill.pages(backfill.source("posts"), rate=20, fetch=fetch))
    assert len(sleeps) == 2 and all(0 < s <= 0.05 for s in sleeps)


# ---- accounts (identity's export of the accounts that are not active; rule E6) ----


def account_item(**kw):
    account_id = uid()
    return {"_id": account_id, "account_id": account_id, **kw}


def test_accounts_source_is_identity():
    src = backfill.source("accounts")
    assert (src.service, src.audience, src.path) == (
        "identity",
        "identity-internal",
        "intel/export/accounts/",
    )


def test_accounts_backfill_marks_listed_authors_inactive_with_both_flags_apart():
    suspended = account_item(deactivated=False, suspended=True)
    both = account_item(deactivated=True, suspended=True)
    backfill.run("accounts", fetch=fake({None: ([suspended, both], None)}), rate=0)
    s = AuthorRef.objects.get(account_id=suspended["account_id"])
    assert (s.suspended, s.deactivated, s.active) == (True, False, False)
    b = AuthorRef.objects.get(account_id=both["account_id"])
    assert (b.suspended, b.deactivated, b.active) == (True, True, False)
    # lifting the suspension leaves the deactivation standing
    from intel import ports

    ports.set_author_lifecycle(both["account_id"], "suspended", False, AS_OF + timedelta(hours=1))
    assert AuthorRef.objects.get(account_id=both["account_id"]).active is False


def test_a_newer_lifecycle_event_wins_over_the_accounts_backfill():
    from intel import ports

    item = account_item(deactivated=False, suspended=True)
    ports.set_author_lifecycle(item["account_id"], "suspended", False, AS_OF + timedelta(minutes=1))
    backfill.run("accounts", fetch=fake({None: ([item], None)}), rate=0)
    assert AuthorRef.objects.get(account_id=item["account_id"]).active is True


def test_a_complete_accounts_scan_reactivates_unlisted_authors_only_when_older():
    from intel import ports

    lost, recent = uid(), uid()
    ports.set_author_lifecycle(lost, "deactivated", True, AS_OF - timedelta(days=1))
    ports.set_author_lifecycle(recent, "suspended", True, AS_OF + timedelta(minutes=1))
    result = backfill.run("accounts", fetch=fake({None: ([], None)}), rate=0)
    assert result.swept == 1
    assert AuthorRef.objects.get(account_id=lost).active is True
    assert AuthorRef.objects.get(account_id=recent).active is False
    # a resumed scan never sweeps
    ports.set_author_lifecycle(lost, "deactivated", True, AS_OF + timedelta(hours=1))
    backfill.run("accounts", after="x", fetch=fake({"x": ([], None)}), rate=0)
    assert AuthorRef.objects.get(account_id=lost).active is False


def test_accounts_command_runs_the_accounts_kind(monkeypatch):
    seen = []

    def run(kind, **kw):
        seen.append(kind)
        return backfill.Result(kind, complete=True)

    monkeypatch.setattr(backfill, "run", run)
    call_command("intel_backfill_accounts", stdout=io.StringIO())
    assert seen == ["accounts", "restrictions"]


# ---- restrictions (moderation's standing user restrict / shadow; rule E11) --------


def restriction_item(action="restrict", account_id=None):
    case_id = uid()
    return {"_id": case_id, "account_id": account_id or uid(), "action": action, "case_id": case_id}


def test_restrictions_source_is_moderation():
    src = backfill.source("restrictions")
    assert (src.service, src.audience, src.path) == (
        "moderation",
        "moderation-internal",
        "intel/export/restrictions/",
    )


def test_restrictions_backfill_and_sweep():
    from intel.models import AccountRestriction

    shadowed = restriction_item("shadow")
    odd = restriction_item("warn")  # not a restriction: ignored
    lifted, recent = uid(), uid()
    readmodels.set_restriction(lifted, "restrict", uid(), True, AS_OF - timedelta(days=1))
    readmodels.set_restriction(recent, "shadow", uid(), True, AS_OF + timedelta(minutes=1))

    result = backfill.run("restrictions", fetch=fake({None: ([shadowed, odd], None)}), rate=0)

    row = AccountRestriction.objects.get(account_id=shadowed["account_id"])
    assert (row.kind, row.active, str(row.case_id)) == ("shadow", True, shadowed["case_id"])
    assert not AccountRestriction.objects.filter(account_id=odd["account_id"]).exists()
    assert result.swept == 1
    assert AccountRestriction.objects.get(account_id=lifted).active is False
    assert AccountRestriction.objects.get(account_id=recent).active is True


def test_a_newer_reinstate_wins_over_the_restrictions_backfill():
    from intel.models import AccountRestriction

    item = restriction_item()
    readmodels.set_restriction(item["account_id"], "", None, False, AS_OF + timedelta(minutes=1))
    backfill.run("restrictions", fetch=fake({None: ([item], None)}), rate=0)
    assert AccountRestriction.objects.get(account_id=item["account_id"]).active is False
