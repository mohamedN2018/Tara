"""WP 3.5 property test: for random synthetic worlds, no id that retrieval plus
eligibility returns is unauthorized, according to a reference oracle that implements
post's ``visible_to_viewer`` (``posts/services.py:96-190``).

Each world mixes blocks both ways, public, private and hidden groups (suspended and
deleted too), banned and pending members, pending group posts, draft, suspended and
deleted pages, unplayable reels, restricted and shadowed authors, friends-only,
followers-only and ``only_me`` posts reached through **every pull source** (capped
fan-outs, new follows and new friends, groups), deactivated authors, removed posts,
and minor or unknown-age viewers. Every account is checked as the viewer on every
surface.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import timedelta

import pytest
from django.db import transaction
from feed.models import AuthorRef, FeedItem, FollowEdge
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from intel import config, eligibility, readmodels, retrieval
from intel.eligibility import DISCOVERY, Viewer
from intel.models import (
    AccountRestriction,
    ContentRef,
    FanoutCapped,
    GroupMembership,
    GroupRef,
    PageRef,
)
from intel.retrieval import Candidate

from .world import NOW

pytestmark = pytest.mark.django_db

USERS = 5
SURFACES = ("home", "reels", "video", "groups")
STAFF = {"owner", "admin", "moderator"}


def _id(kind: int, i: int) -> str:
    return str(uuid.UUID(int=(kind << 64) | (i + 1)))


# ---- the world ------------------------------------------------------------------------


@dataclass
class World:
    users: list[str]
    active: dict[str, bool]
    searchable: dict[str, bool]
    limited: dict[str, bool]
    friends: set[frozenset]
    new_friends: set[frozenset]
    follows: set[tuple[str, str]]
    new_follows: set[tuple[str, str]]
    blocks: set[tuple[str, str]]
    restricted: dict[str, str]
    pages: dict[str, dict]
    groups: dict[str, dict]
    members: dict[tuple[str, str], dict]
    posts: list[dict] = field(default_factory=list)

    def blocked(self, a: str, b: str) -> bool:
        return (a, b) in self.blocks or (b, a) in self.blocks

    def are_friends(self, a: str, b: str) -> bool:
        return frozenset((a, b)) in self.friends


@st.composite
def worlds(draw):
    users = [_id(1, i) for i in range(USERS)]
    pairs = [(a, b) for a in users for b in users if a < b]
    ordered = [(a, b) for a in users for b in users if a != b]
    friends = {frozenset(p) for p in pairs if draw(st.booleans())}
    new_friends = {f for f in friends if draw(st.integers(0, 3)) == 0}
    blocks = {p for p in ordered if draw(st.integers(0, 5)) == 0}

    pages = {}
    for i in range(draw(st.integers(0, 2))):
        pages[_id(2, i)] = {
            "owner": draw(st.sampled_from(users)),
            "status": draw(st.sampled_from(["published", "published", "draft", "suspended"])),
            "deleted": draw(st.integers(0, 4)) == 0,
        }
    targets = users + list(pages)
    follows = {(a, t) for a in users for t in targets if a != t and draw(st.integers(0, 2)) == 0}
    new_follows = {f for f in follows if draw(st.integers(0, 2)) == 0}

    groups, members = {}, {}
    for i in range(draw(st.integers(0, 2))):
        g = _id(3, i)
        groups[g] = {
            "privacy": draw(st.sampled_from(["public", "private", "hidden"])),
            "status": draw(st.sampled_from(["active", "active", "active", "suspended", "deleted"])),
        }
        for u in users:
            state = draw(st.sampled_from(["", "", "active", "active", "banned", "requested"]))
            if state:
                role = draw(st.sampled_from(["member", "member", "owner", "admin"]))
                members[(u, g)] = {"state": state, "role": role}

    world = World(
        users=users,
        active={u: draw(st.integers(0, 5)) != 0 for u in users},
        searchable={u: draw(st.integers(0, 4)) != 0 for u in users},
        limited={u: draw(st.integers(0, 3)) == 0 for u in users},
        friends=friends,
        new_friends=new_friends,
        follows=follows,
        new_follows=new_follows,
        blocks=blocks,
        restricted={
            u: draw(st.sampled_from(["restrict", "shadow"]))
            for u in users
            if draw(st.integers(0, 4)) == 0
        },
        pages=pages,
        groups=groups,
        members=members,
    )

    for i in range(draw(st.integers(1, 12))):
        as_page = bool(pages) and draw(st.integers(0, 3)) == 0
        author = draw(st.sampled_from(sorted(pages))) if as_page else draw(st.sampled_from(users))
        in_group = bool(groups) and not as_page and draw(st.integers(0, 2)) == 0
        kind = draw(st.sampled_from(["text", "video", "reel"]))
        world.posts.append(
            {
                "post_id": _id(4, i),
                "author": author,
                "author_type": "page" if as_page else "user",
                "group": draw(st.sampled_from(sorted(groups))) if in_group else None,
                "audience": "group"
                if in_group
                else draw(st.sampled_from(["public", "public", "friends", "followers", "only_me"])),
                "approval": draw(st.sampled_from(["approved", "approved", "pending"]))
                if in_group
                else "approved",
                "type": kind,
                "reel_state": draw(
                    st.sampled_from(["published", "published", "media_missing", "media_failed"])
                )
                if kind == "reel"
                else "",
                "deleted": draw(st.integers(0, 6)) == 0,
                "moderation": draw(st.sampled_from(["ok", "ok", "ok", "pending", "removed"])),
                "reports": draw(st.integers(0, 4)),
                "hours": draw(st.integers(1, 24 * 6)),
                "capped": draw(st.booleans()),
            }
        )
    return world


def _store(world: World) -> None:
    long_ago = NOW - timedelta(days=30)
    recent = NOW - timedelta(hours=1)
    for u in world.users:
        AuthorRef.objects.create(
            account_id=u,
            occurred_at=long_ago,
            active=world.active[u],
            deactivated=not world.active[u],
            searchable=world.searchable[u],
        )
    for f in world.friends:
        a, b = sorted(f)
        since = recent if f in world.new_friends else long_ago
        readmodels.set_friendship(a, b, True, since, since=since)
    for follower, target in world.follows:
        FollowEdge.objects.create(
            follower_id=follower,
            target_id=target,
            target_type="page" if target in world.pages else "user",
            occurred_at=recent if (follower, target) in world.new_follows else long_ago,
        )
    for blocker, blocked in world.blocks:
        readmodels.set_block(blocker, blocked, True, long_ago)
    for u, kind in world.restricted.items():
        AccountRestriction.objects.create(
            account_id=u, kind=kind, active=True, since=long_ago, event_at=long_ago
        )
    for page_id, p in world.pages.items():
        PageRef.objects.create(
            page_id=page_id,
            owner_id=p["owner"],
            status=p["status"],
            deleted=p["deleted"],
            event_at=long_ago,
        )
        AuthorRef.objects.create(account_id=page_id, occurred_at=long_ago, kind="page")
    for g, attrs in world.groups.items():
        GroupRef.objects.create(group_id=g, event_at=long_ago, **attrs)
    for (u, g), m in world.members.items():
        GroupMembership.objects.create(
            account_id=u, group_id=g, state=m["state"], role=m["role"], event_at=long_ago
        )
    for p in world.posts:
        held = p["author_type"] == "user" and not world.active[p["author"]]
        created = NOW - timedelta(hours=p["hours"])
        ContentRef.objects.create(
            post_id=p["post_id"],
            author_id=p["author"],
            author_type=p["author_type"],
            type=p["type"],
            audience=p["audience"],
            group_id=p["group"],
            approval_state=p["approval"],
            reel_state=p["reel_state"],
            state="deleted" if p["deleted"] else ("hidden" if held else "live"),
            held=held,
            moderation_state=p["moderation"],
            moderation_open=p["moderation"] == "pending",
            pending_reports=p["reports"],
            created_at=created,
            event_at=created,
        )
        if p["deleted"]:
            continue  # feed's remove_post drops the fan-out rows of a deleted post
        recipients = _fan_out(world, p)
        if p["capped"] and len(recipients) > 1:
            recipients = recipients[:1]  # the author's own row only
            FanoutCapped.objects.create(
                post_id=p["post_id"],
                author_id=p["author"],
                audience=p["audience"],
                total=5,
                cap=1,
                created_at=created,
            )
        FeedItem.objects.bulk_create(
            [
                FeedItem(
                    recipient_id=r,
                    post_id=p["post_id"],
                    author_id=p["author"],
                    reason=reason,
                    snapshot={"type": p["type"]},
                    post_created_at=created,
                )
                for r, reason in recipients
            ]
        )


def _fan_out(world: World, p: dict) -> list[tuple[str, str]]:
    """feed's ``_recipients`` at publish time: author, friends, followers. Blocks made
    after the fan-out are not applied here: eligibility (E4) has to catch them."""
    author, audience = p["author"], p["audience"]
    out = [(author, "self")]
    if p["group"] is not None or audience == "only_me":
        return out
    friends = {u for u in world.users if u != author and world.are_friends(u, author)}
    out += [(u, "friend") for u in sorted(friends)]
    if audience in ("public", "followers"):
        out += [
            (u, "follow")
            for u in sorted({f for f, t in world.follows if t == author} - friends - {author})
        ]
    return out


# ---- the oracle: post's visible_to_viewer ----------------------------------------------


def oracle(world: World, viewer: str, p: dict) -> bool:
    held = p["author_type"] == "user" and not world.active[p["author"]]
    if p["deleted"] or held or p["moderation"] == "removed":
        return False  # Post.is_visible
    author = p["author"]
    if p["author_type"] == "page":
        page = world.pages[author]
        team = viewer == page["owner"]
        if not team and (page["status"] != "published" or page["deleted"]):
            return False
        if world.blocked(viewer, page["owner"]):
            return False
    if p["group"] is not None:
        group = world.groups[p["group"]]
        member = world.members.get((viewer, p["group"]), {})
        if group["status"] != "active" or member.get("state") == "banned":
            return False
        if member.get("state") != "active":
            owners = {
                u
                for (u, g), m in world.members.items()
                if g == p["group"] and m["role"] == "owner" and m["state"] == "active"
            }
            if group["privacy"] != "public" or any(world.blocked(viewer, o) for o in owners):
                return False
        if viewer != author and world.blocked(viewer, author):
            return False
        if p["approval"] == "pending":
            return viewer == author or (
                member.get("state") == "active" and member.get("role") in STAFF
            )
        return True
    if author == viewer:
        return True
    if world.blocked(viewer, author):
        return False
    if p["audience"] == "public":
        return True
    if p["audience"] == "friends":
        return world.are_friends(viewer, author)
    if p["audience"] == "followers":
        return world.are_friends(viewer, author) or (viewer, author) in world.follows
    return False


# ---- the property ----------------------------------------------------------------------


def _assert_authorized(world, viewer, limited, kept, posts, surface) -> None:
    for c in kept:
        p = posts[c.post_id]
        assert oracle(world, viewer, p), (surface, c, p)
        if c.source in DISCOVERY:
            # Strangers' reach: never a limited viewer (no allow-listed topics yet),
            # never a restricted author or page owner, never content under review.
            assert not limited, (surface, c)
            assert p["author"] not in world.restricted
            owner = world.pages.get(p["author"], {}).get("owner")
            assert owner not in world.restricted
            assert p["moderation"] == "ok" and p["reports"] < 3
        if p["approval"] == "pending":
            assert c.source == "connections" and p["author"] == viewer
        if p["type"] == "reel":  # playability is feed's rule (E1c), not post's
            assert p["reel_state"] == "published", (surface, c, p)


@settings(
    max_examples=120,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(world=worlds())
def test_no_returned_id_is_unauthorized(world):
    with transaction.atomic():
        _store(world)
        posts = {p["post_id"]: p for p in world.posts}
        for viewer in world.users:
            limited = world.limited[viewer]
            v = Viewer(
                viewer,
                is_minor=True if limited else False,
                age_band="13-17" if limited else "25-34",
            )
            for surface in SURFACES:
                cfg = config.for_surface(surface)
                found = retrieval.candidates(viewer, surface, cfg, now=NOW)
                kept = eligibility.filter(v, found, cfg).kept
                _assert_authorized(world, viewer, limited, kept, posts, surface)
                assert len({c.post_id for c in kept}) == len(kept)
            # Adversarial: every post offered through every non-connection source,
            # whatever the retrieval queries would have found. Eligibility alone must
            # stop the unauthorized ones (connections are trusted fan-out rows).
            offered = [
                Candidate(p["post_id"], p["author"], source, "x", NOW, p["type"])
                for p in world.posts
                for source in sorted(eligibility.NON_CONNECTION)
            ]
            kept = eligibility.filter(v, offered, config.for_surface("home")).kept
            _assert_authorized(world, viewer, limited, kept, posts, "any")
        transaction.set_rollback(True)
