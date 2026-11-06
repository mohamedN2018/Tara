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
- discovery sources (``reels``, ``video`` public pools, the Home ``discovery`` pools
  of WP 4b.6; WP 9.1's pools later): every rule, including E2 (public, or a public
  active group), E6 (searchable), E7 (pending integrity), E8 (dislikes), E9 (the
  viewer's age), E9b (the author's age), E10 (languages), E11 (restriction).

All data comes from feed_db in a fixed number of batched queries (one ``IN`` per
table), never one call per candidate and never another service.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from django.db import connection

from . import metrics
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
    # R4 (02 section 10.1): discovery toggles the viewer turned off (rule E12).
    discovery_off: frozenset[str] = frozenset()
    # R4: read the viewer's interest rows with the relations (an ``intel:prof`` miss).
    want_profile: bool = False

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
    topics: dict[str, set[int]] = field(default_factory=dict)  # phase 6 (R4)
    # R4: each post's ``(topic_id, confidence)``, best first (``intel_content_topic``),
    # the labels of those topics, and (``Viewer.want_profile``) the viewer's interest
    # rows, read in the same relations statement (no query for a profile-cache miss).
    topic_conf: dict[str, list[tuple[int, float]]] = field(default_factory=dict)
    topic_labels: dict[int, dict] = field(default_factory=dict)
    profile_rows: list | None = None

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
    # ``get`` (read only, no copy): this rule runs once per candidate.
    if not ctx.cfg.get("integrity.exclude_pending_from_discovery"):
        return True
    ref = ctx.ref(c)
    if ref is None:
        return False
    return not (
        ref["moderation_open"]
        or ref["moderation_state"] == "pending"
        or ref["pending_reports"] >= ctx.cfg.get("integrity.pending_report_min_reporters")
    )


def e8_dislikes(c: Candidate, ctx: Context) -> bool:
    """A creator the viewer said they dislike, or chose "Don't recommend this creator"
    for, and (R4, 07 WP 7.5-B2) an item carrying a topic the viewer muted or
    explicitly disliked: never recommended. Connected items are not filtered here
    (a muted primary topic demotes them, ``intel.ranking.home``)."""
    author = ctx.author(c) or ""
    if author in ctx.exclusions["disliked"] or author in ctx.exclusions.get("hidden_creators", ()):
        return False
    blocked = ctx.exclusions.get("excluded_topics")
    return not (blocked and ctx.topics.get(c.post_id, set()) & blocked)


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


def e9b_author_age(c: Candidate, ctx: Context) -> bool:
    """WP 4b.14 (owner decisions 9b and 37): a ``kind=user`` author reaches strangers'
    discovery only when their own token said adult (``author_ref.age_class``). A
    minor, an unknown age or no ``author_ref`` row at all is dropped (fail closed).
    Pages carry no age class and are not excluded; connection and pull items never
    run this rule, so friends and followers still see a minor's posts."""
    if ctx.is_page(c):
        return True
    author = ctx.author(c)
    if author is None:
        return False
    return (ctx.authors.get(author) or {}).get("age_class") == "adult"


def e10_language(c: Candidate, ctx: Context) -> bool:
    v = ctx.viewer
    if v.languages is None or v.other_languages:
        return True
    ref = ctx.ref(c)
    return ref is not None and ref["lang"] in (set(v.languages) | {"und"})


# R4 rule E12: the sources and pool buckets each discovery toggle removes (02 section
# 10.1). ``trending`` also covers Home's ``rec_popular`` bucket (what spreads now);
# ``new_creators`` the WP 9.1 source of that name (none feeds Home before R5).
TOGGLE_REASONS = {
    "trending": frozenset({"trending", "rec_popular"}),
    "new_creators": frozenset({"new_creators"}),
}


def e12_discovery_toggles(c: Candidate, ctx: Context) -> bool:
    """A recommended item from a source or bucket the viewer turned off."""
    for toggle in ctx.viewer.discovery_off:
        names = TOGGLE_REASONS.get(toggle, frozenset())
        if c.source in names or c.reason in names:
            return False
    return True


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
    ("E9b", DISCOVERY, e9b_author_age),
    ("E10", DISCOVERY, e10_language),
    ("E11", DISCOVERY, e11_restriction),
    ("E12", DISCOVERY, e12_discovery_toggles),
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


