"""The ranked "for you" mode: pages over a ranking session (1.7; Tara Intelligence 4.3, 4.10).

Ranking itself lives in ``intel.ranking`` and reads every weight from the active
home config (``intel.config``): ``rank_items`` and ``first_page`` always delegate
to ``intel.ranking.home.rank``. With ``home@1`` (active by default) that is
today's formula exactly, over the viewer's newest ``window.connections`` feed rows:

    3 * freshness                   2 ** -(age in hours / 24)
  + reason affinity                 self 0.3, friend 1.0, follow 0.6
  + 1.5 if the viewer favorites the author (about a day of freshness)
  + 0.25 * log(1 + interactions)    the viewer's reactions, comments, shares on the author
  - 0.75 * dislikes (at most 3)     ``dislike_creator`` / ``annoying`` hides of the author
  + 0.5 * engagement                the post's ``PostStats`` (``readmodels.engagement_score``)

``home@2`` adds the group and follow-pull sources, the rule predictions, quality,
integrity demotions and the diversity re-ranker (``intel/config/defaults/home.v2.json``).

The first page stores the ranked list in ``redis-hot`` (session v2,
``intel.ranking.session``: 24 bytes per item, one key per surface). Later pages
read their slice through a signed opaque cursor that names its surface, reload
connection items from ``FeedItem`` and every other item from ``intel_content_ref``,
and re-run the eligibility rules that can change between pages, so posts that
arrive meanwhile never shift a page or repeat one, and posts deleted, hidden or
blocked since page 1 are not returned. When the connections window was full, the
cursor continues in latest order below its oldest row.

The cursor (R3, 4b.12-B3, 08 section 7.3) carries the session id ``s``, the
frozen-list offset ``o``, the config version ``v`` and ``t``/``i``: the oldest
``(post_created_at, id)`` served so far. A later page reads forward from ``o``
until ``size`` entries survive the re-check (short pages are refilled) and names
the rule that dropped every other one. When the session is gone (expired, replaced
by another tab's first page, ``redis-hot`` restarted) or the first page could not
store it (``noeviction`` OOM, counted, never retried), the page says
``fallback: true`` and continues chronologically strictly below ``(t, i)``: nothing
served can come back, by construction. A reload during the visit (``entry`` reload
or nav, a refresh/ongoing visit) serves the live frozen list again (``reuse_page``).

Recommended pool items (WP 4b.6) are ordinary session entries (source
``discovery``, reason ``rec_popular`` / ``rec_fresh``) re-checked on later pages
like any other non-connection item. The session stores ``cu``, the index of the
first item after the connection inventory ran out; the page that holds it says so
in ``caught_up_index`` (its index in the page's ``data``).
"""

from __future__ import annotations

import logging
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from django.conf import settings
from django.core import signing
from django.core.cache import caches
from django.db.models import Count, Q
from django.db.models.expressions import RawSQL
from django.utils.dateparse import parse_datetime
from intel import config
from intel import metrics as intel_metrics
from intel.eligibility import ALL as ELIGIBLE_SOURCES
from intel.eligibility import RECHECK, RULES, Viewer, recheck_context
from intel.models import ContentRef
from intel.ranking import home as home_ranker
from intel.ranking import session as rank_session
from intel.retrieval.sources import CONNECTIONS, Candidate

from . import feedback, readmodels
from .models import FeedItem, PostHide, PostState, RelationshipFlag

logger = logging.getLogger("tara.feed.ranking")

Reason = FeedItem.Reason
CONNECTED = (Reason.SELF, Reason.FRIEND, Reason.FOLLOW)
SURFACE = "home"

_SALT = "tara.feed.cursor.v1"
_MAX_ID = "ffffffff-ffff-ffff-ffff-ffffffffffff"


class InvalidCursor(Exception):
    """The cursor was not issued by this service (or was altered)."""


# Accounts with a block either way with the viewer (``intel_block_pair``, rule E4).
_BLOCKED_SQL = (
    "SELECT CASE WHEN low = %s THEN high ELSE low END FROM intel_block_pair"
    " WHERE (low = %s OR high = %s) AND (low_blocks OR high_blocks)"
)


