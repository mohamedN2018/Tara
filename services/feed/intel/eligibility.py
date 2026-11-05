"""Stage 1b: the eligibility filter (02 section 11; WP 3.5). Runs before any scoring.

Every rule is one function ``(candidate, ctx) -> bool`` (True keeps it) and counts
what it drops in ``intel_eligibility_drop_total{rule}``. The privacy and safety rules
(E1 to E7, E9, E11) are **fail closed**: data the rule needs and does not have (no
``intel_content_ref`` row for a pulled post, no ``intel_group_ref`` for its group, no
``intel_page_ref`` for a page author, an empty audience) drops the candidate. No
config, user or LLM can turn them off. E8 and E10 are the viewer's preference
filters: they only ever remove more.

Where each rule applies (``SOURCE CLASSES``):

- ``connections`` rows were audience-checked by the fan-out: E1, E1b, E1c, E3, E4, E5
  and E6b re-check what can change after it (deletion, reel playability, group bans,
  blocks, hides, page status). A pending group post keeps only its author's own row.
- pull sources (``follow_pull``, ``groups``) never went through the fan-out check:
  E1, E1b, E1c, E2b, E3, E4, E5, E6 (active), E6b.
- discovery sources (``reels``, ``video`` public pools; WP 9.1's pools later): every
  rule, including E2 (public, or a public active group), E6 (searchable), E7
  (pending integrity), E8 (dislikes), E9 (age), E10 (languages), E11 (restriction).

All data comes from feed_db in a fixed number of batched queries (one ``IN`` per
table), never one call per candidate and never another service.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from django.db import connection

from . import metrics, ports
from .config import SurfaceConfig
from .retrieval.sources import CONNECTIONS, FOLLOW_PULL, GROUPS, REELS, VIDEO, Candidate

logger = logging.getLogger("tara.intel.eligibility")

PULL = frozenset({FOLLOW_PULL, GROUPS})
# Non-connection content of strangers; WP 9.1 adds discovery, trending, new_creators.
DISCOVERY = frozenset({REELS, VIDEO, "discovery", "trending", "new_creators"})
ALL = frozenset({CONNECTIONS}) | PULL | DISCOVERY
NON_CONNECTION = PULL | DISCOVERY

# Age bands with full discovery; anything else (a minor, "unknown", no claim) is
# limited (rule E9, owner decision 9a).
ADULT_BANDS = frozenset({"18-24", "25-34", "35-44", "45+"})


@dataclass(frozen=True)
class Viewer:
    """Who is asking. ``is_minor`` and ``age_band`` come from the access token's
    claims (``identity/tokens.py``); missing claims mean a limited viewer.
    ``languages`` is the viewer's content languages (E10); ``None`` until WP 8.x
    stores them, which applies no language filter (a preference, not a privacy rule)."""

    id: str
    is_minor: bool | None = None
    age_band: str | None = None
    languages: frozenset[str] | None = None
    other_languages: bool = False

    @classmethod
    def from_claims(cls, claims: dict, **kw) -> Viewer:
        return cls(
            id=str(claims.get("sub")),
            is_minor=claims.get("is_minor"),
            age_band=claims.get("age_band"),
            **kw,
        )

    @property
    def limited(self) -> bool:
        return self.is_minor is not False or self.age_band not in ADULT_BANDS


@dataclass
class Context:
    viewer: Viewer
    cfg: SurfaceConfig
    content: dict[str, dict]
    pages: dict[str, dict]
    groups: dict[str, dict]
    memberships: dict[str, dict]
    group_owners: dict[str, set[str]]
    blocked: set[str]
    friends: set[str]
    follows: set[str]
    authors: dict[str, dict]
    restricted: set[str]
    exclusions: dict[str, set[str]]
    topics: dict[str, set[int]] = field(default_factory=dict)  # phase 6

    def ref(self, c: Candidate) -> dict | None:
        return self.content.get(c.post_id)

    def author(self, c: Candidate) -> str | None:
        ref = self.ref(c)
        return str(ref["author_id"]) if ref and ref["author_id"] else c.author_id

    def is_page(self, c: Candidate) -> bool:
        ref = self.ref(c)
        author = self.author(c)
        return bool(
            (ref and ref["author_type"] == "page")
            or (author and self.authors.get(author, {}).get("kind") == "page")
            or (author and author in self.pages)
        )

    def page_owner(self, c: Candidate) -> str | None:
        page = self.pages.get(self.author(c) or "")
        return str(page["owner_id"]) if page and page["owner_id"] else None

    def own(self, c: Candidate) -> bool:
        return self.author(c) == self.viewer.id


# ---- the rules ----------------------------------------------------------------------


def e1_live(c: Candidate, ctx: Context) -> bool:
    """Not deleted, not held (author deactivated), not removed by moderation. A pulled
    or discovered post that feed has no content row for is unknown: dropped."""
    ref = ctx.ref(c)
    if ref is None:
        return c.source == CONNECTIONS  # fan-out rows: feed's PostState already applies
    return ref["state"] == "live" and ref["moderation_state"] != "removed"


def e1b_group_approval(c: Candidate, ctx: Context) -> bool:
    """A group post waiting for approval is in no intel source (its author keeps the
    own fan-out row, staff review it in the group's queue)."""
    ref = ctx.ref(c)
    if ref is None:
        return c.source == CONNECTIONS
    if ref["group_id"] is None and ref["audience"] != "group":
        return True
    if ref["approval_state"] == "approved":
        return True
    return c.source == CONNECTIONS and ctx.own(c)


def e1c_reel_playable(c: Candidate, ctx: Context) -> bool:
    ref = ctx.ref(c)
    if ref is None:
        return c.type != "reel" or c.source == CONNECTIONS
    if ref["type"] != "reel" and c.type != "reel":
        return True
    return ref["reel_state"] == "published"


def _group_public_active(ctx: Context, group_id) -> bool:
    group = ctx.groups.get(str(group_id))
    return bool(group and group["privacy"] == "public" and group["status"] == "active")


def e2_audience_public(c: Candidate, ctx: Context) -> bool:
    """Discovery: public and not in a group, or in a public, active group."""
    ref = ctx.ref(c)
    if ref is None:
        return False
    if ref["group_id"] is None:
        return ref["audience"] == "public"
    return _group_public_active(ctx, ref["group_id"])


def e2b_pull_audience(c: Candidate, ctx: Context) -> bool:
    """Pull sources: post's audience rule (``visible_to_viewer``) on feed's edges."""
    ref = ctx.ref(c)
    if ref is None:
        return False
    if ref["group_id"] is not None:
        return ref["audience"] == "group"  # E1b and E3 decide
    author = ctx.author(c)
    audience = ref["audience"]
    if author == ctx.viewer.id:
        return audience in {"public", "friends", "followers", "only_me"}
    if audience == "public":
        return True
    if audience == "friends":
        return author in ctx.friends
    if audience == "followers":
        return author in ctx.friends or author in ctx.follows
    return False  # only_me, group without a group, unknown


def e3_group_access(c: Candidate, ctx: Context) -> bool:
    """A group post: the group is known and active; a banned account sees nothing;
    private and hidden groups need an active membership; a public group's content
    is not shown to a non-member who has a block with any of its owners."""
    ref = ctx.ref(c)
    if ref is None or ref["group_id"] is None:
        return ref is not None or c.source == CONNECTIONS
    group_id = str(ref["group_id"])
    group = ctx.groups.get(group_id)
    if group is None or group["status"] != "active":
        return False
    state = ctx.memberships.get(group_id, {}).get("state")
    if state == "banned":
        return False
    if state == "active":
        return True
    if group["privacy"] != "public":
        return False
    return not (ctx.group_owners.get(group_id, set()) & ctx.blocked)


def e4_no_block(c: Candidate, ctx: Context) -> bool:
    """No block either way with the author, or with the owner of the page it posted as."""
    if ctx.own(c):
        return True
    author = ctx.author(c)
    if author is None or author in ctx.blocked:
        return False
    owner = ctx.page_owner(c)
    return owner is None or owner == ctx.viewer.id or owner not in ctx.blocked


def e5_viewer_hides(c: Candidate, ctx: Context) -> bool:
    ex = ctx.exclusions
    author = ctx.author(c) or ""
    return not (c.post_id in ex["hidden"] or author in ex["snoozed"] or author in ex["muted"])


def e6_author_active(c: Candidate, ctx: Context) -> bool:
    """Outside connections the author is active; discovery also needs ``searchable``."""
    author = ctx.author(c)
    if author is None:
        return False
    ref = ctx.authors.get(author)
    if ref is None:
        return True  # feed's default: active and searchable until told otherwise
    if not ref["active"]:
        return False
    return c.source not in DISCOVERY or ref["searchable"]


def e6b_page_published(c: Candidate, ctx: Context) -> bool:
    """A page's post only while the page is published and not deleted (``_page_visible``).
    A page feed has no row for is unknown: dropped."""
    if not ctx.is_page(c):
        return True
    page = ctx.pages.get(ctx.author(c) or "")
    return bool(page and page["status"] == "published" and not page["deleted"])


def e7_pending_integrity(c: Candidate, ctx: Context) -> bool:
    integrity = ctx.cfg.section("integrity")
    if not integrity["exclude_pending_from_discovery"]:
        return True
    ref = ctx.ref(c)
    if ref is None:
        return False
    return not (
        ref["moderation_open"]
        or ref["moderation_state"] == "pending"
        or ref["pending_reports"] >= integrity["pending_report_min_reporters"]
    )


def e8_dislikes(c: Candidate, ctx: Context) -> bool:
    """A creator the viewer said they dislike (topics join in phase 6)."""
    return (ctx.author(c) or "") not in ctx.exclusions["disliked"]


def e9_age(c: Candidate, ctx: Context) -> bool:
    """A minor or unknown-age viewer discovers only pages and public groups in an
    allow-listed topic (``eligibility.minor_allowed_topics``)."""
    if not ctx.viewer.limited:
        return True
    ref = ctx.ref(c)
    if ref is None:
        return False
    if not (ctx.is_page(c) or (ref["group_id"] and _group_public_active(ctx, ref["group_id"]))):
        return False
    allowed = set(ctx.cfg.get("eligibility.minor_allowed_topics"))
    return bool(ctx.topics.get(c.post_id, set()) & allowed)


def e10_language(c: Candidate, ctx: Context) -> bool:
    v = ctx.viewer
    if v.languages is None or v.other_languages:
        return True
    ref = ctx.ref(c)
    return ref is not None and ref["lang"] in (set(v.languages) | {"und"})


def e11_restriction(c: Candidate, ctx: Context) -> bool:
    """An account under ``restrict`` or ``shadow`` (or the page it owns) reaches no
    stranger. Its connection and pull rows are untouched: it must not notice."""
    author = ctx.author(c)
    if author is None:
        return False
    return author not in ctx.restricted and (ctx.page_owner(c) or "") not in ctx.restricted


Rule = Callable[[Candidate, Context], bool]

# (counter label, sources it applies to, rule), in order: the first rule that
# drops a candidate is the one counted.
RULES: tuple[tuple[str, frozenset[str], Rule], ...] = (
    ("E1", ALL, e1_live),
    ("E1b", ALL, e1b_group_approval),
    ("E1c", ALL, e1c_reel_playable),
    ("E2", DISCOVERY, e2_audience_public),
    ("E2b", PULL, e2b_pull_audience),
    ("E3", ALL, e3_group_access),
    ("E4", ALL, e4_no_block),
    ("E5", ALL, e5_viewer_hides),
    ("E6", NON_CONNECTION, e6_author_active),
    ("E6b", ALL, e6b_page_published),
    ("E7", DISCOVERY, e7_pending_integrity),
    ("E8", DISCOVERY, e8_dislikes),
    ("E9", DISCOVERY, e9_age),
    ("E10", DISCOVERY, e10_language),
    ("E11", DISCOVERY, e11_restriction),
)
RULE_NAMES = tuple(name for name, _, _ in RULES)


# ---- loading ------------------------------------------------------------------------


def _fetch(sql: str, params) -> list[dict]:
    with connection.cursor() as cur:
        cur.execute(sql, params)
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]