_CONTEXT_CONTENT_SQL = """
SELECT c.post_id, c.author_id, c.author_type, c.type, c.audience, c.group_id,
       c.approval_state, c.reel_state, c.lang, c.state, c.moderation_state,
       c.pending_reports, c.moderation_open, c.created_at,
       EXISTS (SELECT 1 FROM feed_item i WHERE i.recipient_id = %(v)s
               AND i.post_id = c.post_id) AS in_feed,
       g.privacy AS g_privacy, g.status AS g_status, m.state AS m_state
FROM intel_content_ref c
LEFT JOIN intel_group_ref g ON g.group_id = c.group_id
LEFT JOIN intel_group_membership m ON m.group_id = c.group_id AND m.account_id = %(v)s
WHERE c.post_id = ANY(%(posts)s::uuid[])
"""
# Everything else ``filter``'s rules read, in one round trip (R3 WP A8: the first page
# went from 14 eligibility queries to 2, same data): pages of the authors, group
# owners, blocks either way (authors, the pages' owners, the groups' owners), friends,
# restrictions (authors and page owners), follows, author refs, and the viewer's
# hides, snoozes, mutes and creator dislikes. Rows are (kind, key, a, b, c, d) text.
_CONTEXT_RELATIONS_SQL = """
WITH pages AS (
    SELECT page_id, owner_id, status, deleted FROM intel_page_ref
    WHERE page_id = ANY(%(authors)s::uuid[])),
owners AS (
    SELECT group_id, account_id FROM intel_group_membership
    WHERE group_id = ANY(%(groups)s::uuid[]) AND role = 'owner' AND state = 'active'),
others AS (
    SELECT unnest(%(authors)s::uuid[]) AS id
    UNION SELECT owner_id FROM pages WHERE owner_id IS NOT NULL
    UNION SELECT account_id FROM owners)
SELECT 'page', page_id::text, owner_id::text, status, deleted::text, NULL FROM pages
UNION ALL
SELECT 'owner', group_id::text, account_id::text, NULL, NULL, NULL FROM owners
UNION ALL
SELECT 'blocked', (CASE WHEN low = %(v)s THEN high ELSE low END)::text, NULL, NULL, NULL, NULL
FROM intel_block_pair
WHERE (low_blocks OR high_blocks)
  AND ((low = %(v)s AND high IN (SELECT id FROM others))
    OR (high = %(v)s AND low IN (SELECT id FROM others)))
UNION ALL
SELECT 'friend', friend_id::text, NULL, NULL, NULL, NULL FROM intel_friend_edge
WHERE account_id = %(v)s AND active AND friend_id = ANY(%(authors)s::uuid[])
UNION ALL
SELECT 'restricted', account_id::text, NULL, NULL, NULL, NULL FROM intel_account_restriction
WHERE active AND (account_id = ANY(%(authors)s::uuid[])
                  OR account_id IN (SELECT owner_id FROM pages WHERE owner_id IS NOT NULL))
UNION ALL
SELECT 'follow', target_id::text, NULL, NULL, NULL, NULL FROM follow_edge
WHERE follower_id = %(v)s AND active AND target_id = ANY(%(authors)s::uuid[])
UNION ALL
SELECT 'author', account_id::text, kind, active::text, searchable::text, age_class
FROM author_ref WHERE account_id = ANY(%(authors)s::uuid[])
UNION ALL
SELECT 'hidden', post_id::text, NULL, NULL, NULL, NULL FROM post_hide
WHERE account_id = %(v)s AND post_id = ANY(%(posts)s::uuid[])
UNION ALL
SELECT 'snoozed', author_id::text, NULL, NULL, NULL, NULL FROM author_snooze
WHERE account_id = %(v)s AND until > %(now)s AND author_id = ANY(%(authors)s::uuid[])
UNION ALL
SELECT 'muted', target_id::text, NULL, NULL, NULL, NULL FROM relationship_flag
WHERE actor_id = %(v)s AND kind = 'mute' AND active AND target_id = ANY(%(authors)s::uuid[])
UNION ALL
SELECT 'disliked', author_id::text, NULL, NULL, NULL, NULL FROM post_hide
WHERE account_id = %(v)s AND reason = 'dislike_creator' AND author_id = ANY(%(authors)s::uuid[])
UNION ALL
SELECT 'pref_' || polarity, key, dim, NULL, NULL, NULL FROM intel_user_interest
WHERE account_id = %(v)s AND source = 'explicit'
  AND ((dim = 'creator' AND polarity = 'hidden' AND key = ANY(%(author_keys)s::text[]))
    OR (dim = 'topic' AND polarity IN ('muted', 'dislike')))
UNION ALL
SELECT 'ctopic', ct.post_id::text, ct.topic_id::text, ct.confidence::text,
       t.slug || '|' || t.label_ar || '|' || t.label_en, NULL
FROM intel_content_topic ct JOIN intel_topic t ON t.id = ct.topic_id AND t.status = 'active'
WHERE ct.post_id = ANY(%(posts)s::uuid[])
UNION ALL
SELECT 'prof', dim, key, source || ':' || coalesce(polarity, ''),
       short_v || '|' || coalesce(extract(epoch FROM short_at), 0) || '|' || mid_v || '|'
       || coalesce(extract(epoch FROM mid_at), 0) || '|' || long_v || '|'
       || coalesce(extract(epoch FROM long_at), 0), NULL
FROM intel_user_interest WHERE %(want_profile)s AND account_id = %(v)s
"""
_GROUP_KEYS = ("g_privacy", "g_status", "m_state")
# A block either way between two accounts (R4 feedback on a profile): params
# (viewer, other, other, viewer).
_BLOCKED_ONE_SQL = (
    "SELECT 1 FROM intel_block_pair WHERE (low_blocks OR high_blocks) AND "
    "((low = %s AND high = %s) OR (low = %s AND high = %s))"
)