def visible_items(viewer_id):
    """The viewer's feed rows minus what they hid, snoozed or muted, posts of
    deactivated accounts and, fail closed, authors with a block either way (R3: the
    ``user.blocked`` handler deletes those rows, but a fan-out racing the block must
    not show or count one, 07 WP 4b.7). Every mode starts here."""
    v = str(viewer_id)
    return (
        FeedItem.objects.filter(recipient_id=viewer_id)
        .exclude(post_id__in=PostState.objects.filter(hidden=True).values("post_id"))
        .exclude(post_id__in=feedback.hidden_post_ids(viewer_id))
        .exclude(author_id__in=feedback.snoozed_author_ids(viewer_id))
        .exclude(author_id__in=readmodels.flagged_ids(viewer_id, RelationshipFlag.Kind.MUTE))
        # A fixed statement; the viewer id is a bound parameter.
        .exclude(author_id__in=RawSQL(_BLOCKED_SQL, [v, v, v]))  # noqa: S611
    )


def _candidates(viewer_id):
    return visible_items(viewer_id).exclude(
        Q(author_id__in=readmodels.non_searchable_ids()) & ~Q(reason__in=CONNECTED)
    )


def author_penalties(viewer_id, author_ids) -> dict[str, int]:
    rows = (
        PostHide.objects.filter(
            account_id=viewer_id,
            author_id__in=author_ids,
            reason__in=feedback.AUTHOR_DOWNWEIGHT_REASONS,
        )
        .values("author_id")
        .annotate(n=Count("id"))
    )
    return {str(r["author_id"]): r["n"] for r in rows}


def home_config(window: int | None = None):
    """The active home config (``window`` overrides ``window.connections``)."""
    if window is None:
        return config.for_surface(SURFACE)
    return config.for_surface(SURFACE, {"window": {CONNECTIONS: window}})


def _viewer(viewer_id, claims: dict | None = None) -> Viewer:
    if claims:
        return Viewer.from_claims({**claims, "sub": str(viewer_id)})
    return Viewer(id=str(viewer_id))


# ---- items -----------------------------------------------------------------------


_SNAPSHOT_KEYS = ("author_type", "type", "audience")


def _pulled_item(viewer_id, ref: dict, reason: str) -> FeedItem:
    """An unsaved ``FeedItem`` for a non-connection candidate: ids and enums only
    (the client hydrates every item through post's ``/posts/batch/``)."""
    post_id = str(ref["post_id"])
    created = ref["created_at"]
    snapshot = {"post_id": post_id, "author_id": str(ref["author_id"])}
    snapshot.update({k: ref[k] for k in _SNAPSHOT_KEYS if ref.get(k)})
    if created is not None:
        snapshot["created_at"] = created.isoformat()
    return FeedItem(
        id=uuid.UUID(post_id),
        recipient_id=viewer_id,
        post_id=post_id,
        author_id=ref["author_id"],
        reason=reason,
        score=0.0,
        snapshot=snapshot,
        post_created_at=created,
    )


def _materialize(viewer_id, entries: list[tuple[str, str, str]], refs: dict | None = None):
    """``[(post_id, source, reason)]`` as ``(item, source, index)``, in order (``index``
    is the entry's position in ``entries``); a post no longer visible is left out.
    Connections come from ``FeedItem`` (one query), the rest from ``intel_content_ref``
    (``refs`` when the caller already read them: no query)."""
    conn = [p for p, s, _ in entries if s == CONNECTIONS]
    rows = {str(i.post_id): i for i in visible_items(viewer_id).filter(post_id__in=conn)}
    others = [p for p, s, _ in entries if s != CONNECTIONS]
    if others and refs is None:
        refs = {
            str(r["post_id"]): r
            for r in ContentRef.objects.filter(post_id__in=others).values(
                "post_id", "author_id", "created_at", *_SNAPSHOT_KEYS
            )
        }
    out = []
    for n, (post_id, source, reason) in enumerate(entries):
        if source == CONNECTIONS:
            if post_id in rows:
                out.append((rows[post_id], source, n))
        elif refs and post_id in refs and refs[post_id]["author_id"]:
            out.append((_pulled_item(viewer_id, refs[post_id], reason), source, n))
    return out


def rank_items(viewer_id, now: datetime, window: int | None = None, claims=None) -> list[FeedItem]:
    """The viewer's ranked items, best first. Same rows and ``now``, same order."""
    ranking = home_ranker.rank(_viewer(viewer_id, claims), now, home_config(window))
    entries = [(s.feats.post_id, s.feats.source, s.feats.reason) for s in ranking.items]
    return [item for item, _, _ in _materialize(viewer_id, entries, ranking.content or None)]


# ---- cursor and session --------------------------------------------------------


def encode_cursor(data: dict) -> str:
    return signing.dumps(data, salt=_SALT, compress=True)