def _s(value) -> str:
    return str(value)


def load_context(viewer: Viewer, candidates: list[Candidate], cfg: SurfaceConfig) -> Context:
    post_ids = sorted({c.post_id for c in candidates})
    content = {
        _s(r["post_id"]): r
        for r in _fetch(
            "SELECT post_id, author_id, author_type, type, audience, group_id, approval_state,"
            " reel_state, lang, state, moderation_state, pending_reports, moderation_open"
            " FROM intel_content_ref WHERE post_id = ANY(%s::uuid[])",
            [post_ids],
        )
    }
    authors = sorted(
        {_s(r["author_id"]) for r in content.values() if r["author_id"]}
        | {c.author_id for c in candidates if c.author_id}
    )
    pages = {
        _s(r["page_id"]): r
        for r in _fetch(
            "SELECT page_id, owner_id, status, deleted FROM intel_page_ref"
            " WHERE page_id = ANY(%s::uuid[])",
            [authors],
        )
    }
    group_ids = sorted({_s(r["group_id"]) for r in content.values() if r["group_id"]})
    groups = {
        _s(r["group_id"]): r
        for r in _fetch(
            "SELECT group_id, privacy, status FROM intel_group_ref"
            " WHERE group_id = ANY(%s::uuid[])",
            [group_ids],
        )
    }
    memberships = {
        _s(r["group_id"]): r
        for r in _fetch(
            "SELECT group_id, state FROM intel_group_membership"
            " WHERE account_id = %s AND group_id = ANY(%s::uuid[])",
            [viewer.id, group_ids],
        )
    }
    group_owners: dict[str, set[str]] = {}
    for r in _fetch(
        "SELECT group_id, account_id FROM intel_group_membership"
        " WHERE group_id = ANY(%s::uuid[]) AND role = 'owner' AND state = 'active'",
        [group_ids],
    ):
        group_owners.setdefault(_s(r["group_id"]), set()).add(_s(r["account_id"]))
    owners = {_s(p["owner_id"]) for p in pages.values() if p["owner_id"]}
    others = sorted(set(authors) | owners | {o for s in group_owners.values() for o in s})
    blocked = {
        _s(r["other"])
        for r in _fetch(
            "SELECT CASE WHEN low = %(v)s THEN high ELSE low END AS other FROM intel_block_pair"
            " WHERE (low_blocks OR high_blocks) AND ("
            " (low = %(v)s AND high = ANY(%(o)s::uuid[]))"
            " OR (high = %(v)s AND low = ANY(%(o)s::uuid[])))",
            {"v": viewer.id, "o": others},
        )
    }
    friends = {
        _s(r["friend_id"])
        for r in _fetch(
            "SELECT friend_id FROM intel_friend_edge"
            " WHERE account_id = %s AND active AND friend_id = ANY(%s::uuid[])",
            [viewer.id, authors],
        )
    }
    restricted = {
        _s(r["account_id"])
        for r in _fetch(
            "SELECT account_id FROM intel_account_restriction"
            " WHERE active AND account_id = ANY(%s::uuid[])",
            [sorted(set(authors) | owners)],
        )
    }
    return Context(
        viewer=viewer,
        cfg=cfg,
        content=content,
        pages=pages,
        groups=groups,
        memberships=memberships,
        group_owners=group_owners,
        blocked=blocked,
        friends=friends,
        follows=ports.followed_among(viewer.id, authors),
        authors=ports.author_refs(authors),
        restricted=restricted,
        exclusions=ports.viewer_exclusions(viewer.id, authors, post_ids),
    )


# ---- the filter ---------------------------------------------------------------------


@dataclass
class Result:
    kept: list[Candidate]
    dropped: Counter = field(default_factory=Counter)  # {rule: n}


def evaluate(c: Candidate, ctx: Context) -> str | None:
    """The first rule that drops ``c``, or None when it is eligible. An unknown
    source is never eligible (fail closed)."""
    if c.source not in ALL:
        return "E0"
    for name, applies, rule in RULES:
        if c.source in applies and not rule(c, ctx):
            return name
    return None


def filter(  # noqa: A001 - the stage's name in 02 section 6
    viewer: Viewer, candidates: Iterable[Candidate], cfg: SurfaceConfig
) -> Result:
    items = list(candidates)
    if not items:
        return Result([])
    ctx = load_context(viewer, items, cfg)
    result = Result([])
    for c in items:
        rule = evaluate(c, ctx)
        if rule is None:
            result.kept.append(c)
        else:
            result.dropped[rule] += 1
    for rule, n in result.dropped.items():
        metrics.eligibility_dropped(rule, n)
    return result