def _bool(value) -> bool:
    return value in ("true", "t", True)


def _pref(kind: str, key: str, dim, prefs: dict) -> None:
    """One explicit preference row of the relations statement (R4, rule E8)."""
    if dim == "creator" and kind == "pref_hidden":
        prefs["hidden_creators"].add(key)
    elif dim == "topic" and kind in ("pref_muted", "pref_dislike"):
        try:
            topic_id = int(key)
        except ValueError:
            return
        prefs["excluded_topics"].add(topic_id)
        if kind == "pref_muted":
            prefs["muted"].add(topic_id)


def load_context(viewer: Viewer, candidates: list[Candidate], cfg: SurfaceConfig) -> Context:
    """Everything the rules read for ``candidates``, in **two** queries (content with
    its group and the viewer's membership; then every relation, ``_CONTEXT_RELATIONS_SQL``)."""
    from django.utils import timezone

    post_ids = sorted({c.post_id for c in candidates})
    content, groups, memberships = {}, {}, {}
    for r in _fetch(_CONTEXT_CONTENT_SQL, {"v": viewer.id, "posts": post_ids}):
        g_privacy, g_status, m_state = (r.pop(k) for k in _GROUP_KEYS)
        content[_s(r["post_id"])] = r
        if r["group_id"] and g_privacy is not None:
            group_id = _s(r["group_id"])
            groups[group_id] = {"group_id": r["group_id"], "privacy": g_privacy, "status": g_status}
        if r["group_id"] and m_state is not None:
            memberships[_s(r["group_id"])] = {"group_id": r["group_id"], "state": m_state}
    authors = sorted(
        {_s(r["author_id"]) for r in content.values() if r["author_id"]}
        | {c.author_id for c in candidates if c.author_id}
    )
    group_ids = sorted({_s(r["group_id"]) for r in content.values() if r["group_id"]})
    pages: dict[str, dict] = {}
    group_owners: dict[str, set[str]] = {}
    authors_ref: dict[str, dict] = {}
    sets: dict[str, set[str]] = {
        k: set()
        for k in (
            "blocked",
            "friend",
            "restricted",
            "follow",
            "hidden",
            "snoozed",
            "muted",
            "disliked",
        )
    }
    topics: dict[str, set[int]] = {}
    topic_conf: dict[str, list[tuple[int, float]]] = {}
    topic_labels: dict[int, dict] = {}
    profile_rows: list[tuple] = []
    prefs: dict[str, set] = {"hidden_creators": set(), "excluded_topics": set(), "muted": set()}
    with connection.cursor() as cur:
        cur.execute(
            _CONTEXT_RELATIONS_SQL,
            {
                "v": viewer.id,
                "authors": authors,
                "author_keys": authors,
                "groups": group_ids,
                "posts": post_ids,
                "now": timezone.now(),
                "want_profile": bool(viewer.want_profile),
            },
        )
        for kind, key, a, b, c, d in cur.fetchall():
            if kind == "ctopic":
                topics.setdefault(key, set()).add(int(a))
                topic_conf.setdefault(key, []).append((int(a), float(b)))
                if c:
                    slug, label_ar, label_en = (c.split("|") + ["", "", ""])[:3]
                    topic_labels[int(a)] = {
                        "slug": slug,
                        "label_ar": label_ar,
                        "label_en": label_en,
                    }
                continue
            if kind == "prof":
                profile_rows.append((key, a, b, c))
                continue
            if kind.startswith("pref_"):
                _pref(kind, key, a, prefs)
                continue
            if kind == "page":
                pages[key] = {"page_id": key, "owner_id": a, "status": b, "deleted": _bool(c)}
            elif kind == "owner":
                group_owners.setdefault(key, set()).add(a)
            elif kind == "author":
                authors_ref[key] = {
                    "account_id": key,
                    "kind": a,
                    "active": _bool(b),
                    "searchable": _bool(c),
                    "age_class": d,
                }
            else:
                sets[kind].add(key)
    return Context(
        viewer=viewer,
        cfg=cfg,
        content=content,
        pages=pages,
        groups=groups,
        memberships=memberships,
        group_owners=group_owners,
        blocked=sets["blocked"],
        friends=sets["friend"],
        follows=sets["follow"],
        authors=authors_ref,
        restricted=sets["restricted"],
        exclusions={
            "hidden": sets["hidden"],
            "snoozed": sets["snoozed"],
            "muted": sets["muted"],
            "disliked": sets["disliked"],
            "hidden_creators": prefs["hidden_creators"],
            "excluded_topics": prefs["excluded_topics"],
            "muted_topics": prefs["muted"],
        },
        topics=topics,
        topic_conf={k: sorted(v, key=lambda t: (-t[1], t[0])) for k, v in topic_conf.items()},
        topic_labels=topic_labels,
        profile_rows=profile_rows if viewer.want_profile else None,
    )