def is_ranked_cursor(token: str | None) -> bool:
    """Whether ``token`` is a cursor this module issued (a ranked or latest-order
    "for you" cursor); a chronological keyset cursor is not (R4: personalization off
    serves "for you" chronologically)."""
    if not token:
        return False
    try:
        decode_cursor(token)
    except InvalidCursor:
        return False
    return True


def decode_cursor(token: str) -> dict:
    try:
        data = signing.loads(token, salt=_SALT)
    except signing.BadSignature as exc:
        raise InvalidCursor from exc
    if not isinstance(data, dict) or data.get("k") not in ("r", "l"):
        raise InvalidCursor
    if data["k"] == "r" and data.get("f", SURFACE) != SURFACE:
        raise InvalidCursor  # a cursor of another surface's session
    return data


def _session_key(viewer_id) -> str:
    return rank_session.key(SURFACE, viewer_id)


def _hot():
    return caches[settings.FEED_HOT_CACHE]


def session_entry(viewer_id, post_id):
    """The post's entry in the viewer's current Home session, or None (WP 4.8)."""
    return rank_session.contains(SURFACE, viewer_id, post_id, _hot())


# ---- pages ---------------------------------------------------------------------


@dataclass
class Page:
    items: list[FeedItem]
    next_cursor: str | None
    fallback: bool = False
    # Ranked pages: each item's candidate source and the config version that ranked it.
    sources: list[str] = field(default_factory=list)
    cfg_version: str | None = None
    # WP 4b.6: the index in ``items`` of the first item served after the connection
    # inventory ran out, else None; ``caught_up`` is true on the page where it ran
    # out (that index, or the last page of a session without continuation).
    caught_up_index: int | None = None
    caught_up: bool = False
    # R3: the ranking session (``sid``), the eligible new-since items of the ranked
    # list and where their block ends (``meta.visit``), what a later page dropped by
    # rule (``{rule: n}``; "visible" = no longer one of the viewer's visible rows),
    # whether a first page reused the live frozen list, and the ranking itself (the
    # harness reads its scores).
    sid: str | None = None
    new_count: int | None = None
    anchor_index: int | None = None
    dropped: dict = field(default_factory=dict)
    reused: bool = False
    ranking: object = None
    offset: int = 0
    # R4: ``{post_id: [(topic_id, confidence)]}`` of the page's items and their labels,
    # when the eligibility read already had them (no extra query for ``topics``).
    topics: dict = field(default_factory=dict)
    topic_labels: dict = field(default_factory=dict)

    @property
    def has_more(self) -> bool:
        return self.next_cursor is not None


def _latest_cursor(item_or_key) -> str:
    if isinstance(item_or_key, FeedItem):
        at, ident = item_or_key.post_created_at.isoformat(), str(item_or_key.id)
    else:
        at, ident = item_or_key
    return encode_cursor({"k": "l", "t": at, "i": ident})


def _latest_page(viewer_id, at: str, ident: str, size: int, *, fallback: bool) -> Page:
    when = parse_datetime(at)
    if when is None:
        raise InvalidCursor
    rows = list(
        _candidates(viewer_id)
        .filter(Q(post_created_at__lt=when) | Q(post_created_at=when, id__lt=ident))
        .order_by("-post_created_at", "-id")[: size + 1]
    )
    more = len(rows) > size
    rows = rows[:size]
    return Page(rows, _latest_cursor(rows[-1]) if more and rows else None, fallback)


def _oldest(items: list[FeedItem], floor) -> tuple[str, str] | None:
    """``(t_min, id_min)``: the oldest ``(post_created_at, id)`` served so far in the
    session (08 section 7.3). A chronological continuation strictly below it cannot
    repeat a served row, by construction."""
    best = None
    if floor is not None and parse_datetime(floor[0]) is not None:
        best = (parse_datetime(floor[0]), str(floor[1]))
    for item in items:
        if item.post_created_at is None:
            continue
        key = (item.post_created_at, str(item.id))
        if best is None or key < best:
            best = key
    return (best[0].isoformat(), best[1]) if best else None


def _ranked_cursor(sid: str, offset: int, as_of: str, version, oldest) -> str:
    data = {"k": "r", "s": sid, "o": offset, "a": as_of, "f": SURFACE, "v": version}
    if oldest is not None:
        data["t"], data["i"] = oldest
    return encode_cursor(data)


def _after_slice(session: dict, sid: str, end: int, as_of: str, oldest) -> str | None:
    if end < session["n"]:
        return _ranked_cursor(sid, end, as_of, session.get("cfg"), oldest)
    if session.get("edge"):  # the window was full: older rows continue in latest order
        return _latest_cursor(tuple(session["edge"]))
    return None


