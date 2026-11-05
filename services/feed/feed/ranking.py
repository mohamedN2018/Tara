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
cursor continues in latest order below its oldest row. When the session is gone
(expired, replaced by a newer first page, or ``redis-hot`` down), the cursor falls
back to latest order from the session's start time and the page says
``fallback: true`` (the client drops posts it already shows).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from django.conf import settings
from django.core import signing
from django.core.cache import caches
from django.db.models import Count, Q
from django.utils.dateparse import parse_datetime
from intel import config
from intel.eligibility import Viewer, recheck
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


def visible_items(viewer_id):
    """The viewer's feed rows minus what they hid, snoozed or muted, and posts of
    deactivated accounts. Every mode starts here."""
    return (
        FeedItem.objects.filter(recipient_id=viewer_id)
        .exclude(post_id__in=PostState.objects.filter(hidden=True).values("post_id"))
        .exclude(post_id__in=feedback.hidden_post_ids(viewer_id))
        .exclude(author_id__in=feedback.snoozed_author_ids(viewer_id))
        .exclude(author_id__in=readmodels.flagged_ids(viewer_id, RelationshipFlag.Kind.MUTE))
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
    """``[(post_id, source, reason)]`` as items, in order; a post no longer visible is
    left out. Connections come from ``FeedItem`` (one query), the rest from
    ``intel_content_ref`` (``refs`` when the caller already read them)."""
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
    for post_id, source, reason in entries:
        if source == CONNECTIONS:
            if post_id in rows:
                out.append((rows[post_id], source))
        elif refs and post_id in refs and refs[post_id]["author_id"]:
            out.append((_pulled_item(viewer_id, refs[post_id], reason), source))
    return out


def rank_items(viewer_id, now: datetime, window: int | None = None, claims=None) -> list[FeedItem]:
    """The viewer's ranked items, best first. Same rows and ``now``, same order."""
    ranking = home_ranker.rank(_viewer(viewer_id, claims), now, home_config(window))
    entries = [(s.feats.post_id, s.feats.source, s.feats.reason) for s in ranking.items]
    return [item for item, _ in _materialize(viewer_id, entries)]


# ---- cursor and session --------------------------------------------------------


def encode_cursor(data: dict) -> str:
    return signing.dumps(data, salt=_SALT, compress=True)


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


def _ranked_cursor(sid: str, offset: int, as_of: str) -> str:
    return encode_cursor({"k": "r", "s": sid, "o": offset, "a": as_of, "f": SURFACE})


def _after_slice(session: dict, sid: str, end: int, as_of: str) -> str | None:
    if end < session["n"]:
        return _ranked_cursor(sid, end, as_of)
    if session.get("edge"):  # the window was full: older rows continue in latest order
        return _latest_cursor(tuple(session["edge"]))
    return None


def first_page(viewer_id, size: int, now: datetime, claims: dict | None = None) -> Page:
    cfg = home_config()
    ranking = home_ranker.rank(_viewer(viewer_id, claims), now, cfg)
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
    }
    head = _materialize(viewer_id, [(e.post_id, e.source, e.reason) for e in entries[:size]])
    items, sources = [i for i, _ in head], [s for _, s in head]
    if rank_session.save(SURFACE, viewer_id, session, cfg.get("session.ttl_s"), _hot()):
        return Page(items, _after_slice(session, sid, size, as_of), False, sources, cfg.version)
    # No session: later pages go on in latest order from now (the client drops repeats).
    more = len(entries) > size or session["edge"] is not None
    return Page(
        items,
        _latest_cursor((as_of, _MAX_ID)) if more else None,
        True,
        sources,
        cfg.version,
    )


def next_page(viewer_id, token: str, size: int, claims: dict | None = None) -> Page:
    data = decode_cursor(token)
    if data["k"] == "l":
        return _latest_page(viewer_id, data["t"], data["i"], size, fallback=False)
    sid, offset, as_of = data.get("s"), int(data.get("o", 0)), data.get("a", "")
    session = rank_session.load(SURFACE, viewer_id, sid, _hot())
    if session is None:
        return _latest_page(viewer_id, as_of, _MAX_ID, size, fallback=True)
    entries = rank_session.unpack(session["items"], offset, offset + size)
    cfg = config.for_surface(SURFACE)
    viewer = _viewer(viewer_id, claims)
    conn = [e.post_id for e in entries if e.source == CONNECTIONS]
    rows = {str(i.post_id): i for i in visible_items(viewer_id).filter(post_id__in=conn)}
    candidates = []
    for e in entries:
        if e.source != CONNECTIONS:
            candidates.append(Candidate(e.post_id, None, e.source, e.reason, None))
        elif e.post_id in rows:  # gone from the viewer's visible rows: not served
            row = rows[e.post_id]
            kind = (row.snapshot or {}).get("type") or ""
            candidates.append(
                Candidate(e.post_id, str(row.author_id), CONNECTIONS, e.reason, None, kind)
            )
    # Fail closed between pages: E1 to E5, E1b, E1c and E6b again (WP 4.10).
    checked = recheck(viewer, candidates, cfg)
    items, sources = [], []
    for c in checked.kept:
        if c.source == CONNECTIONS:
            items.append(rows[c.post_id])
        else:
            ref = checked.content.get(c.post_id)
            if not ref or not ref["author_id"]:
                continue
            items.append(_pulled_item(viewer_id, ref, c.reason))
        sources.append(c.source)
    return Page(
        items,
        _after_slice(session, sid, offset + len(entries), as_of),
        False,
        sources,
        session.get("cfg"),
    )