# ---- the filter ---------------------------------------------------------------------


@dataclass
class Result:
    kept: list[Candidate]
    dropped: Counter = field(default_factory=Counter)  # {rule: n}
    content: dict = field(default_factory=dict)  # the content rows the rules read
    # R4: ``{post_id: [(topic_id, confidence)]}`` best first, and the viewer's muted
    # topic ids (a connected item with one as primary is demoted, not dropped).
    topics: dict = field(default_factory=dict)
    muted_topics: frozenset = frozenset()
    topic_labels: dict = field(default_factory=dict)
    profile_rows: list | None = None


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
    result = Result(
        [],
        content=ctx.content,
        topics=ctx.topic_conf,
        muted_topics=frozenset(ctx.exclusions.get("muted_topics", ())),
        topic_labels=ctx.topic_labels,
        profile_rows=ctx.profile_rows,
    )
    for c in items:
        rule = evaluate(c, ctx)
        if rule is None:
            result.kept.append(c)
        else:
            result.dropped[rule] += 1
    for rule, n in result.dropped.items():
        metrics.eligibility_dropped(rule, n)
    return result


# ---- later pages: the re-check (WP 4.10) ---------------------------------------------

# A later page re-runs the rules that can change between pages (02 section 22):
# deletion and moderation, group approval, reel playability, audience, group access,
# blocks, the viewer's hides, snoozes and mutes, and page status.
# E9b (WP 4b.14) too: an author's age class only ever leaves ``unknown``, and a
# discovery item is re-checked fail closed like every other rule here.
# E8 (R4): a creator hidden or a topic muted after the first page is honoured on the
# frozen list's later pages too (its data rides in the same relations statement).
RECHECK = frozenset({"E1", "E1b", "E1c", "E2", "E2b", "E3", "E4", "E5", "E6b", "E8", "E9b"})