def _caught_up(
    session: dict, positions: list[int], start: int, end: int
) -> tuple[int | None, bool]:
    """``(caught_up_index, caught_up)`` for a page that read session entries
    ``[start, end)`` and serves items at ``positions``. With a continuation (``cu``)
    the page holding ``cu`` ran out (its index may be None when the re-check dropped
    that very item); without one, the last page of a session that ends there."""
    cu = session.get("cu")
    if cu is not None:
        if not start <= cu < end:
            return None, False
        return next((i for i, p in enumerate(positions) if p >= cu), None), True
    return None, end >= session["n"] and not session.get("edge")


def new_since(ranking, since: datetime | None, cfg) -> tuple[int, int | None]:
    """``(new_count, anchor_index)`` of a ranked list (06 section 6.2): the eligible,
    non-recommended items created after ``since`` (the list already passed every
    eligibility rule), and the index just after the last of the first ``max_items`` of
    them, where the "new since your last visit" block ends."""
    if since is None:
        return 0, None
    cap = cfg.get("session.new_since.max_items")
    count, anchor = 0, None
    for i, s in enumerate(ranking.items):
        created = s.feats.created_at
        if s.feats.source != home_ranker.DISCOVERY and created is not None and created > since:
            count += 1
            if count <= cap:
                anchor = i + 1
    return count, anchor


def first_page(
    viewer_id,
    size: int,
    now: datetime,
    claims: dict | None = None,
    *,
    ctx=None,
    pools: list | None = None,
    since: datetime | None = None,
    cfg=None,
    personal=None,
) -> Page:
    """Rank, store the frozen list, serve its head. When redis-hot refuses the session
    (``noeviction`` OOM), the ranked head is still served with ``fallback: true`` and
    the cursor continues chronologically below the head's oldest row (08 section 7.3):
    0 duplicates by construction, and the unserved ranked items come back as carry-over
    at the next first page."""
    cfg = cfg or home_config()
    ranking = home_ranker.rank(_viewer(viewer_id, claims), now, cfg, ctx, pools, personal)
    sid, as_of = uuid.uuid4().hex, now.isoformat()
    entries = [
        rank_session.Entry(
            s.feats.post_id, s.feats.source, s.feats.reason, tuple(ranking.factors(s))
        )
        for s in ranking.items
    ]
    session = {
        "sid": sid,
        "surface": SURFACE,
        "cfg": cfg.version,
        "items": rank_session.pack(entries),
        "n": len(entries),
        "edge": list(ranking.edge) if ranking.edge else None,
        "cu": ranking.caught_up,
        "as_of": as_of,
    }
    head = _materialize(
        viewer_id,
        [(e.post_id, e.source, e.reason) for e in entries[:size]],
        ranking.content or None,
    )
    items, sources = [i for i, _, _ in head], [s for _, s, _ in head]
    index, caught = _caught_up(session, [n for _, _, n in head], 0, size)
    new_count, anchor = new_since(ranking, since, cfg)
    oldest = _oldest(items, None)
    page = Page(
        items,
        None,
        False,
        sources,
        cfg.version,
        index,
        caught,
        sid=sid,
        new_count=new_count,
        anchor_index=anchor,
        ranking=ranking,
        topics=ranking.topics,
        topic_labels=ranking.topic_labels,
    )
    if rank_session.save(SURFACE, viewer_id, session, cfg.get("session.ttl_s"), _hot()):
        page.next_cursor = _after_slice(session, sid, size, as_of, oldest)
        return page
    # No session: later pages go on chronologically below the head's oldest row.
    more = len(entries) > size or session["edge"] is not None
    page.fallback, page.sid = True, None
    if more:
        page.next_cursor = _latest_cursor(oldest or (as_of, _MAX_ID))
    return page


def reuse_page(viewer_id, size: int, claims: dict | None = None) -> Page | None:
    """A reload (or in-app navigation) back to Home during the same visit, while the
    ranking session lives: offset 0 of the **existing** frozen list, same ``sid``, no
    re-rank (scenario 5, reload to the same card). None when no session is alive."""
    session = rank_session.current(SURFACE, viewer_id, _hot())
    if session is None or not session.get("sid"):
        return None
    as_of = session.get("as_of") or ""
    page = _session_page(viewer_id, session, session["sid"], 0, size, as_of, None, claims)
    page.reused = True
    return page