_RECHECK_CONTENT_SQL = """
SELECT c.post_id, c.author_id, c.author_type, c.type, c.audience, c.group_id,
       c.approval_state, c.reel_state, c.lang, c.state, c.moderation_state,
       c.pending_reports, c.moderation_open, c.created_at,
       g.privacy AS g_privacy, g.status AS g_status, m.state AS m_state,
       p.page_id AS p_page_id, p.owner_id AS p_owner_id, p.status AS p_status,
       p.deleted AS p_deleted
FROM intel_content_ref c
LEFT JOIN intel_group_ref g ON g.group_id = c.group_id
LEFT JOIN intel_group_membership m ON m.group_id = c.group_id AND m.account_id = %(v)s
LEFT JOIN intel_page_ref p ON p.page_id = c.author_id
WHERE c.post_id = ANY(%(posts)s::uuid[])
"""
# Everything else the rules read, in one round trip: group owners, blocks either way
# (with authors, the pages' owners and the groups' owners), friends, follows, hides,
# snoozes, mutes, and the authors' kind. Rows are (kind, key, value).
_RECHECK_RELATIONS_SQL = """
WITH owners AS (
    SELECT group_id, account_id FROM intel_group_membership
    WHERE group_id = ANY(%(groups)s::uuid[]) AND role = 'owner' AND state = 'active'),
others AS (
    SELECT unnest(%(authors)s::uuid[]) AS id
    UNION SELECT account_id FROM owners
    UNION SELECT owner_id FROM intel_page_ref
          WHERE page_id = ANY(%(authors)s::uuid[]) AND owner_id IS NOT NULL)
SELECT 'owner', group_id::text, account_id::text FROM owners
UNION ALL
SELECT 'blocked', (CASE WHEN low = %(v)s THEN high ELSE low END)::text, NULL
FROM intel_block_pair
WHERE (low_blocks OR high_blocks)
  AND ((low = %(v)s AND high IN (SELECT id FROM others))
    OR (high = %(v)s AND low IN (SELECT id FROM others)))
UNION ALL
SELECT 'friend', friend_id::text, NULL FROM intel_friend_edge
WHERE account_id = %(v)s AND active AND friend_id = ANY(%(authors)s::uuid[])
UNION ALL
SELECT 'follow', target_id::text, NULL FROM follow_edge
WHERE follower_id = %(v)s AND active AND target_id = ANY(%(authors)s::uuid[])
UNION ALL
SELECT 'hidden', post_id::text, NULL FROM post_hide
WHERE account_id = %(v)s AND post_id = ANY(%(posts)s::uuid[])
UNION ALL
SELECT 'snoozed', author_id::text, NULL FROM author_snooze
WHERE account_id = %(v)s AND until > now() AND author_id = ANY(%(authors)s::uuid[])
UNION ALL
SELECT 'muted', target_id::text, NULL FROM relationship_flag
WHERE actor_id = %(v)s AND kind = 'mute' AND active AND target_id = ANY(%(authors)s::uuid[])
UNION ALL
SELECT 'author', account_id::text, kind || ':' || age_class FROM author_ref
WHERE account_id = ANY(%(authors)s::uuid[])
UNION ALL
SELECT 'pref_' || polarity, key, dim FROM intel_user_interest
WHERE account_id = %(v)s AND source = 'explicit'
  AND ((dim = 'creator' AND polarity = 'hidden' AND key = ANY(%(author_keys)s::text[]))
    OR (dim = 'topic' AND polarity IN ('muted', 'dislike')))
UNION ALL
SELECT 'ctopic', ct.post_id::text, ct.topic_id::text || ':' || ct.confidence::text
       || ':' || t.slug || '|' || t.label_ar || '|' || t.label_en
FROM intel_content_topic ct JOIN intel_topic t ON t.id = ct.topic_id AND t.status = 'active'
WHERE ct.post_id = ANY(%(posts)s::uuid[])
"""