def _session_page(
    viewer_id, session: dict, sid: str, offset: int, size: int, as_of: str, oldest, claims
) -> Page:
    """Entries of the frozen list from ``offset``: re-checked (E1 to E5, E1b, E1c,
    E6b, E9b), read forward until ``size`` survive or the list ends (08 section 7.3:
    ``o`` indexes the frozen list, so a dropped item never shifts or repeats another,
    and a short page is refilled). The next ``o`` is just past the last entry served;
    every examined entry before it was served or dropped by a named rule."""
    cfg = config.for_surface(SURFACE)
    viewer = _viewer(viewer_id, claims)
    n = session["n"]
    served: list[tuple[FeedItem, str, int]] = []
    dropped: Counter = Counter()
    topics: dict = {}
    labels: dict = {}
    cursor = offset
    # Over-read once (most pages drop nothing), then at most one more read.
    for chunk in (2 * size, 4 * size):
        if len(served) >= size or cursor >= n:
            break
        entries = rank_session.unpack(session["items"], cursor, cursor + chunk)
        outcome = _recheck_entries(viewer_id, viewer, entries, cfg, topics, labels)
        for k, e in enumerate(entries):
            position = cursor + k
            result = outcome[e.post_id]
            if isinstance(result, str):
                dropped[result] += 1
            else:
                served.append((result, e.source, position))
            if len(served) >= size:
                cursor = position + 1
                break
        else:
            cursor += len(entries)
    for rule, count in dropped.items():
        if rule != "visible":
            intel_metrics.eligibility_dropped(rule, count)
    items = [i for i, _, _ in served]
    index, caught = _caught_up(session, [p for _, _, p in served], offset, cursor)
    oldest = _oldest(items, oldest)
    return Page(
        items,
        _after_slice(session, sid, cursor, as_of, oldest),
        False,
        [s for _, s, _ in served],
        session.get("cfg"),
        index,
        caught,
        sid=sid,
        dropped=dict(dropped),
        offset=offset,
        topics=topics,
        topic_labels=labels,
    )


def _recheck_entries(viewer_id, viewer: Viewer, entries, cfg, topics=None, labels=None) -> dict:
    """``{post_id: FeedItem to serve | the name of the rule that dropped it}``."""
    conn = [e.post_id for e in entries if e.source == CONNECTIONS]
    rows = {str(i.post_id): i for i in visible_items(viewer_id).filter(post_id__in=conn)}
    out: dict = {}
    candidates = []
    for e in entries:
        if e.source != CONNECTIONS:
            candidates.append(Candidate(e.post_id, None, e.source, e.reason, None))
        elif e.post_id in rows:
            row = rows[e.post_id]
            kind = (row.snapshot or {}).get("type") or ""
            candidates.append(
                Candidate(e.post_id, str(row.author_id), CONNECTIONS, e.reason, None, kind)
            )
        else:  # gone from the viewer's visible rows (deleted, hidden, snoozed, muted)
            out[e.post_id] = "visible"
    if not candidates:
        return out
    # Fail closed between pages: E1 to E5, E1b, E1c, E6b and E9b again (WP 4.10).
    ctx = recheck_context(viewer, candidates, cfg)
    if topics is not None:
        topics.update(ctx.topic_conf)
    if labels is not None:
        labels.update(ctx.topic_labels)
    for c in candidates:
        rule = None
        if c.source not in ELIGIBLE_SOURCES:
            rule = "E0"
        else:
            for name, applies, fn in RULES:
                if name in RECHECK and c.source in applies and not fn(c, ctx):
                    rule = name
                    break
        if rule is not None:
            out[c.post_id] = rule
        elif c.source == CONNECTIONS:
            out[c.post_id] = rows[c.post_id]
        else:
            ref = ctx.content.get(c.post_id)
            out[c.post_id] = (
                _pulled_item(viewer_id, ref, c.reason) if ref and ref["author_id"] else "E1"
            )
    return out


def next_page(viewer_id, token: str, size: int, claims: dict | None = None) -> Page:
    data = decode_cursor(token)
    if data["k"] == "l":
        return _latest_page(viewer_id, data["t"], data["i"], size, fallback=False)
    sid, offset, as_of = data.get("s"), int(data.get("o", 0)), data.get("a", "")
    oldest = (data["t"], data["i"]) if data.get("t") and data.get("i") else None
    session = rank_session.load(SURFACE, viewer_id, sid, _hot())
    if session is None:
        # Lost or replaced (expiry, another tab's first page, a redis-hot restart):
        # continue chronologically strictly below the oldest row served so far.
        if oldest is not None:
            return _latest_page(viewer_id, oldest[0], oldest[1], size, fallback=True)
        return _latest_page(viewer_id, as_of, _MAX_ID, size, fallback=True)
    return _session_page(viewer_id, session, sid, offset, size, as_of, oldest, claims)