def recheck_context(viewer: Viewer, candidates: list[Candidate], cfg: SurfaceConfig) -> Context:
    """The data ``RECHECK`` needs, in two queries (a next page's budget is 3 to 5)."""
    posts = sorted({c.post_id for c in candidates})
    rows = _fetch(_RECHECK_CONTENT_SQL, {"v": viewer.id, "posts": posts})
    content, groups, memberships, pages = {}, {}, {}, {}
    for r in rows:
        content[_s(r["post_id"])] = r
        if r["group_id"] and r["g_privacy"] is not None:
            groups[_s(r["group_id"])] = {"privacy": r["g_privacy"], "status": r["g_status"]}
        if r["group_id"] and r["m_state"] is not None:
            memberships[_s(r["group_id"])] = {"state": r["m_state"]}
        if r["p_page_id"] is not None:
            pages[_s(r["p_page_id"])] = {
                "owner_id": r["p_owner_id"],
                "status": r["p_status"],
                "deleted": r["p_deleted"],
            }
    authors = sorted(
        {_s(r["author_id"]) for r in content.values() if r["author_id"]}
        | {c.author_id for c in candidates if c.author_id}
    )
    group_ids = sorted({_s(r["group_id"]) for r in content.values() if r["group_id"]})
    group_owners: dict[str, set[str]] = {}
    sets: dict[str, set[str]] = {
        k: set() for k in ("blocked", "friend", "follow", "hidden", "snoozed", "muted")
    }
    kinds: dict[str, dict] = {}
    topics: dict[str, set[int]] = {}
    topic_conf: dict[str, list[tuple[int, float]]] = {}
    topic_labels: dict[int, dict] = {}
    prefs: dict[str, set] = {"hidden_creators": set(), "excluded_topics": set(), "muted": set()}
    with connection.cursor() as cur:
        cur.execute(
            _RECHECK_RELATIONS_SQL,
            {
                "v": viewer.id,
                "authors": authors,
                "author_keys": authors,
                "groups": group_ids,
                "posts": posts,
            },
        )
        for kind, key, value in cur.fetchall():
            if kind == "ctopic":
                topic_id, conf, label = ((value or "").split(":", 2) + ["", ""])[:3]
                topics.setdefault(key, set()).add(int(topic_id))
                topic_conf.setdefault(key, []).append((int(topic_id), float(conf or 0)))
                if label:
                    slug, label_ar, label_en = (label.split("|") + ["", "", ""])[:3]
                    topic_labels[int(topic_id)] = {
                        "slug": slug, "label_ar": label_ar, "label_en": label_en
                    }  # fmt: skip
                continue
            if kind.startswith("pref_"):
                _pref(kind, key, value, prefs)
                continue
            if kind == "owner":
                group_owners.setdefault(key, set()).add(value)
            elif kind == "author":
                author_kind, _, age_class = (value or "").partition(":")
                kinds[key] = {
                    "kind": author_kind,
                    "active": True,
                    "searchable": True,
                    "age_class": age_class or "unknown",
                }
            else:
                sets[kind].add(key)
    return Context(
        viewer=viewer,
        cfg=cfg,
        content=content,
        pages=pages,
        groups=groups,
        memberships=memberships,
        group_owners=group_owners,
        blocked=sets["blocked"],
        friends=sets["friend"],
        follows=sets["follow"],
        authors=kinds,
        restricted=set(),  # E11 is a discovery rule: not re-checked
        exclusions={
            "hidden": sets["hidden"],
            "snoozed": sets["snoozed"],
            "muted": sets["muted"],
            "disliked": set(),
            "hidden_creators": prefs["hidden_creators"],
            "excluded_topics": prefs["excluded_topics"],
            "muted_topics": prefs["muted"],
        },
        topics=topics,
        topic_conf={k: sorted(v, key=lambda t: (-t[1], t[0])) for k, v in topic_conf.items()},
        topic_labels=topic_labels,
    )


def recheck(viewer: Viewer, candidates: Iterable[Candidate], cfg: SurfaceConfig) -> Result:
    """``RECHECK`` on a later page's items (fail closed like ``filter``)."""
    items = list(candidates)
    if not items:
        return Result([])
    ctx = recheck_context(viewer, items, cfg)
    result = Result([], content=ctx.content)
    for c in items:
        rule = None
        if c.source not in ALL:
            rule = "E0"
        else:
            for name, applies, fn in RULES:
                if name in RECHECK and c.source in applies and not fn(c, ctx):
                    rule = name
                    break
        if rule is None:
            result.kept.append(c)
        else:
            result.dropped[rule] += 1
    for rule, n in result.dropped.items():
        metrics.eligibility_dropped(rule, n)
    return result
